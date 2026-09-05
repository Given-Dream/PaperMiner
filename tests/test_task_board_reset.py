import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from batch_pdf_processor_gui import BatchPDFProcessorGUI


class FakeVariable:
    def __init__(self, value=None):
        self.value = value

    def set(self, value):
        self.value = value


class FakeLabel:
    def __init__(self, text=""):
        self.options = {"text": text}

    def config(self, **kwargs):
        self.options.update(kwargs)


class FakeRoot:
    def __init__(self):
        self.flush_count = 0

    def update_idletasks(self):
        self.flush_count += 1


class TaskBoardResetTests(unittest.TestCase):
    def test_second_run_clears_previous_completion_state_before_precheck(self):
        board = SimpleNamespace(
            progress_var=FakeVariable(100.0),
            status_label=FakeLabel("处理完成 · 61 / 61"),
            progress_text=FakeLabel("上一轮文件.pdf"),
            accent_color="#2563EB",
            root=FakeRoot(),
            stats_refreshes=0,
        )

        def update_stats():
            board.stats_refreshes += 1

        board.update_stats = update_stats

        BatchPDFProcessorGUI._reset_task_board_for_run(board, 12, "full")

        self.assertEqual(board.progress_var.value, 0.0)
        self.assertEqual(board.status_label.options["text"], "正在准备 · 0 / 12")
        self.assertIn("GPU", board.progress_text.options["text"])
        self.assertEqual(board.stats_refreshes, 1)
        self.assertEqual(board.root.flush_count, 1)

    def test_extract_only_uses_raw_preparation_message(self):
        board = SimpleNamespace(
            progress_var=FakeVariable(100.0),
            status_label=FakeLabel("处理完成 · 8 / 8"),
            progress_text=FakeLabel("旧提示"),
            accent_color="#2563EB",
            root=FakeRoot(),
            update_stats=lambda: None,
        )

        BatchPDFProcessorGUI._reset_task_board_for_run(board, 8, "extract_only")

        self.assertEqual(board.progress_var.value, 0.0)
        self.assertIn("raw", board.progress_text.options["text"])


class RecoveryWorkflowTests(unittest.TestCase):
    def test_resume_restores_cpu_choice_after_mode_widget_defaults(self):
        variables = {
            name: FakeVariable()
            for name in (
                "extract_text_var",
                "extract_title_var",
                "extract_formula_var",
                "extract_figures_var",
                "extract_tables_var",
                "extract_sections_var",
                "extract_open_source_var",
                "extract_references_var",
                "use_gpu_var",
                "skip_processed_var",
                "backend_var",
                "llm_model_var",
                "process_mode_var",
            )
        }
        worker = SimpleNamespace(
            **variables,
            llm_settings=None,
            gpu_parallel_preferences={},
            _update_output_paths=lambda: None,
            _refresh_directory_labels=lambda: None,
            check_input_folder=lambda: None,
            _refresh_gpu_summary_label=lambda: None,
        )

        def apply_mode_default():
            worker.use_gpu_var.set(True)

        worker.on_mode_change = apply_mode_default
        BatchPDFProcessorGUI._apply_persisted_run_options(
            worker,
            {
                "mode": "full",
                "input_directory": "D:/papers",
                "output_directory": "D:/results",
                "options": {
                    "extract_text": True,
                    "use_gpu": False,
                    "skip_processed": True,
                    "backend": "pipeline",
                },
            },
        )

        self.assertFalse(worker.use_gpu_var.value)
        self.assertFalse(worker.extract_references_var.value)
        self.assertFalse(worker.extract_title_var.value)

    def test_stop_during_sequential_mineru_keeps_document_nonterminal(self):
        source = Path("paper.pdf")
        transitions = []
        worker = SimpleNamespace(
            is_processing=True,
            skipped_count=0,
            success_count=0,
            failed_count=0,
            last_mineru_issue_code=None,
            FATAL_MINERU_ISSUES=set(),
            log=lambda _message: None,
            _run_option=lambda _name, default=None: default,
            is_already_processed=lambda _name: False,
            _set_thread_log_prefix=lambda _prefix: None,
            _clear_thread_log_prefix=lambda: None,
            _advance_batch_progress=lambda: None,
            _release_batch_memory=lambda _name: None,
        )

        def checkpoint(_source, status, **_kwargs):
            transitions.append(status)
            return True

        def interrupted_mineru(_source):
            worker.is_processing = False
            return None

        worker._checkpoint_document = checkpoint
        worker.run_mineru = interrupted_mineru

        BatchPDFProcessorGUI._process_pdfs_sequential(worker, [source])

        self.assertEqual(transitions, ["parsing"])
        self.assertEqual(worker.failed_count, 0)

    def test_interrupted_outputs_are_kept_until_completion_then_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_id = "20260830_220000_0123456789"
            output = Path(temporary) / "output"
            raw_root = output / "raw"
            extract_root = output / "extract"
            raw = raw_root / "paper"
            extract = extract_root / "paper"
            raw.mkdir(parents=True)
            extract.mkdir(parents=True)
            (raw / "raw.txt").write_text("raw evidence", encoding="utf-8")
            (extract / "result.md").write_text("partial", encoding="utf-8")
            messages = []
            worker = SimpleNamespace(
                output_path=output,
                raw_output_path=raw_root,
                extract_output_path=extract_root,
                log=messages.append,
                _path_is_within=BatchPDFProcessorGUI._path_is_within,
                _is_reparse_or_mount=BatchPDFProcessorGUI._is_reparse_or_mount,
            )

            safe_to_retry = BatchPDFProcessorGUI._quarantine_interrupted_document(
                worker,
                run_id,
                Path(temporary) / "paper.pdf",
                "paper",
                raw_directory=raw / "auto",
            )

            self.assertTrue(safe_to_retry)
            recovery = output / "Recovery" / "Interrupted"
            self.assertFalse(raw.exists())
            self.assertFalse(extract.exists())
            self.assertEqual(
                [path.read_text(encoding="utf-8") for path in recovery.rglob("raw.txt")],
                ["raw evidence"],
            )
            self.assertEqual(
                [path.read_text(encoding="utf-8") for path in recovery.rglob("result.md")],
                ["partial"],
            )

            unrelated = recovery / "20260830_220001_aaaaaaaaaa_20260830_220002"
            unrelated.mkdir()
            (unrelated / "keep.txt").write_text("other run", encoding="utf-8")
            cleanup = BatchPDFProcessorGUI._cleanup_interrupted_recovery(
                worker,
                run_id,
                output_root=output,
            )

            self.assertEqual(cleanup, {"removed": 1, "failed": []})
            self.assertEqual(list(recovery.rglob("raw.txt")), [])
            self.assertEqual(list(recovery.rglob("result.md")), [])
            self.assertEqual(
                (unrelated / "keep.txt").read_text(encoding="utf-8"),
                "other run",
            )
            refused = BatchPDFProcessorGUI._cleanup_interrupted_recovery(
                worker,
                "..",
                output_root=output,
            )
            self.assertEqual(refused["removed"], 0)
            self.assertEqual(refused["failed"], ["invalid_run_id"])
            self.assertTrue((unrelated / "keep.txt").exists())

    def test_cleanup_runs_only_after_batch_reaches_terminal_state(self):
        class FakeStore:
            def __init__(self, unfinished):
                self.unfinished = unfinished
                self.statuses = []

            def summary(self, _run_id):
                return {"total": 2, "unfinished": self.unfinished}

            def set_run_status(self, _run_id, status, error):
                self.statuses.append((status, error))

        completed_calls = []
        completed_store = FakeStore(0)
        completed_worker = SimpleNamespace(
            run_recovery_store=completed_store,
            active_run_id="20260830_220000_0123456789",
            output_path=Path("D:/results"),
            _batch_had_unhandled_error=False,
            _checkpoint_failure=False,
            log=lambda _message: None,
            _cleanup_interrupted_recovery=lambda run_id, **kwargs: (
                completed_calls.append((run_id, kwargs["output_root"]))
                or {"removed": 1, "failed": []}
            ),
        )

        status, _summary = BatchPDFProcessorGUI._finish_active_run_state(
            completed_worker,
            run_stopped=False,
        )

        self.assertEqual(status, "completed")
        self.assertEqual(len(completed_calls), 1)
        self.assertEqual(completed_store.statuses, [("completed", "")])
        self.assertIsNone(completed_worker.active_run_id)

        retry_store = FakeStore(0)
        retry_worker = SimpleNamespace(
            run_recovery_store=retry_store,
            active_run_id="20260830_220000_0123456789",
            output_path=Path("D:/results"),
            _batch_had_unhandled_error=False,
            _checkpoint_failure=False,
            log=lambda _message: None,
            _cleanup_interrupted_recovery=lambda *_args, **_kwargs: {
                "removed": 0,
                "failed": ["locked"],
            },
        )

        status, _summary = BatchPDFProcessorGUI._finish_active_run_state(
            retry_worker,
            run_stopped=False,
        )

        self.assertEqual(status, "completed")
        self.assertEqual(retry_store.statuses[0][0], "cleanup_pending")
        self.assertIn("retried", retry_store.statuses[0][1])

        paused_calls = []
        paused_store = FakeStore(1)
        paused_worker = SimpleNamespace(
            run_recovery_store=paused_store,
            active_run_id="20260830_220000_0123456789",
            output_path=Path("D:/results"),
            _batch_had_unhandled_error=False,
            _checkpoint_failure=False,
            log=lambda _message: None,
            _cleanup_interrupted_recovery=lambda *_args, **_kwargs: paused_calls.append(True),
        )

        status, _summary = BatchPDFProcessorGUI._finish_active_run_state(
            paused_worker,
            run_stopped=True,
        )

        self.assertEqual(status, "paused")
        self.assertEqual(paused_calls, [])
        self.assertEqual(
            paused_worker.active_run_id,
            "20260830_220000_0123456789",
        )

        interrupted_calls = []
        interrupted_store = FakeStore(1)
        interrupted_worker = SimpleNamespace(
            run_recovery_store=interrupted_store,
            active_run_id="20260830_220000_0123456789",
            output_path=Path("D:/results"),
            _batch_had_unhandled_error=True,
            _checkpoint_failure=False,
            log=lambda _message: None,
            _cleanup_interrupted_recovery=lambda *_args, **_kwargs: interrupted_calls.append(True),
        )

        status, _summary = BatchPDFProcessorGUI._finish_active_run_state(
            interrupted_worker,
            run_stopped=False,
        )

        self.assertEqual(status, "interrupted")
        self.assertEqual(interrupted_calls, [])


if __name__ == "__main__":
    unittest.main()
