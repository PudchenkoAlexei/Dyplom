#!/usr/bin/env python3
from __future__ import annotations

from array import array
from collections import deque
import math
import os
from pathlib import Path
import select
import sys
import time
import wave


SAMPLE_RATE = 8000
CHANNELS = 1
SAMPLE_WIDTH = 2
CHUNK_SECONDS = 0.1
CHUNK_BYTES = int(SAMPLE_RATE * SAMPLE_WIDTH * CHUNK_SECONDS)
MIN_SPEECH_SECONDS = 0.45
PREROLL_SECONDS = 0.5
RMS_THRESHOLD_DBFS = -42.0


def log(message: str) -> None:
    print(f"[kpi-record-question] {message}", file=sys.stderr, flush=True)


def read_agi_environment() -> None:
    while True:
        line = sys.stdin.readline()
        if not line or line in {"\n", "\r\n"}:
            return


def agi_command(command: str) -> str:
    sys.stdout.write(f"{command}\n")
    sys.stdout.flush()
    return sys.stdin.readline().strip()


def set_status(status: str) -> None:
    agi_command(f'SET VARIABLE KPI_RECORD_STATUS "{status}"')


def rms_dbfs(chunk: bytes) -> float:
    samples = array("h")
    samples.frombytes(chunk[: len(chunk) - (len(chunk) % SAMPLE_WIDTH)])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return -120.0
    square_sum = sum(sample * sample for sample in samples)
    rms = math.sqrt(square_sum / len(samples))
    if rms <= 0:
        return -120.0
    return 20 * math.log10(rms / 32768.0)


def seconds_for(chunk: bytes) -> float:
    return len(chunk) / (SAMPLE_RATE * SAMPLE_WIDTH)


def record_question(
    output_path: Path,
    start_timeout_seconds: float,
    end_silence_seconds: float,
    max_question_seconds: float,
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.unlink(missing_ok=True)

    started = False
    silence_seconds = 0.0
    speech_seconds = 0.0
    recorded_seconds = 0.0
    start_deadline = time.monotonic() + start_timeout_seconds
    preroll: deque[bytes] = deque(maxlen=max(1, int(PREROLL_SECONDS / CHUNK_SECONDS)))

    try:
        with wave.open(str(temp_path), "wb") as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(SAMPLE_RATE)

            while True:
                now = time.monotonic()
                if not started and now >= start_deadline:
                    log(f"no speech before {start_timeout_seconds:.1f}s timeout")
                    return "NOINPUT"
                if started and recorded_seconds >= max_question_seconds:
                    log(f"maximum question duration reached: {recorded_seconds:.1f}s")
                    break

                readable, _, _ = select.select([3], [], [], 0.25)
                if not readable:
                    continue

                chunk = os.read(3, CHUNK_BYTES)
                if not chunk:
                    log("audio stream ended")
                    break

                loud = rms_dbfs(chunk) >= RMS_THRESHOLD_DBFS
                duration = seconds_for(chunk)

                if not started:
                    preroll.append(chunk)
                    if not loud:
                        continue
                    started = True
                    for previous_chunk in preroll:
                        wav.writeframes(previous_chunk)
                        recorded_seconds += seconds_for(previous_chunk)
                    preroll.clear()

                wav.writeframes(chunk)
                recorded_seconds += duration

                if loud:
                    speech_seconds += duration
                    silence_seconds = 0.0
                else:
                    silence_seconds += duration

                if speech_seconds >= MIN_SPEECH_SECONDS and silence_seconds >= end_silence_seconds:
                    log(f"end silence reached after {recorded_seconds:.1f}s")
                    break

        if speech_seconds < MIN_SPEECH_SECONDS:
            temp_path.unlink(missing_ok=True)
            log(f"recording too short: speech={speech_seconds:.2f}s")
            return "NOINPUT"

        temp_path.replace(output_path)
        log(f"saved {output_path}: speech={speech_seconds:.1f}s total={recorded_seconds:.1f}s")
        return "SPEECH"
    except Exception as exc:  # noqa: BLE001
        temp_path.unlink(missing_ok=True)
        log(f"recording failed: {exc}")
        return "ERROR"


def main() -> int:
    read_agi_environment()
    if len(sys.argv) != 5:
        log("usage: kpi_record_question.py OUTPUT_WAV START_TIMEOUT END_SILENCE MAX_QUESTION")
        set_status("ERROR")
        return 1

    status = record_question(
        output_path=Path(sys.argv[1]),
        start_timeout_seconds=float(sys.argv[2]),
        end_silence_seconds=float(sys.argv[3]),
        max_question_seconds=float(sys.argv[4]),
    )
    set_status(status)
    return 0 if status == "SPEECH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
