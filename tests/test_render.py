"""Renderer and formatter tests — no terminal required."""

import unittest

from sysdash.metrics import DiskUsage, Snapshot, snapshot_to_dict
from sysdash.render import (
    bar,
    fmt_bytes,
    fmt_duration,
    fmt_rate,
    render,
    visible_len,
)

FULL = Snapshot(
    ts=1_700_000_000.0,
    mem_total=7_541_236 * 1024,
    mem_available=2_342_956 * 1024,
    swap_total=6_291_452 * 1024,
    swap_free=3_973_128 * 1024,
    cores=8,
    cpu_model="SM7325",
    cpu_mhz_avg=1324.8,
    cpu_mhz_max=1804.8,
    load_1=4.69,
    load_5=4.65,
    load_15=3.48,
    uptime_s=4 * 86400 + 12 * 3600 + 16 * 60,
    temp_c=45.9,
    temp_label="board_thermal",
    disks=[DiskUsage("/", 118_000_000_000, 23_000_000_000, 95_000_000_000)],
    net_rx_bytes=12_345_678_901,
    net_tx_bytes=4_567_890_123,
    battery_pct=62,
    battery_status="Charging",
)

EMPTY = Snapshot(ts=1_700_000_000.0, missing={"memory": "permission denied"})


class TestFormatters(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(fmt_bytes(None), "n/a")
        self.assertEqual(fmt_bytes(0), "0.0B")
        self.assertEqual(fmt_bytes(1536), "1.5K")
        self.assertEqual(fmt_bytes(7_541_236 * 1024), "7.2G")
        self.assertEqual(fmt_bytes(118_000_000_000), "110G")

    def test_rate(self):
        self.assertEqual(fmt_rate(None), "n/a")
        self.assertEqual(fmt_rate(1536.0), "1.5K/s")

    def test_duration(self):
        self.assertEqual(fmt_duration(None), "n/a")
        self.assertEqual(fmt_duration(0), "0s")
        self.assertEqual(fmt_duration(5), "5s")
        self.assertEqual(fmt_duration(5 * 60 + 3), "5m 03s")
        self.assertEqual(fmt_duration(3 * 3600 + 5 * 60), "3h 05m")
        self.assertEqual(fmt_duration(4 * 86400 + 12 * 3600 + 16 * 60), "4d 12h")

    def test_bar(self):
        self.assertEqual(bar(0.5, 10), "█████░░░░░")
        self.assertEqual(bar(1.0, 4), "████")
        self.assertEqual(bar(2.0, 4), "████")  # clamped
        self.assertEqual(bar(-1.0, 4), "░░░░")
        self.assertEqual(bar(None, 4), "░░░░")

    def test_visible_len_strips_ansi(self):
        self.assertEqual(visible_len("\033[32m████\033[0m"), 4)


class TestRender(unittest.TestCase):
    def test_frame_is_exactly_width_columns(self):
        for width in (40, 60, 80, 120):
            frame = render(FULL, width=width, color=False)
            for line in frame.splitlines():
                self.assertEqual(visible_len(line), width, f"width={width}: {line!r}")

    def test_contains_expected_labels_and_values(self):
        frame = render(FULL, width=60, color=False)
        for token in ("sysdash", "MEM", "SWAP", "LOAD", "CPU", "NET", "BAT", "8c", "62%"):
            self.assertIn(token, frame)

    def test_no_ansi_when_color_disabled(self):
        frame = render(FULL, width=60, color=False)
        self.assertNotIn("\033[", frame)

    def test_ansi_when_color_enabled(self):
        frame = render(FULL, width=60, color=True)
        self.assertIn("\033[", frame)

    def test_empty_snapshot_still_renders(self):
        frame = render(EMPTY, width=40, color=False)
        self.assertIn("MEM", frame)
        self.assertIn("n/a", frame)
        self.assertIn("permission denied", frame)

    def test_network_rate_uses_previous_snapshot(self):
        prev = Snapshot(ts=1_700_000_000.0, net_rx_bytes=1000, net_tx_bytes=500)
        cur = Snapshot(ts=1_700_000_001.0, net_rx_bytes=3048, net_tx_bytes=2548)
        frame = render(cur, prev=prev, width=60, color=False)
        self.assertIn("↓ 2.0K/s", frame)
        self.assertIn("↑ 2.0K/s", frame)

    def test_first_frame_shows_cumulative_network(self):
        frame = render(FULL, prev=None, width=60, color=False)
        self.assertIn("Σ", frame)

    def test_long_missing_note_is_truncated(self):
        snap = Snapshot(
            ts=1_700_000_000.0,
            missing={
                "network": "permission denied",
                "battery": "permission denied",
                "disk": "permission denied",
                "uptime": "permission denied",
            },
        )
        frame = render(snap, width=40, color=False)
        for line in frame.splitlines():
            self.assertEqual(visible_len(line), 40)

    def test_snapshot_to_dict_is_json_ready(self):
        import json

        payload = snapshot_to_dict(FULL)
        text = json.dumps(payload)
        self.assertIn("mem", text)
        self.assertEqual(payload["cpu"]["load"], [4.69, 4.65, 3.48])
        self.assertEqual(payload["battery"]["pct"], 62)


if __name__ == "__main__":
    unittest.main()
