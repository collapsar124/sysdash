"""CLI smoke tests: one-shot output must be stable and machine-readable."""

import io
import json
import unittest
from contextlib import redirect_stdout

from sysdash.__main__ import main


def run(argv):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    return code, buffer.getvalue()


class TestCli(unittest.TestCase):
    def test_once_json(self):
        code, out = run(["--once", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        for key in ("ts", "mem", "cpu", "disks", "missing"):
            self.assertIn(key, payload)

    def test_once_frame_width_and_no_color(self):
        code, out = run(["--once", "--no-color", "--width", "60"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("┌"))
        self.assertNotIn("\033[", out)
        for line in out.splitlines():
            self.assertEqual(len(line), 60)

    def test_custom_disk_path(self):
        code, out = run(["--once", "--json", "--disk", "/"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["disks"][0]["path"], "/")


if __name__ == "__main__":
    unittest.main()
