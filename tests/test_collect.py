"""Parsers must be pure and tolerant: real device output contains garbage."""

import unittest

from sysdash.collect import (
    parse_battery_capacity,
    parse_cpuinfo,
    parse_meminfo,
    parse_netdev,
    parse_thermal_value,
    parse_uptime_output,
)

MEMINFO = """\
MemTotal:        7541236 kB
MemFree:          534324 kB
MemAvailable:    2342956 kB
Buffers:            2364 kB
Cached:          1969952 kB
SwapTotal:       6291452 kB
SwapFree:        3973128 kB
"""

CPUINFO = """\
processor\t: 0
BogoMIPS\t: 38.40
Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32
CPU implementer\t: 0x41
processor\t: 1
BogoMIPS\t: 38.40
processor\t: 2
processor\t: 3
processor\t: 4
processor\t: 5
processor\t: 6
processor\t: 7
Hardware\t: SM7325
"""

NETDEV = """\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:    1000      10    0    0    0     0          0         0     1000      10    0    0    0     0       0          0
  eth0:    2048      20    0    0    0     0          0         0     4096      30    0    0    0     0       0          0
 wlan0:    1000       5    0    0    0     0          0         0      500       5    0    0    0     0       0          0
"""


class TestMeminfo(unittest.TestCase):
    def test_converts_kb_to_bytes(self):
        mem = parse_meminfo(MEMINFO)
        self.assertEqual(mem["MemTotal"], 7541236 * 1024)
        self.assertEqual(mem["MemAvailable"], 2342956 * 1024)
        self.assertEqual(mem["SwapTotal"], 6291452 * 1024)
        self.assertEqual(mem["SwapFree"], 3973128 * 1024)

    def test_ignores_malformed_lines(self):
        mem = parse_meminfo("garbage\nMemTotal: 100 kB\n::\nMemFree: abc kB\n")
        self.assertEqual(mem, {"MemTotal": 100 * 1024})

    def test_empty_text(self):
        self.assertEqual(parse_meminfo(""), {})


class TestCpuinfo(unittest.TestCase):
    def test_counts_processors_and_finds_model(self):
        cores, model = parse_cpuinfo(CPUINFO)
        self.assertEqual(cores, 8)
        self.assertEqual(model, "SM7325")

    def test_missing_model(self):
        cores, model = parse_cpuinfo("processor: 0\nprocessor: 1\n")
        self.assertEqual(cores, 2)
        self.assertIsNone(model)

    def test_x86_model_name(self):
        cores, model = parse_cpuinfo("processor: 0\nmodel name: AMD Ryzen\n")
        self.assertEqual((cores, model), (1, "AMD Ryzen"))


class TestThermal(unittest.TestCase):
    def test_millidegrees(self):
        self.assertAlmostEqual(parse_thermal_value("45903"), 45.903, places=3)

    def test_degrees(self):
        self.assertAlmostEqual(parse_thermal_value("27.5"), 27.5)

    def test_bogus_sensors_are_dropped(self):
        # Seen on real Android devices: disconnected sensors report near absolute zero.
        self.assertIsNone(parse_thermal_value("-274000"))
        self.assertIsNone(parse_thermal_value("-273000"))
        self.assertIsNone(parse_thermal_value("999999"))

    def test_non_numeric(self):
        self.assertIsNone(parse_thermal_value("NaN"))
        self.assertIsNone(parse_thermal_value(""))


class TestUptime(unittest.TestCase):
    def test_linux_output_with_days(self):
        seconds, load = parse_uptime_output(
            " 17:11:36 up 4 days, 12:16,  0 users,  load average: 4.69, 4.65, 3.48"
        )
        self.assertEqual(seconds, 4 * 86400 + 12 * 3600 + 16 * 60)
        self.assertEqual(load, (4.69, 4.65, 3.48))

    def test_minutes_only(self):
        seconds, load = parse_uptime_output(
            " 10:00:00 up 5 min,  1 user,  load average: 0.00, 0.01, 0.05"
        )
        self.assertEqual(seconds, 5 * 60)

    def test_one_day(self):
        seconds, _ = parse_uptime_output(
            " 10:00:00 up 1 day,  2:03,  1 user,  load average: 0.1, 0.2, 0.3"
        )
        self.assertEqual(seconds, 86400 + 2 * 3600 + 3 * 60)

    def test_macos_load_averages_spelling(self):
        _, load = parse_uptime_output(
            "10:00  up 2 days,  3:00, 5 users, load averages: 1.0 1.2 1.3"
        )
        self.assertEqual(load, (1.0, 1.2, 1.3))

    def test_unparseable(self):
        seconds, load = parse_uptime_output("hello")
        self.assertIsNone(seconds)
        self.assertIsNone(load)


class TestNetdev(unittest.TestCase):
    def test_sums_interfaces_without_loopback(self):
        self.assertEqual(parse_netdev(NETDEV), (2048 + 1000, 4096 + 500))

    def test_no_interfaces(self):
        self.assertIsNone(parse_netdev("header\nheader\n"))

    def test_malformed_row_is_skipped(self):
        text = "  eth0: 1 2 3\n  wlan0: 100 1 0 0 0 0 0 0 200 1 0 0 0 0 0 0\n"
        self.assertEqual(parse_netdev(text), (100, 200))


class TestBattery(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_battery_capacity("62"), 62)
        self.assertEqual(parse_battery_capacity(" 100 \n"), 100)

    def test_out_of_range_or_garbage(self):
        self.assertIsNone(parse_battery_capacity("120"))
        self.assertIsNone(parse_battery_capacity("abc"))
        self.assertIsNone(parse_battery_capacity(None))


if __name__ == "__main__":
    unittest.main()
