import unittest

from src.export import export_rows


class ExportRowsTests(unittest.TestCase):
    def test_all_records(self):
        self.assertEqual(export_rows([["a"], ["b"]]).count("\n"), 2)

    def test_embedded_newline(self):
        self.assertEqual(
            export_rows([["line 1\nline 2"]]), '"line 1\nline 2"\r\n'
        )


if __name__ == "__main__":
    unittest.main()
