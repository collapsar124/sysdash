"""ANSI renderer: turns a :class:`~sysdash.metrics.Snapshot` into a framed
dashboard string.

Rendering is pure (snapshot in, string out) which keeps it trivially testable:
no terminal, no I/O, no clock.  Color is opt-out so captured output stays
diffable and CI-friendly.
"""

from __future__ import annotations

import re
import time
from typing import List, Optional

from .metrics import Snapshot

RESET = "\033[0m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_len(text: str) -> int:
    """Length of ``text`` as displayed (ANSI escapes stripped)."""
    return len(_ANSI_RE.sub("", text))


def paint(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{RESET}" if enabled else text


def fmt_bytes(value: Optional[int]) -> str:
    """Human size with binary units: ``4.9G``, ``512M``, ``23K``."""
    if value is None:
        return "n/a"
    number = float(value)
    for unit in ("B", "K", "M", "G", "T"):
        if abs(number) < 1024 or unit == "T":
            return f"{number:.0f}{unit}" if number >= 100 else f"{number:.1f}{unit}"
        number /= 1024.0
    return f"{number:.0f}T"  # pragma: no cover - unreachable


def fmt_rate(bytes_per_sec: Optional[float]) -> str:
    if bytes_per_sec is None:
        return "n/a"
    return fmt_bytes(int(bytes_per_sec)) + "/s"


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "n/a"
    total = int(max(0, seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def bar(fraction: Optional[float], width: int, filled: str = "█", empty: str = "░") -> str:
    """A ``width``-cell progress bar; the filled part is rounded."""
    if fraction is None:
        return empty * width
    ratio = min(1.0, max(0.0, fraction))
    count = int(round(ratio * width))
    return filled * count + empty * (width - count)


def fraction_color(fraction: Optional[float]) -> str:
    if fraction is None:
        return _DIM
    if fraction < 0.60:
        return _GREEN
    if fraction < 0.85:
        return _YELLOW
    return _RED


# --------------------------------------------------------------------------- #
# Row builders
# --------------------------------------------------------------------------- #


def _row(content: str, inner: int) -> str:
    pad = max(0, inner - visible_len(content))
    return "│ " + content + " " * pad + " │"


def _border(left: str, right: str, width: int) -> str:
    return left + "─" * (width - 2) + right


def _title_row(title: str, stamp: str, width: int) -> str:
    head = f" {title} "
    tail = f" {stamp} "
    dash = max(1, width - 2 - visible_len(head) - visible_len(tail))
    return "┌" + head + "─" * dash + tail + "┐"


def _bar_row(
    label: str, fraction: Optional[float], value: str, inner: int, color: bool
) -> str:
    room = inner - 5 - 2 - visible_len(value)
    cells = max(8, room)
    cells_text = paint(bar(fraction, cells), fraction_color(fraction), color)
    return f"{label:<5}" + cells_text + "  " + value


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #


def render(
    snap: Snapshot,
    prev: Optional[Snapshot] = None,
    width: int = 60,
    color: bool = True,
) -> str:
    """Render one frame.

    ``prev`` is optional; when given, the network row shows a rate computed
    from the delta since that snapshot, otherwise cumulative totals are shown.
    """
    width = max(40, min(120, width))
    inner = width - 4  # "│ " + content + " │" eats four columns

    stamp = time.strftime("%H:%M:%S", time.localtime(snap.ts))
    lines: List[str] = [_title_row("sysdash", stamp, width)]
    lines.append(_border("├", "┤", width))

    # Memory -------------------------------------------------------------
    mem_value = (
        f"{fmt_bytes(snap.used_mem)}/{fmt_bytes(snap.mem_total)}"
        + (f" {snap.mem_fraction * 100:.0f}%" if snap.mem_fraction is not None else "")
    )
    lines.append(_row(_bar_row("MEM", snap.mem_fraction, mem_value, inner, color), inner))
    if snap.swap_total is not None:
        swap_value = (
            f"{fmt_bytes(snap.used_swap)}/{fmt_bytes(snap.swap_total)}"
            + (f" {snap.swap_fraction * 100:.0f}%" if snap.swap_fraction is not None else "")
        )
        lines.append(
            _row(_bar_row("SWAP", snap.swap_fraction, swap_value, inner, color), inner)
        )

    # Load / uptime -------------------------------------------------------
    if snap.load_1 is not None and snap.load_5 is not None and snap.load_15 is not None:
        load_row = f"LOAD  {snap.load_1:.2f} {snap.load_5:.2f} {snap.load_15:.2f}"
        up = f"up {fmt_duration(snap.uptime_s)}"
        load_row += " " * max(2, inner - visible_len(load_row) - visible_len(up)) + up
        lines.append(_row(load_row, inner))

    # CPU -----------------------------------------------------------------
    cpu_parts: List[str] = []
    if snap.cores is not None:
        cpu_parts.append(f"{snap.cores}c")
    if snap.cpu_model:
        cpu_parts.append(snap.cpu_model)
    if snap.cpu_mhz_avg:
        cpu_parts.append(f"{snap.cpu_mhz_avg / 1000:.2f}G")
    if snap.temp_c is not None:
        cpu_parts.append(f"{snap.temp_c:.0f}°C")
    if cpu_parts:
        lines.append(_row("CPU   " + " · ".join(cpu_parts), inner))

    # Disks ---------------------------------------------------------------
    for disk in snap.disks[:2]:
        value = f"{fmt_bytes(disk.used)}/{fmt_bytes(disk.total)} {disk.fraction * 100:.0f}%"
        lines.append(
            _row(_bar_row(disk.path[-4:], disk.fraction, value, inner, color), inner)
        )

    # Network -------------------------------------------------------------
    if snap.net_rx_bytes is not None and snap.net_tx_bytes is not None:
        if prev is not None and prev.net_rx_bytes is not None and prev.net_tx_bytes is not None:
            dt = snap.ts - prev.ts
            if dt > 0:
                rx_rate = max(0, snap.net_rx_bytes - prev.net_rx_bytes) / dt
                tx_rate = max(0, snap.net_tx_bytes - prev.net_tx_bytes) / dt
                net_text = f"↓ {fmt_rate(rx_rate)}  ↑ {fmt_rate(tx_rate)}"
            else:
                net_text = "n/a"
        else:
            net_text = f"Σ ↓ {fmt_bytes(snap.net_rx_bytes)}  ↑ {fmt_bytes(snap.net_tx_bytes)}"
        lines.append(_row(f"NET   {net_text}", inner))

    # Battery -------------------------------------------------------------
    if snap.battery_pct is not None:
        state = f" ({snap.battery_status})" if snap.battery_status else ""
        lines.append(_row(f"BAT   {snap.battery_pct}%{state}", inner))

    # Sources that could not be read ---------------------------------------
    if snap.missing:
        items = ", ".join(f"{name}: {why}" for name, why in sorted(snap.missing.items()))
        note = "n/a — " + items
        if visible_len(note) > inner:
            note = note[: max(0, inner - 1)] + "…"
        lines.append(_row(paint(note, _DIM, color), inner))

    lines.append(_border("└", "┘", width))
    return "\n".join(lines)
