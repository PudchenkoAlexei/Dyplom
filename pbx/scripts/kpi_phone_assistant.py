#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

DEFAULT_BACKEND_URL = "http://host.docker.internal:8000/api/v1/phone-assistant/ask"
DEFAULT_PBX_TOKEN = "change-this-pbx-token-for-development"


def log(message: str) -> None:
    print(f"[kpi-phone-assistant] {message}", file=sys.stderr, flush=True)


def multipart_form(
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
    content_type: str,
) -> tuple[bytes, str]:
    boundary = f"----kpi-phone-assistant-{uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), boundary


def post_question(
    backend_url: str,
    token: str,
    caller_number: str,
    call_id: str,
    question_audio_path: Path,
) -> dict:
    content_type = mimetypes.guess_type(question_audio_path.name)[0] or "audio/wav"
    body, boundary = multipart_form(
        {
            "caller_number": caller_number,
            "call_id": call_id,
        },
        "audio",
        question_audio_path,
        content_type,
    )
    request = Request(
        backend_url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "X-PBX-Token": token,
        },
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def convert_to_asterisk_wav(source_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to prepare audio for Asterisk playback.")

    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-filter:a",
            "loudnorm=I=-18:TP=-3:LRA=8",
            "-ar",
            "8000",
            "-ac",
            "1",
            "-sample_fmt",
            "s16",
            str(output_path),
        ],
        check=True,
    )


def write_status(output_path: Path, payload: dict) -> None:
    status_path = output_path.with_suffix(".json")
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 5:
        log("usage: kpi_phone_assistant.py CALLER_NUMBER CALL_ID QUESTION_WAV ANSWER_WAV")
        return 2

    caller_number = sys.argv[1].strip() or "unknown"
    call_id = sys.argv[2].strip()
    question_audio_path = Path(sys.argv[3])
    answer_output_path = Path(sys.argv[4])

    if not question_audio_path.exists():
        log(f"question audio does not exist: {question_audio_path}")
        return 1

    backend_url = os.getenv("KPI_BACKEND_PHONE_ASSISTANT_URL", DEFAULT_BACKEND_URL)
    token = os.getenv("KPI_PBX_INTERNAL_TOKEN", DEFAULT_PBX_TOKEN)

    try:
        payload = post_question(
            backend_url=backend_url,
            token=token,
            caller_number=caller_number,
            call_id=call_id,
            question_audio_path=question_audio_path,
        )
        audio_bytes = base64.b64decode(payload["answer_audio_base64"])
        mime_type = str(payload.get("answer_audio_mime_type") or "audio/mpeg")
        suffix = mimetypes.guess_extension(mime_type) or ".mp3"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = Path(temp_file.name)

        try:
            convert_to_asterisk_wav(temp_path, answer_output_path)
        finally:
            temp_path.unlink(missing_ok=True)

        write_status(answer_output_path, payload)
        log(
            "answered call "
            f"{call_id}: {payload.get('source')} "
            f"{payload.get('confidence')} -> {answer_output_path}"
        )
        return 0
    except (HTTPError, URLError, TimeoutError, subprocess.CalledProcessError, KeyError) as exc:
        log(f"failed to process call {call_id}: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        log(f"unexpected failure for call {call_id}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
