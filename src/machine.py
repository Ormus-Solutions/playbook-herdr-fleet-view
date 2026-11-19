#!/usr/bin/env python3
"""Machine load for the fleet view: CPU load, RAM, swap, disk, uptime, and the
programs that hold the most RAM.

This file has two jobs:
- run on its own, it is the probe: it reads this machine and prints one JSON
  object. That is how a remote machine is read: `ssh <alias> python3 -` with
  this file on stdin, so nothing has to be installed there. For that reason it
  imports only the standard library and runs on Python 3.9 or newer.
- imported, it reads a machine from the config: this one, one over ssh, or a
  saved reading in a file (the demo and the tests use files).

The memory-sum lesson lives in `program_rows`: a plain sum of RSS counts every
shared page once per process, so it can report far more RAM than the machine
has. Read its docstring before you change it.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

KIB = 1024
SSH_TIMEOUT = 20  # seconds for the whole remote probe


def meminfo(text: str) -> Dict[str, int]:
    """/proc/meminfo as bytes per key ("MemTotal: 1024 kB" -> 1048576)."""
    out = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            out[key] = int(parts[0]) * KIB
    return out


def process_row(status_text: str) -> Optional[Dict[str, Any]]:
    """One process from /proc/PID/status: its name and its three RSS parts.

    RSS (resident set size) is the RAM a process maps, in three parts:
    RssAnon is its own memory, RssFile the program file and libraries it
    maps (shared by every copy of the program), RssShmem shared memory.
    A kernel thread has no Rss lines and gives None.
    """
    fields = {}
    for line in status_text.splitlines():
        key, _, rest = line.partition(":")
        fields[key] = rest.strip()
    if "RssAnon" not in fields:
        return None

    def kib(key: str) -> int:
        parts = fields.get(key, "0").split()
        return int(parts[0]) * KIB if parts and parts[0].isdigit() else 0

    return {
        "name": fields.get("Name", "?"),
        "anon": kib("RssAnon"),
        "file": kib("RssFile"),
        "shmem": kib("RssShmem"),
    }


def program_rows(procs: Iterable[Dict[str, Any]], top: int = 5) -> List[Dict[str, Any]]:
    """RAM per program (processes with the same name), largest first.

    The lesson: a sum of plain RSS counts each shared page once per process.
    Forty copies of node map the same program file, and twelve database
    workers map the same shared buffers, so their RSS sum can be several times
    the RAM they really hold, even more than the machine has.

    So `ram` is the sum of each process's own memory (RssAnon) plus the
    largest shared part (RssShmem) of one of them. File pages are left out:
    they are the kernel's page cache, which it can drop and read again.
    `rss_sum` is the plain sum, kept so the view can show the difference.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for p in procs:
        groups.setdefault(p["name"], []).append(p)
    rows = []
    for name, ps in groups.items():
        rows.append({
            "name": name,
            "count": len(ps),
            "ram": sum(p["anon"] for p in ps) + max(p["shmem"] for p in ps),
            "rss_sum": sum(p["anon"] + p["file"] + p["shmem"] for p in ps),
        })
    rows.sort(key=lambda r: (-r["ram"], r["name"]))
    return rows[:top]


def read_processes(proc: Path = Path("/proc")) -> List[Dict[str, Any]]:
    """Every process this user can read. /proc/PID/status is readable for all."""
    out = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            row = process_row((entry / "status").read_text(errors="replace"))
        except OSError:  # the process ended while we read
            continue
        if row:
            out.append(row)
    return out


def probe(top: int = 5) -> Dict[str, Any]:
    """Read this machine. Linux gives everything; other systems give load,
    cores and disk, and say that RAM is not read there."""
    disk = shutil.disk_usage("/")
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    out: Dict[str, Any] = {
        "ok": True,
        "system": platform.system(),
        "cores": os.cpu_count() or 1,
        "load": [round(x, 2) for x in load],
        "disk_total": disk.total,
        "disk_used": disk.used,
        "uptime": None,
        "mem_total": None,
        "mem_available": None,
        "swap_total": None,
        "swap_free": None,
        "programs": [],
        "note": "",
    }
    if platform.system() != "Linux":
        out["note"] = "RAM and programs are read on Linux only"
        return out
    mem = meminfo(Path("/proc/meminfo").read_text())
    out.update({
        "uptime": float(Path("/proc/uptime").read_text().split()[0]),
        "mem_total": mem.get("MemTotal"),
        "mem_available": mem.get("MemAvailable"),
        "swap_total": mem.get("SwapTotal"),
        "swap_free": mem.get("SwapFree"),
        "programs": program_rows(read_processes(), top),
    })
    return out


def failed(reason: str) -> Dict[str, Any]:
    return {"ok": False, "error": reason}


def short_reason(stderr: str) -> str:
    """The last line of an error, clipped: "Connection timed out"."""
    lines = [line.strip() for line in stderr.strip().splitlines() if line.strip()]
    text = lines[-1] if lines else "no answer"
    # ssh puts the reason after the last colon: "connect to host x port 22: Connection refused"
    return text.rsplit(": ", 1)[-1][:60]


def ssh_argv(alias: str, top: int) -> List[str]:
    """`python3 -` runs the program it reads on stdin; nothing is copied there.
    BatchMode: never stop to ask for a password, the pane cannot answer."""
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", alias,
            "python3", "-", str(int(top))]


def read_ssh(alias: str, top: int) -> Dict[str, Any]:
    source = Path(__file__).read_text(encoding="utf-8")
    try:
        done = subprocess.run(ssh_argv(alias, top), input=source, capture_output=True,
                              text=True, timeout=SSH_TIMEOUT)
    except FileNotFoundError:
        return failed("ssh is not installed")
    except subprocess.TimeoutExpired:
        return failed(f"no answer in {SSH_TIMEOUT} s")
    if done.returncode != 0:
        return failed(short_reason(done.stderr))
    try:
        return json.loads(done.stdout)
    except ValueError:
        return failed("the probe did not answer in JSON")


def read_file(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        return failed(e.strerror or "cannot read the file")
    except ValueError:
        return failed("the file is not JSON")


def read_machine(machine: Dict[str, Any], top: int = 5) -> Dict[str, Any]:
    """One reading for a [[machines]] entry: from a file, over ssh, or here."""
    if machine.get("file"):
        reading = read_file(Path(machine["file"]))
    elif machine.get("ssh"):
        reading = read_ssh(machine["ssh"], top)
    else:
        try:
            reading = probe(top)
        except OSError as e:
            reading = failed(e.strerror or "cannot read /proc")
    reading.setdefault("ok", "error" not in reading)
    reading["read_at"] = time.time()
    return reading


if __name__ == "__main__":
    # `python3 src/machine.py` here, or `ssh <alias> python3 - 5` with this
    # file on stdin: either way, print this machine's reading as JSON.
    print(json.dumps(probe(int(sys.argv[1]) if len(sys.argv) > 1 else 5)))
