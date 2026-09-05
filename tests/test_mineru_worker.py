import argparse
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import mineru_worker


class MinerUWorkerContractTests(unittest.TestCase):
    def test_bounded_document_name_is_forwarded_to_mineru(self):
        captured = {}

        def do_parse(**kwargs):
            captured.update(kwargs)
            output = Path(kwargs["output_dir"]) / kwargs["pdf_file_names"][0] / "auto"
            output.mkdir(parents=True)
            (output / "short.md").write_text("ok", encoding="utf-8")

        mineru_module = types.ModuleType("mineru")
        mineru_module.__file__ = str(SCRIPTS_DIR / "fake_mineru.py")
        mineru_module.__path__ = []
        cli_module = types.ModuleType("mineru.cli")
        cli_module.__path__ = []
        common_module = types.ModuleType("mineru.cli.common")
        common_module.do_parse = do_parse
        common_module.read_fn = lambda path: Path(path).read_bytes()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "a very long original paper title.pdf"
            source.write_bytes(b"%PDF-test")
            output = root / "raw"
            arguments = argparse.Namespace(
                input=source,
                output=output,
                document_name="paper__123456789abc",
                device="cpu",
                backend="pipeline",
                model_source="modelscope",
            )
            modules = {
                "mineru": mineru_module,
                "mineru.cli": cli_module,
                "mineru.cli.common": common_module,
            }
            with (
                mock.patch.object(mineru_worker, "_parse_args", return_value=arguments),
                mock.patch.object(
                    mineru_worker.importlib.metadata,
                    "version",
                    return_value="3.1.0",
                ),
                mock.patch.dict(sys.modules, modules),
            ):
                exit_code = mineru_worker.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["pdf_file_names"], ["paper__123456789abc"])


if __name__ == "__main__":
    unittest.main()
