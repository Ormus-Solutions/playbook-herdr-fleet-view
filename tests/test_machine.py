"""The machine probe and the memory-sum lesson."""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SRC

import machine

MIB = 1024**2


def procs(name: str, n: int, anon: float, file: float, shmem: float) -> list[dict]:
    return [{"name": name, "anon": int(anon * MIB), "file": int(file * MIB),
             "shmem": int(shmem * MIB)} for _ in range(n)]


class MemorySumTest(unittest.TestCase):
    """A plain RSS sum counts a shared page once per process."""

    def test_forty_copies_of_one_program(self) -> None:
        # 28 MiB own, 45 MiB of program file and libraries, 2 MiB shared each.
        [row] = machine.program_rows(procs("node", 40, 28, 45, 2))
        self.assertEqual(row["count"], 40)
        self.assertEqual(row["ram"], (40 * 28 + 2) * MIB)       # 1122 MiB
        self.assertEqual(row["rss_sum"], 40 * (28 + 45 + 2) * MIB)  # 3000 MiB

    def test_shared_buffers_count_once(self) -> None:
        # Twelve database workers that all map the same 512 MiB of shared buffers.
        [row] = machine.program_rows(procs("postgres", 12, 10, 8, 512))
        self.assertEqual(row["ram"], (12 * 10 + 512) * MIB)          # 632 MiB
        self.assertEqual(row["rss_sum"], 12 * (10 + 8 + 512) * MIB)  # 6360 MiB, ten times more

    def test_largest_first_and_top(self) -> None:
        rows = machine.program_rows(procs("a", 1, 5, 0, 0) + procs("b", 1, 50, 0, 0)
                                    + procs("c", 1, 20, 0, 0), top=2)
        self.assertEqual([r["name"] for r in rows], ["b", "c"])


class ParseTest(unittest.TestCase):
    def test_meminfo_in_bytes(self) -> None:
        mem = machine.meminfo("MemTotal:       2048 kB\nMemAvailable:   1024 kB\nHugePages_Total: 0\n")
        self.assertEqual(mem["MemTotal"], 2048 * 1024)
        self.assertEqual(mem["MemAvailable"], 1024 * 1024)

    def test_process_row(self) -> None:
        row = machine.process_row("Name:\tnode\nRssAnon:\t  100 kB\nRssFile:\t 50 kB\nRssShmem:\t 4 kB\n")
        self.assertEqual(row, {"name": "node", "anon": 102400, "file": 51200, "shmem": 4096})

    def test_kernel_thread_has_no_rss(self) -> None:
        self.assertIsNone(machine.process_row("Name:\tkthreadd\nState:\tS (sleeping)\n"))

    def test_short_reason_takes_the_last_part(self) -> None:
        err = "ssh: connect to host demo-box port 22: Connection timed out\n"
        self.assertEqual(machine.short_reason(err), "Connection timed out")
        self.assertEqual(machine.short_reason(""), "no answer")


class ReadMachineTest(unittest.TestCase):
    def test_reading_from_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "box.json"
            path.write_text(json.dumps({"ok": True, "cores": 4}), encoding="utf-8")
            reading = machine.read_machine({"name": "box", "file": str(path)})
        self.assertTrue(reading["ok"])
        self.assertIn("read_at", reading)

    def test_a_missing_file_is_a_failed_reading(self) -> None:
        reading = machine.read_machine({"name": "box", "file": "/nonexistent/box.json"})
        self.assertFalse(reading["ok"])
        self.assertIn("No such file", reading["error"])

    def test_ssh_never_asks_for_a_password(self) -> None:
        argv = machine.ssh_argv("build-box", 3)
        self.assertEqual(argv[0], "ssh")
        self.assertIn("BatchMode=yes", argv)
        self.assertEqual(argv[-4:], ["build-box", "python3", "-", "3"])

    def test_missing_ssh_says_so(self) -> None:
        old = machine.ssh_argv
        machine.ssh_argv = lambda alias, top: ["/nonexistent/ssh"]
        try:
            reading = machine.read_ssh("build-box", 3)
        finally:
            machine.ssh_argv = old
        self.assertEqual(reading, {"ok": False, "error": "ssh is not installed"})


@unittest.skipUnless(platform.system() == "Linux", "the probe reads /proc on Linux")
class ProbeTest(unittest.TestCase):
    def test_probe_reads_this_machine(self) -> None:
        r = machine.probe(top=2)
        self.assertTrue(r["ok"])
        self.assertGreater(r["mem_total"], 0)
        self.assertLessEqual(len(r["programs"]), 2)

    def test_probe_runs_as_a_program_on_stdin(self) -> None:
        # The ssh path without ssh: `python3 - 2` with this file on stdin.
        source = (SRC / "machine.py").read_text(encoding="utf-8")
        done = subprocess.run([sys.executable, "-", "2"], input=source, capture_output=True,
                              text=True, check=True)
        r = json.loads(done.stdout)
        self.assertTrue(r["ok"])
        self.assertLessEqual(len(r["programs"]), 2)


if __name__ == "__main__":
    unittest.main()
