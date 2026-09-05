import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from mineru_path_policy import (
    SAFE_WINDOWS_PATH_LENGTH,
    choose_child_filename,
    choose_extract_storage_name,
    choose_mineru_storage_name,
    path_text_length,
    projected_mineru_image_path,
    read_source_manifest,
    source_stem_for_directory,
    write_source_manifest,
)
from batch_pdf_processor_gui import BatchPDFProcessorGUI


LONG_STEM = (
    "001_Underground storage of hydrogen in lined rock caverns An overview "
    "of key components and hydrogen embrittlement challenges"
)


class MinerUPathPolicyTests(unittest.TestCase):
    def test_reported_266_character_image_path_is_shortened_deterministically(self):
        raw_root = Path(
            r"C:\Users\admin\AppData\Local\Programs\PaperMiner\output\raw"
        )
        original_projection = projected_mineru_image_path(raw_root, LONG_STEM)
        self.assertEqual(path_text_length(original_projection), 266)

        first = choose_mineru_storage_name(LONG_STEM, raw_root)
        second = choose_mineru_storage_name(LONG_STEM, raw_root)

        self.assertEqual(first, second)
        self.assertNotEqual(first, LONG_STEM)
        self.assertLessEqual(len(first), 64)
        self.assertLessEqual(
            path_text_length(projected_mineru_image_path(raw_root, first)),
            SAFE_WINDOWS_PATH_LENGTH,
        )

    def test_short_document_name_is_not_changed(self):
        raw_root = Path(r"D:\PM_OUT\raw")
        self.assertEqual(
            choose_mineru_storage_name("paper_01", raw_root),
            "paper_01",
        )

    def test_extract_folder_keeps_reported_title_but_repeated_filename_is_short(self):
        extract_root = Path(
            r"C:\Users\admin\AppData\Local\Programs\PaperMiner\output\extract"
        )
        storage_name = choose_extract_storage_name(LONG_STEM, extract_root)
        self.assertEqual(storage_name, LONG_STEM)

        document_dir = extract_root / storage_name
        main_name = choose_child_filename(
            document_dir,
            f"{LONG_STEM}.md",
            "全文.md",
        )
        formula_name = choose_child_filename(
            document_dir / "Formula",
            f"{LONG_STEM}_formula.md",
            "公式.md",
        )
        self.assertEqual(main_name, "全文.md")
        self.assertEqual(formula_name, "公式.md")

    def test_source_manifest_round_trip_restores_original_title(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "paper__abc123"
            manifest = write_source_manifest(
                directory,
                source_stem=LONG_STEM,
                source_path=Path(temporary) / f"{LONG_STEM}.pdf",
            )

            self.assertTrue(manifest.is_file())
            self.assertEqual(
                read_source_manifest(directory)["source_stem"],
                LONG_STEM,
            )
            self.assertEqual(source_stem_for_directory(directory), LONG_STEM)

    def test_existing_mineru_traceback_gets_specific_path_diagnosis(self):
        diagnosis = BatchPDFProcessorGUI.diagnose_mineru_output(
            None,
            [
                "FileNotFoundError: [Errno 2] No such file or directory: "
                "'C:\\Users\\admin\\AppData\\Local\\Programs\\PaperMiner\\"
                f"output\\raw\\{LONG_STEM}\\auto\\images\\{'f' * 64}.jpg'"
            ],
        )
        self.assertEqual(diagnosis["code"], "mineru_windows_path_too_long")

    def test_unsupported_gpu_kernel_gets_repair_diagnosis(self):
        diagnosis = BatchPDFProcessorGUI.diagnose_mineru_output(
            None,
            [
                "torch.AcceleratorError: CUDA error: no kernel image is "
                "available for execution on the device"
            ],
        )
        self.assertEqual(diagnosis["code"], "torch_cuda_arch_mismatch")
        self.assertIn("重装", " ".join(diagnosis["tips"]))

    def test_text_extraction_uses_short_filename_but_keeps_full_title_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw" / "paper_short" / "auto"
            raw.mkdir(parents=True)
            (raw / "paper_short.md").write_text("# Full text", encoding="utf-8")
            extract = root / "extract" / LONG_STEM
            extract.mkdir(parents=True)
            messages = []
            worker = SimpleNamespace(
                log=messages.append,
                find_file_by_glob=lambda directory, exact_name, glob_pattern: (
                    BatchPDFProcessorGUI.find_file_by_glob(
                        None,
                        directory,
                        exact_name,
                        glob_pattern,
                    )
                ),
            )

            result = BatchPDFProcessorGUI.extract_text(
                worker,
                raw,
                extract,
                LONG_STEM,
            )

            self.assertTrue(result)
            self.assertTrue((extract / "全文.md").is_file())
            self.assertFalse((extract / f"{LONG_STEM}.md").exists())


if __name__ == "__main__":
    unittest.main()
