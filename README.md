# sysdash

[![CI](https://github.com/your-name/sysdash/actions/workflows/ci.yml/badge.svg)](https://github.com/your-name/sysdash/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](pyproject.toml)

A tiny terminal dashboard for **memory, CPU, load, thermal, disk, network and
battery** — written for Android/Termux, but it runs fine on Linux and macOS too.

Pure Python standard library. No `psutil`, no C extensions, no build step.

```
┌ sysdash ───────────────────────────────────────────── 17:14:04 ┐
├────────────────────────────────────────────────────────────────┤
│ MEM  ██████████████████████░░░░░░░░░░  5.0G/7.2G 70%          │
│ SWAP ████████████░░░░░░░░░░░░░░░░░░░░  2.2G/6.0G 36%          │
│ LOAD  4.10 4.54 3.62                           up 4d 12h      │
│ CPU   8c · SM7325 · 1.77G · 69°C                               │
│ /    ███████████████████████████████  2.8G/2.8G 100%          │
│ data ███████████████████████████████░  215G/225G 96%          │
│ n/a — battery: no power_supply, network: permission denied    │
└────────────────────────────────────────────────────────────────┘
```

## Why

Android app sandboxes hide most of `/proc` and `/sys` from non-root uids:
`/proc/stat`, `/proc/loadavg` and `/proc/uptime` are typically unreadable, and
popular tools such as `psutil` silently fall back to zeros or crash.

sysdash treats every data source as optional. It probes a chain of fallbacks
(procfs → sysfs → the `uptime(1)` command) and honestly reports
`n/a — network: permission denied` for whatever it cannot read, instead of
showing a fake `0%`.

## Install

```bash
pipx install sysdash        # or: pip install sysdash
```

From a checkout:

```bash
git clone https://github.com/your-name/sysdash
cd sysdash
pip install -e .
sysdash
```

Termux: `pkg install python && pip install sysdash`.

## Usage

```bash
sysdash                       # live dashboard, refresh every second
sysdash --interval 0.5        # faster refresh
sysdash --once                # print one frame and exit
sysdash --once --no-color     # pipe-friendly, no ANSI escapes
sysdash --json                # machine-readable single object
sysdash --disk /data --disk / # choose filesystems
sysdash --width 72            # fixed frame width
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--once` | off | render a single frame and exit |
| `--interval SECONDS` | `1.0` | refresh interval, minimum `0.2` |
| `--json` | off | emit JSON; in live mode one object per line |
| `--no-color` | off | disable ANSI colors |
| `--width COLS` | terminal width | clamp frame width (40–120) |
| `--disk PATH` | `/`, plus mounted `/data`, `/sdcard` | filesystems to show, repeatable |

Press `Ctrl-C` to exit; the cursor is restored on the way out.

## Data sources

| Metric | Primary source | Fallbacks |
| --- | --- | --- |
| Memory / swap | `/proc/meminfo` | — |
| CPU cores, model | `/proc/cpuinfo` | — |
| CPU frequency | `…/cpufreq/scaling_cur_freq` per core | — |
| Load average, uptime | `uptime(1)` | `/proc/loadavg`, `/proc/uptime` |
| Temperature | `thermal_zone*/temp` + `type` | bogus sensors filtered (`-27x°C` rejected) |
| Disk | `shutil.disk_usage()` | — |
| Network | `/proc/net/dev` (loopback excluded) | — |
| Battery | `/sys/class/power_supply/*/capacity` | — |
| CPU usage % | *not collected on Android* | `/proc/stat` is masked |

Anything unreadable is listed in the footer with its reason. `--json` exposes
the same data, including the `missing` map.

## Tests

37 unit tests cover every parser with captured real-device output, plus
renderer geometry and CLI smoke tests. They run on the standard library alone:

```bash
python -m unittest discover -s tests -v
```

The parsers are pure functions (text in, value out), so none of the tests need
a phone, a terminal, or `/proc` access.

## Project layout

```
sysdash/
├── sysdash/
│   ├── collect.py    # parsers + readers with layered fallbacks
│   ├── metrics.py    # frozen dataclasses + JSON view
│   ├── render.py     # pure ANSI renderer
│   └── __main__.py   # CLI + refresh loop
├── tests/            # unittest suite
└── .github/workflows/ci.yml
```

## Design notes

- **Zero dependencies** — stdlib only, so it installs anywhere Python does.
- **Pure rendering** — `render(snapshot) -> str`; easy to test, easy to pipe.
- **Honest fallbacks** — a missing metric is `n/a` plus a reason, never `0`.
- **No config file** — flags are enough for a dashboard.

## License

[MIT](LICENSE)
