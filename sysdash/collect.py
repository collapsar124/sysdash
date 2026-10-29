"""Metric collection with honest, layered fallbacks.

Android app sandboxes hide most of ``/proc`` and ``/sys`` from non-root uids,
so every source here is best-effort: a source that fails is recorded in
``Snapshot.missing`` instead of crashing the dashboard.  The parsers are pure
functions (text in, value out) so the whole collection layer is unit-testable
without a real device.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time
from typing import Dict, List, Optional, Tuple

from .metrics import DiskUsage, Snapshot

# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _reason(err: BaseException) -> str:
    if isinstance(err, PermissionError):
        return "permission denied"
    if isinstance(err, FileNotFoundError):
        return "not available"
    if isinstance(err, IsADirectoryError):
        return "not available"
    text = str(err).strip() or err.__class__.__name__
    return text


def _try_read(path: str) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(text, None)`` or ``(None, reason)``."""
    try:
        return _read(path), None
    except OSError as err:
        return None, _reason(err)


# --------------------------------------------------------------------------- #
# Pure parsers (unit-tested with captured device output)
# --------------------------------------------------------------------------- #


def parse_meminfo(text: str) -> Dict[str, int]:
    """Parse ``/proc/meminfo``; values are converted from kB to bytes."""
    out: Dict[str, int] = {}
    for line in text.splitlines():
        key, sep, rest = line.partition(":")
        if not sep:
            continue
        parts = rest.split()
        if not parts:
            continue
        try:
            out[key.strip()] = int(parts[0]) * 1024
        except ValueError:
            continue
    return out


def parse_cpuinfo(text: str) -> Tuple[int, Optional[str]]:
    """Count ``processor`` entries and find a human-readable model name."""
    cores = 0
    model: Optional[str] = None
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "processor":
            cores += 1
        elif key in ("model name", "Hardware", "cpu model") and value and model is None:
            model = value
    return cores, model


def parse_thermal_value(raw: str) -> Optional[float]:
    """Return degrees Celsius for one ``thermal_zone*/temp`` reading.

    Kernels report either degrees or millidegrees; bogus sensors report values
    such as ``-274000``, which are dropped rather than displayed.
    """
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    if abs(value) >= 1000:
        value /= 1000.0
    if not -50.0 <= value <= 150.0:
        return None
    return value


_UPTIME_LOAD = [
    r"load averages?:\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)",
]
_UPTIME_DURATION = r"up\s+(?:(\d+)\s+days?,\s*)?(?:(\d+):(\d+)|(\d+)\s+mins?)"


def parse_uptime_output(text: str) -> Tuple[Optional[float], Optional[Tuple[float, float, float]]]:
    """Parse the output of ``uptime`` into ``(uptime_seconds, load_1_5_15)``."""
    import re

    load: Optional[Tuple[float, float, float]] = None
    for pattern in _UPTIME_LOAD:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            load = (float(match.group(1)), float(match.group(2)), float(match.group(3)))
            break

    seconds: Optional[float] = None
    match = re.search(_UPTIME_DURATION, text)
    if match:
        days = int(match.group(1) or 0)
        if match.group(2) is not None:
            hours, minutes = int(match.group(2)), int(match.group(3))
        else:
            hours, minutes = 0, int(match.group(4) or 0)
        seconds = float(days * 86400 + hours * 3600 + minutes * 60)
    return seconds, load


def parse_netdev(text: str) -> Optional[Tuple[int, int]]:
    """Sum rx/tx byte counters from ``/proc/net/dev`` (loopback excluded)."""
    rx = tx = 0
    seen = False
    for line in text.splitlines():
        name, sep, rest = line.partition(":")
        if not sep:
            continue
        name = name.strip()
        if not name or name == "lo":
            continue
        fields = rest.split()
        if len(fields) < 9:
            continue
        try:
            rx += int(fields[0])
            tx += int(fields[8])
            seen = True
        except ValueError:
            continue
    return (rx, tx) if seen else None


def parse_battery_capacity(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if 0 <= value <= 100 else None


# --------------------------------------------------------------------------- #
# Readers (touch the real filesystem; failures become ``missing`` entries)
# --------------------------------------------------------------------------- #


def _read_meminfo(missing: Dict[str, str]) -> Dict[str, int]:
    text, err = _try_read("/proc/meminfo")
    if text is None:
        missing["memory"] = err or "not available"
        return {}
    try:
        return parse_meminfo(text)
    except (OSError, ValueError) as err2:
        missing["memory"] = _reason(err2)
        return {}


def _read_cpu(missing: Dict[str, str]) -> Tuple[Optional[int], Optional[str]]:
    text, err = _try_read("/proc/cpuinfo")
    if text is None:
        missing["cpu"] = err or "not available"
        return None, None
    try:
        cores, model = parse_cpuinfo(text)
    except (OSError, ValueError) as err2:
        missing["cpu"] = _reason(err2)
        return None, None
    if not cores:
        missing["cpu"] = "no processors listed"
    return (cores or None), model


def _read_cpu_freq() -> Optional[Tuple[float, float]]:
    """Average and maximum current CPU frequency in MHz, if exposed."""
    current: List[float] = []
    maximum: List[float] = []
    for path in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"):
        text, _ = _try_read(path)
        if text:
            try:
                current.append(int(text.strip()) / 1000.0)
            except ValueError:
                pass
    for path in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/cpuinfo_max_freq"):
        text, _ = _try_read(path)
        if text:
            try:
                maximum.append(int(text.strip()) / 1000.0)
            except ValueError:
                pass
    if not current:
        return None
    return (sum(current) / len(current), max(maximum) if maximum else max(current))


def _read_thermal() -> Optional[Tuple[float, str]]:
    """Hottest plausible sensor as ``(celsius, label)``."""
    sensors: List[Tuple[str, float]] = []
    for path in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")):
        text, _ = _try_read(path)
        if text is None:
            continue
        celsius = parse_thermal_value(text)
        if celsius is None:
            continue
        zone = os.path.basename(os.path.dirname(path))
        type_text, _ = _try_read(os.path.join(os.path.dirname(path), "type"))
        sensors.append((type_text.strip() if type_text else zone, celsius))
    if not sensors:
        return None

    preferred = ("cpu", "soc", "gpu", "board")
    hits = [s for s in sensors if any(word in s[0].lower() for word in preferred)]
    chosen = max(hits or sensors, key=lambda s: s[1])
    return chosen[1], chosen[0]


def _read_uptime(
    missing: Dict[str, str],
) -> Tuple[Optional[float], Optional[Tuple[float, float, float]]]:
    # Preferred: the ``uptime`` command (works where /proc/uptime is masked).
    try:
        proc = subprocess.run(
            ["uptime"], capture_output=True, text=True, timeout=3, check=False
        )
        if proc.returncode == 0 and proc.stdout:
            seconds, load = parse_uptime_output(proc.stdout)
            if seconds is not None or load is not None:
                return seconds, load
    except (OSError, subprocess.SubprocessError):
        pass

    # Fallback: /proc/uptime + /proc/loadavg.
    text, err = _try_read("/proc/uptime")
    seconds: Optional[float] = None
    if text:
        try:
            seconds = float(text.split()[0])
        except (IndexError, ValueError):
            seconds = None

    load: Optional[Tuple[float, float, float]] = None
    text, _ = _try_read("/proc/loadavg")
    if text:
        try:
            parts = text.split()
            load = (float(parts[0]), float(parts[1]), float(parts[2]))
        except (IndexError, ValueError):
            load = None

    if seconds is None and load is None:
        missing["uptime"] = err or "not available"
    return seconds, load


def _read_disks(paths: List[str], missing: Dict[str, str]) -> List[DiskUsage]:
    disks: List[DiskUsage] = []
    for path in paths:
        try:
            usage = shutil.disk_usage(path)
        except OSError as err:
            missing.setdefault("disk", _reason(err))
            continue
        disks.append(DiskUsage(path=path, total=usage.total, used=usage.used, free=usage.free))
    return disks


def _read_net(missing: Dict[str, str]) -> Tuple[Optional[int], Optional[int]]:
    text, err = _try_read("/proc/net/dev")
    if text is None:
        missing["network"] = err or "not available"
        return None, None
    counters = parse_netdev(text)
    if counters is None:
        missing["network"] = "unparseable /proc/net/dev"
        return None, None
    return counters


def _read_battery(missing: Dict[str, str]) -> Tuple[Optional[int], Optional[str]]:
    for path in sorted(glob.glob("/sys/class/power_supply/*/capacity")):
        text, err = _try_read(path)
        if text is None:
            missing["battery"] = err or "not available"
            continue
        pct = parse_battery_capacity(text)
        if pct is None:
            continue
        status_text, _ = _try_read(os.path.join(os.path.dirname(path), "status"))
        return pct, status_text.strip() if status_text else None
    if "battery" not in missing:
        missing["battery"] = "no power_supply"
    return None, None


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def default_disk_paths() -> List[str]:
    paths = ["/"]
    for candidate in ("/data", "/sdcard"):
        if os.path.ismount(candidate) and candidate not in paths:
            paths.append(candidate)
    return paths


def collect_snapshot(disk_paths: Optional[List[str]] = None) -> Snapshot:
    """Read every available source once and return an immutable snapshot."""
    missing: Dict[str, str] = {}
    mem = _read_meminfo(missing)
    cores, model = _read_cpu(missing)
    freq = _read_cpu_freq()
    thermal = _read_thermal()
    uptime_s, load = _read_uptime(missing)
    disks = _read_disks(disk_paths if disk_paths is not None else default_disk_paths(), missing)
    rx, tx = _read_net(missing)
    battery_pct, battery_status = _read_battery(missing)

    return Snapshot(
        ts=time.time(),
        mem_total=mem.get("MemTotal"),
        mem_available=mem.get("MemAvailable"),
        swap_total=mem.get("SwapTotal"),
        swap_free=mem.get("SwapFree"),
        cores=cores,
        cpu_model=model,
        cpu_mhz_avg=freq[0] if freq else None,
        cpu_mhz_max=freq[1] if freq else None,
        load_1=load[0] if load else None,
        load_5=load[1] if load else None,
        load_15=load[2] if load else None,
        uptime_s=uptime_s,
        temp_c=thermal[0] if thermal else None,
        temp_label=thermal[1] if thermal else None,
        disks=disks,
        net_rx_bytes=rx,
        net_tx_bytes=tx,
        battery_pct=battery_pct,
        battery_status=battery_status,
        missing=missing,
    )
