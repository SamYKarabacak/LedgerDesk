"""Ensure build-output cleanup cannot remove source or unrelated user files."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_windows import ROOT, prepare_output


class BuildOutputTests(unittest.TestCase):
    def test_source_project_cannot_be_an_output_folder(self):
        with self.assertRaises(RuntimeError):
            prepare_output(ROOT.parent)
        self.assertTrue((ROOT / "income_tracker.py").is_file())

    def test_unrelated_existing_folder_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            unrelated = output / "LedgerDesk"
            unrelated.mkdir()
            important = unrelated / "keep.txt"
            important.write_text("Keep this user file.")
            with self.assertRaises(RuntimeError):
                prepare_output(output)
            self.assertEqual(important.read_text(), "Keep this user file.")

    def test_owned_output_can_be_rebuilt_without_touching_siblings(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            sibling = output / "other.txt"
            sibling.write_text("Keep the sibling.")
            bundle = prepare_output(output)
            (bundle / "obsolete.txt").write_text("Old build.")
            rebuilt = prepare_output(output)
            self.assertFalse((rebuilt / "obsolete.txt").exists())
            self.assertTrue((rebuilt / "app").is_dir())
            self.assertEqual(sibling.read_text(), "Keep the sibling.")


if __name__ == "__main__":
    unittest.main()
