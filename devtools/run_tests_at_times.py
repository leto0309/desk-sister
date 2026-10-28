"""Run the whole test suite at the hours and days that change what she says, and with many random draws.

A release once failed on a test that passed only on a lucky draw (a greeting picked at random that happened to
"think"). This runs pytest with DESK_SISTER_FAKE_NOW (the wall clock) or DESK_SISTER_SEED (every random choice) set,
see tests/conftest.py, a few runs at a time, and lists the failures of each.

    .venv/Scripts/python.exe devtools/run_tests_at_times.py [--jobs 4] [--only 2027-02-06T09:00 ...]
    .venv/Scripts/python.exe devtools/run_tests_at_times.py --seeds 20
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "build" / "test-runs"  # the full output of each run that failed

MOMENTS = [
    "2026-11-03T00:30",  # after midnight: still "tonight" for the bedtime reminder
    "2026-11-03T04:59",  # the last minute of the night
    "2026-11-03T05:30",  # early morning
    "2026-11-03T07:30",  # morning greetings
    "2026-11-03T11:59",
    "2026-11-03T12:30",  # lunch
    "2026-11-03T15:56",  # the afternoon a release once failed in
    "2026-11-03T18:30",  # evening
    "2026-11-03T21:30",  # after the default daily-summary hour
    "2026-11-03T22:59",
    "2026-11-03T23:30",  # late night: the bedtime reminder
    "2026-11-07T10:00",  # a Saturday
    "2026-12-25T10:00",  # a fixed festival
    "2026-12-31T23:58",  # the year (and the day) turns during the run
    "2027-01-01T08:00",  # New Year's Day
    "2027-02-06T09:00",  # Spring Festival (lunar new year)
    "2028-02-29T10:00",  # a leap day
]


def run(setting: tuple[str, str]) -> tuple[str, int, list[str], str]:
    name, value = setting
    # Read back as UTF-8: Chinese messages intact. Runs side by side must not write the real Credential Manager at
    # once: it then loses writes, the user's own credentials included (see tests/test_api_mode.py).
    env = dict(os.environ, **{name: value}, PYTHONIOENCODING="utf-8", DESK_SISTER_PARALLEL_RUN="1")
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests", "-o", "pythonpath=src", "-p", "no:cacheprovider"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    failed = re.findall(r"^(?:FAILED|ERROR) (\S+)", done.stdout, re.M)
    summary = (done.stdout.strip().splitlines() or ["(no output)"])[-1]
    if done.returncode:
        log = LOGS / f"{name}-{re.sub(r'[^0-9A-Za-z]', '-', value)}.log"
        LOGS.mkdir(parents=True, exist_ok=True)
        log.write_text(f"exit code {done.returncode}\n{done.stdout}\n--- stderr ---\n{done.stderr}", encoding="utf-8")
        summary += f"  (exit {done.returncode}; log: {log.relative_to(ROOT)})"
    return value, done.returncode, failed, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--only", nargs="*", help="these moments instead of the whole list")
    parser.add_argument("--seeds", type=int, help="instead of moments: this many runs, each with its own random seed")
    parser.add_argument("--first-seed", type=int, default=1)
    args = parser.parse_args()
    if args.seeds is not None and args.seeds <= 0:
        parser.error("--seeds needs at least one run")
    if args.jobs <= 0:
        parser.error("--jobs needs at least one")
    if args.seeds is not None:
        settings = [("DESK_SISTER_SEED", str(n)) for n in range(args.first_seed, args.first_seed + args.seeds)]
    else:
        settings = [("DESK_SISTER_FAKE_NOW", moment) for moment in args.only or MOMENTS]
    bad = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for value, code, failed, summary in pool.map(run, settings):
            print(f"{value}  {summary}", flush=True)
            for name in failed:
                print(f"    {name}")
            bad += code != 0
    print(f"{len(settings) - bad}/{len(settings)} runs passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
