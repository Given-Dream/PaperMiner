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
                "extract_formula_var",
                "extract_figures_var",
                "extract_tables_var",
                "extract_sections_var",
                "extract_open_source_var",
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

    def test_interrupted_outputs_are_moved_to_recovery_not_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
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
            )

            safe_to_retry = BatchPDFProcessorGUI._quarantine_interrupted_document(
                worker,
                "run-test",
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


if __name__ == "__main__":
    unittest.main()
