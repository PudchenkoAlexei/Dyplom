#!/usr/bin/env python3
from __future__ import annotations

from array import array
from pathlib import Path
import math
import sys
import wave


MIN_SPEECH_SECONDS = 0.45
RMS_THRESHOLD_DBFS = -42.0
SKIP_INITIAL_SECONDS = 0.35
WINDOW_SECONDS = 0.15


def rms_dbfs(samples: array) -> float:
    if not samples:
        return -120.0
    square_sum = sum(sample * sample for sample in samples)
    rms = math.sqrt(square_sum / len(samples))
    if rms <= 0:
        return -120.0
    return 20 * math.log10(rms / 32768.0)


def has_speech(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as recording:
            sample_rate = recording.getframerate()
            channels = recording.getnchannels()
            sample_width = recording.getsampwidth()
            frames = recording.readframes(recording.getnframes())
    except (wave.Error, OSError):
        return False

    if sample_rate <= 0 or sample_width != 2 or not frames:
        return False

    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder == "big":
        samples.byteswap()
    if channels > 1:
        samples = array("h", samples[::channels])

    skip = int(SKIP_INITIAL_SECONDS * sample_rate)
    window_size = max(int(WINDOW_SECONDS * sample_rate), 1)
    required_windows = max(math.ceil(MIN_SPEECH_SECONDS / WINDOW_SECONDS), 1)

    loud_windows = 0
    index = skip
    while index < len(samples):
        window = samples[index : index + window_size]
        if rms_dbfs(window) >= RMS_THRESHOLD_DBFS:
            loud_windows += 1
            if loud_windows >= required_windows:
                return True
        else:
            loud_windows = 0
        index += window_size

    return False


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: kpi_audio_has_speech.py QUESTION_WAV", file=sys.stderr)
        return 2
    return 0 if has_speech(Path(sys.argv[1])) else 1


if __name__ == "__main__":
    raise SystemExit(main())
