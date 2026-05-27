#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import time


def log(message: str) -> None:
    print(f"[kpi-wait-for-file] {message}", file=sys.stderr, flush=True)


def skip_marker_for(target_path: Path) -> Path:
    return target_path.with_suffix(target_path.suffix + ".skip")


def main() -> int:
    if len(sys.argv) != 3:
        log("usage: kpi_wait_for_file.py TARGET_PATH TIMEOUT_SECONDS")
        return 2

    target_path = Path(sys.argv[1])
    timeout_seconds = float(sys.argv[2])
    skip_marker = skip_marker_for(target_path)
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        if target_path.exists() and target_path.stat().st_size > 44:
            log(f"file is ready: {target_path}")
            return 0
        if skip_marker.exists():
            log(f"skip marker found: {skip_marker}")
            return 1
        time.sleep(0.2)

    log(f"timeout waiting for {target_path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
