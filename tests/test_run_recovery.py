import sys
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from run_recovery import (
    MARKER_NAME,
    RunRecoveryStore,
    completion_marker_matches,
    write_completion_marker,
)


OPTIONS = {
    "extract_text": True,
    "extract_formula": True,
    "extract_figures": True,
    "extract_tables": True,
    "extract_sections": True,
    "extract_open_source": True,
    "backend": "pipeline",
    "llm_model": "deepseek-chat",
    "llm_provider": "deepseek",
    "skip_processed": True,
    "use_gpu": True,
    "gpu_assignments": [{"index": 0, "workers": 1}],
}


class RunRecoveryStoreTests(unittest.TestCase):
    def test_wal_state_survives_process_hard_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "crashed.pdf"
            source.write_bytes(b"crash test")
            database = root / "state" / "runs.db"
            child_code = r"""
import os
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from run_recovery import RunRecoveryStore
database = Path(sys.argv[2])
source = Path(sys.argv[3])
store = RunRecoveryStore(database)
run_id = store.create_run(
    mode="full",
    input_directory=source.parent,
    output_directory=source.parent / "output",
    options={"extract_text": True},
    items=[source],
)
store.transition_document(run_id, source, "parsing", increment_attempt=True)
os._exit(87)
"""
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(SCRIPTS_DIR),
                    str(database),
                    str(source),
                ],
                check=False,
            )
            self.assertEqual(result.returncode, 87)

            reopened = RunRecoveryStore(database)
            run = reopened.latest_resumable_run()
            self.assertIsNotNone(run)
            documents = reopened.list_documents(run["run_id"])
            self.assertEqual(documents[0]["status"], "parsing")
            self.assertEqual(documents[0]["attempts"], 1)
            reopened.close()

    def test_transitions_survive_reopen_and_only_unfinished_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = []
            for index in range(3):
                source = root / f"paper-{index}.pdf"
                source.write_bytes(f"PDF {index}".encode("ascii"))
                sources.append(source)

            database = root / "state" / "runs.db"
            store = RunRecoveryStore(database)
            run_id = store.create_run(
                mode="full",
                input_directory=root,
                output_directory=root / "output",
                options=OPTIONS,
                items=sources,
            )
            store.transition_document(
                run_id,
                sources[0],
                "parsing",
                increment_attempt=True,
                gpu_id=0,
            )
            store.transition_document(
                run_id,
                sources[0],
                "raw_validated",
                raw_directory=root / "output" / "raw" / "paper-0" / "auto",
            )
            store.transition_document(run_id, sources[0], "extracting")
            store.transition_document(run_id, sources[0], "complete")
            store.transition_document(
                run_id,
                sources[1],
                "parsing",
                increment_attempt=True,
                gpu_id=0,
            )
            store.close()

            reopened = RunRecoveryStore(database)
            run = reopened.latest_resumable_run()
            self.assertEqual(run["run_id"], run_id)
            resumed = reopened.prepare_resume(run_id)
            by_name = {Path(item["source_path"]).name: item for item in resumed}

            self.assertNotIn("paper-0.pdf", by_name)
            self.assertEqual(by_name["paper-1.pdf"]["previous_status"], "parsing")
            self.assertEqual(by_name["paper-2.pdf"]["previous_status"], "pending")

            documents = {
                Path(item["source_path"]).name: item
                for item in reopened.list_documents(run_id)
            }
            self.assertEqual(documents["paper-0.pdf"]["status"], "complete")
            self.assertEqual(documents["paper-1.pdf"]["status"], "pending")
            self.assertEqual(documents["paper-1.pdf"]["interruptions"], 1)
            self.assertEqual(documents["paper-2.pdf"]["interruptions"], 0)
            self.assertEqual(reopened.get_run(run_id)["recovery_count"], 1)
            reopened.close()

    def test_terminal_failures_are_not_requeued(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "bad.pdf"
            source.write_bytes(b"bad")
            store = RunRecoveryStore(root / "runs.db")
            run_id = store.create_run(
                mode="full",
                input_directory=root,
                output_directory=root / "out",
                options=OPTIONS,
                items=[source],
            )
            store.transition_document(
                run_id,
                source,
                "failed",
                issue_code="test_failure",
            )

            self.assertEqual(store.prepare_resume(run_id), [])
            self.assertEqual(store.summary(run_id)["unfinished"], 0)
            store.close()


class CompletionMarkerTests(unittest.TestCase):
    def test_marker_is_atomic_and_rejects_changed_source_or_options(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "paper.pdf"
            source.write_bytes(b"first")
            extract = root / "extract" / "paper"

            marker = write_completion_marker(
                extract,
                run_id="run-1",
                source_path=source,
                options=OPTIONS,
            )

            self.assertEqual(marker.name, MARKER_NAME)
            self.assertTrue(completion_marker_matches(extract, OPTIONS, source))
            self.assertEqual(list(extract.glob(f"{MARKER_NAME}.*.tmp")), [])

            changed_options = dict(OPTIONS)
            changed_options["extract_tables"] = False
            self.assertFalse(
                completion_marker_matches(extract, changed_options, source)
            )

            source.write_bytes(b"second version")
            self.assertFalse(completion_marker_matches(extract, OPTIONS, source))


if __name__ == "__main__":
    unittest.main()
