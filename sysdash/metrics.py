"""Typed, immutable snapshot of the metrics sysdash knows how to display.

Every field is optional on purpose: Android strips most of ``/proc`` for app
uids, so a snapshot is allowed to be partial.  What could not be read is
recorded in :attr:`Snapshot.missing` together with a human-readable reason,
and the renderer shows ``n/a`` instead of inventing a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class DiskUsage:
    """Usage of one mounted filesystem, in bytes."""

    path: str
    total: int
    used: int
    free: int

    @property
    def fraction(self) -> float:
        return self.used / self.total if self.total else 0.0


@dataclass(frozen=True)
class Snapshot:
    """One point-in-time reading of the machine."""

    ts: float

    # Memory (bytes)
    mem_total: Optional[int] = None
    mem_available: Optional[int] = None
    swap_total: Optional[int] = None
    swap_free: Optional[int] = None

    # CPU / load
    cores: Optional[int] = None
    cpu_model: Optional[str] = None
    cpu_mhz_avg: Optional[float] = None
    cpu_mhz_max: Optional[float] = None
    load_1: Optional[float] = None
    load_5: Optional[float] = None
    load_15: Optional[float] = None
    uptime_s: Optional[float] = None

    # Thermal: (sensor label, °C) for the hottest plausible sensor
    temp_c: Optional[float] = None
    temp_label: Optional[str] = None

    # Storage
    disks: List[DiskUsage] = field(default_factory=list)

    # Network counters (cumulative bytes, since boot)
    net_rx_bytes: Optional[int] = None
    net_tx_bytes: Optional[int] = None

    # Battery
    battery_pct: Optional[int] = None
    battery_status: Optional[str] = None

    # source name -> why it is missing (e.g. "permission denied")
    missing: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ helpers

    @property
    def used_mem(self) -> Optional[int]:
        if self.mem_total is None or self.mem_available is None:
            return None
        return self.mem_total - self.mem_available

    @property
    def mem_fraction(self) -> Optional[float]:
        used = self.used_mem
        if used is None or not self.mem_total:
            return None
        return used / self.mem_total

    @property
    def used_swap(self) -> Optional[int]:
        if self.swap_total is None or self.swap_free is None:
            return None
        return self.swap_total - self.swap_free

    @property
    def swap_fraction(self) -> Optional[float]:
        used = self.used_swap
        if used is None or not self.swap_total:
            return None
        return used / self.swap_total

    @property
    def hottest_disk(self) -> Optional[DiskUsage]:
        return max(self.disks, key=lambda d: d.fraction) if self.disks else None


def snapshot_to_dict(snap: Snapshot) -> Dict[str, object]:
    """JSON-friendly view of a snapshot (used by ``--json``)."""

    def gb(value: Optional[int]) -> Optional[float]:
        return round(value / 1024**3, 2) if value is not None else None

    return {
        "ts": round(snap.ts, 3),
        "mem": {
            "total_gb": gb(snap.mem_total),
            "available_gb": gb(snap.mem_available),
            "used_gb": gb(snap.used_mem),
            "used_pct": (
                round(snap.mem_fraction * 100, 1) if snap.mem_fraction is not None else None
            ),
            "swap_total_gb": gb(snap.swap_total),
            "swap_used_gb": gb(snap.used_swap),
        },
        "cpu": {
            "cores": snap.cores,
            "model": snap.cpu_model,
            "mhz_avg": round(snap.cpu_mhz_avg, 1) if snap.cpu_mhz_avg else None,
            "mhz_max": round(snap.cpu_mhz_max, 1) if snap.cpu_mhz_max else None,
            "temp_c": round(snap.temp_c, 1) if snap.temp_c is not None else None,
            "temp_sensor": snap.temp_label,
            "load": [snap.load_1, snap.load_5, snap.load_15],
            "uptime_s": round(snap.uptime_s, 1) if snap.uptime_s is not None else None,
        },
        "disks": [
            {
                "path": d.path,
                "total_gb": gb(d.total),
                "used_gb": gb(d.used),
                "used_pct": round(d.fraction * 100, 1),
            }
            for d in snap.disks
        ],
        "net": {
            "rx_bytes": snap.net_rx_bytes,
            "tx_bytes": snap.net_tx_bytes,
        },
        "battery": {"pct": snap.battery_pct, "status": snap.battery_status},
        "missing": dict(snap.missing),
    }


def load_triple(snap: Snapshot) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    return snap.load_1, snap.load_5, snap.load_15
