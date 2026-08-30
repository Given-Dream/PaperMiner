import sys
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


if __name__ == "__main__":
    unittest.main()
