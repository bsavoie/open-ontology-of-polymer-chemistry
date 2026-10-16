"""Run the Python test suite in parallel, one process per test file.

    python tools/run_tests.py                  # every tier (the merge gate)
    python tools/run_tests.py --tier fast      # after an individual change
    python tools/run_tests.py --tier scenario  # the long end-to-end scenarios
    python tools/run_tests.py test_trace.py test_server_safety.py

Each file runs exactly as `python -m unittest discover -s tests -p FILE`, so
test modules keep importing shared fixtures by their top-level names. Scenario
files are listed in `tests/test-tiers.json`; they start first because they
dominate wall time. A file that outlasts `--timeout` fails instead of hanging.
Standard library only, so the gate runs offline and on Python 3.9.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
TIERS = TESTS / "test-tiers.json"
_SUMMARY = re.compile(r"^(OK|FAILED)\b(?: \((.*)\))?", re.M)


def load_tiers():
    """Test files by tier; every file not listed as a scenario is fast."""
    listed = json.loads(TIERS.read_text(encoding="utf-8"))["scenario"]
    files = sorted(path.name for path in TESTS.glob("test_*.py"))
    missing = sorted(set(listed) - set(files))
    if missing:
        raise SystemExit("tests/test-tiers.json names missing files: " + ", ".join(missing))
    return {"scenario": [name for name in files if name in listed],
            "fast": [name for name in files if name not in listed]}


def run_file(name, timeout):
    started = time.monotonic()
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", name]
    try:
        completed = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, text=True, timeout=timeout)
        output, code = completed.stdout, completed.returncode
    except subprocess.TimeoutExpired as error:
        output = (error.output or "") if isinstance(error.output, str) else (error.output or b"").decode("utf-8", "replace")
        output, code = output + f"\nTimed out after {timeout}s\n", -1
    ran = re.search(r"^Ran (\d+) tests?", output, re.M)
    summary = _SUMMARY.search(output)
    counts = dict(re.findall(r"(\w+)=(\d+)", summary.group(2) or "")) if summary else {}
    return {"file": name, "seconds": time.monotonic() - started, "code": code, "tests": int(ran.group(1)) if ran else 0,
            "skipped": int(counts.get("skipped", 0)), "output": output}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", help="Specific test files (default: the selected tier)")
    parser.add_argument("--tier", choices=["all", "fast", "scenario"], default="all")
    parser.add_argument("--workers", type=int, default=max(1, min(12, (os.cpu_count() or 2) // 2)))
    parser.add_argument("--timeout", type=float, default=1800, help="Seconds per test file")
    args = parser.parse_args(argv)
    tiers = load_tiers()
    if args.files:
        names = [Path(name).name for name in args.files]
        unknown = [name for name in names if not (TESTS / name).is_file()]
        if unknown:
            raise SystemExit("Unknown test files: " + ", ".join(unknown))
    else:
        names = tiers["scenario"] + tiers["fast"] if args.tier == "all" else tiers[args.tier]
    # Longest first: scenario files dominate wall time.
    names.sort(key=lambda name: name not in tiers["scenario"])
    started, results = time.monotonic(), []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_file, name, args.timeout) for name in names]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            mark = "ok  " if result["code"] == 0 else "FAIL"
            print(f"{mark} {result['seconds']:7.1f}s {result['tests']:4d} {result['file']}", flush=True)
    failed = sorted((r for r in results if r["code"] != 0), key=lambda r: r["file"])
    for result in failed:
        print("\n" + "=" * 70 + "\n" + result["file"] + "\n" + "=" * 70)
        print(result["output"][-6000:])
    total = sum(r["tests"] for r in results)
    skipped = sum(r["skipped"] for r in results)
    print(f"\nRan {total} tests in {len(results)} files in {time.monotonic() - started:.0f}s "
          f"with {args.workers} workers: {'FAILED (' + str(len(failed)) + ' files)' if failed else 'OK'}"
          + (f" (skipped={skipped})" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
