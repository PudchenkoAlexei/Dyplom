#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

DEFAULT_BACKEND_URL = "http://host.docker.internal:8000/api/v1/phone-assistant/ask"
DEFAULT_BACKEND_TEXT_URL = "http://host.docker.internal:8000/api/v1/phone-assistant/ask-text"
DEFAULT_BACKEND_SPEECH_URL = "http://host.docker.internal:8000/api/v1/phone-assistant/speech"
DEFAULT_PBX_TOKEN = "change-this-pbx-token-for-development"
FAST_START_MIN_CHARS = 120
FAST_START_MAX_CHARS = 360
SPLIT_ABBREVIATIONS = (" ім.", " м.", " пр.", " вул.", " кім.", " р.", " ст.")


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


def post_question_text(
    backend_url: str,
    token: str,
    caller_number: str,
    call_id: str,
    question_audio_path: Path,
) -> dict:
    return post_question(
        backend_url=backend_url,
        token=token,
        caller_number=caller_number,
        call_id=call_id,
        question_audio_path=question_audio_path,
    )


def post_speech(backend_url: str, token: str, text: str) -> tuple[bytes, str]:
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    request = Request(
        backend_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "X-PBX-Token": token,
        },
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        mime_type = response.headers.get("Content-Type") or "audio/mpeg"
        return response.read(), mime_type.split(";", 1)[0]


def split_answer_for_fast_start(answer: str) -> tuple[str, str]:
    answer = " ".join(answer.split()).strip()
    if len(answer) <= FAST_START_MAX_CHARS:
        return answer, ""

    boundaries = []
    for match in re.finditer(r"[:.!?]\s+", answer):
        prefix = answer[: match.start() + 1].casefold()
        if any(prefix.endswith(abbreviation) for abbreviation in SPLIT_ABBREVIATIONS):
            continue
        boundaries.append(match.end())
    for boundary in boundaries:
        if FAST_START_MIN_CHARS <= boundary <= FAST_START_MAX_CHARS:
            return answer[:boundary].strip(), answer[boundary:].strip()

    for boundary in boundaries:
        if boundary > FAST_START_MAX_CHARS:
            break
        if boundary >= 70:
            return answer[:boundary].strip(), answer[boundary:].strip()

    fallback = answer.rfind(" ", 0, FAST_START_MAX_CHARS)
    if fallback < FAST_START_MIN_CHARS:
        fallback = FAST_START_MAX_CHARS
    return answer[:fallback].strip(), answer[fallback:].strip()


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


def write_audio_to_asterisk_wav(audio: bytes, mime_type: str, output_path: Path) -> None:
    suffix = mimetypes.guess_extension(mime_type) or ".mp3"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        temp_file.write(audio)
        temp_path = Path(temp_file.name)

    try:
        convert_to_asterisk_wav(temp_path, output_path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_status(output_path: Path, payload: dict) -> None:
    status_path = output_path.with_suffix(".json")
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rest_output_path_for(answer_output_path: Path) -> Path:
    return answer_output_path.with_name(f"{answer_output_path.stem}-rest{answer_output_path.suffix}")


def skip_marker_for(rest_output_path: Path) -> Path:
    return rest_output_path.with_suffix(rest_output_path.suffix + ".skip")


def synthesize_rest_from_request(request_path: Path) -> int:
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    rest_output_path = Path(request_payload["rest_output_path"])
    skip_marker_for(rest_output_path).unlink(missing_ok=True)
    try:
        audio, mime_type = post_speech(
            backend_url=str(request_payload["speech_url"]),
            token=str(request_payload["token"]),
            text=str(request_payload["text"]),
        )
        write_audio_to_asterisk_wav(audio, mime_type, rest_output_path)
        log(f"prepared rest audio: {rest_output_path}")
        return 0
    except Exception as exc:  # noqa: BLE001
        log(f"failed to prepare rest audio {rest_output_path}: {exc}")
        skip_marker_for(rest_output_path).write_text("failed\n", encoding="utf-8")
        return 1


def start_rest_synthesis(
    *,
    rest_text: str,
    rest_output_path: Path,
    speech_url: str,
    token: str,
) -> None:
    request_path = rest_output_path.with_suffix(".request.json")
    request_path.write_text(
        json.dumps(
            {
                "text": rest_text,
                "rest_output_path": str(rest_output_path),
                "speech_url": speech_url,
                "token": token,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    skip_marker_for(rest_output_path).unlink(missing_ok=True)
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--synthesize-rest", str(request_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def process_progressive_call(
    *,
    backend_text_url: str,
    backend_speech_url: str,
    token: str,
    caller_number: str,
    call_id: str,
    question_audio_path: Path,
    answer_output_path: Path,
) -> int:
    payload = post_question_text(
        backend_url=backend_text_url,
        token=token,
        caller_number=caller_number,
        call_id=call_id,
        question_audio_path=question_audio_path,
    )
    answer_text = str(payload["answer_text"])
    first_text, rest_text = split_answer_for_fast_start(answer_text)
    first_audio, first_mime_type = post_speech(
        backend_url=backend_speech_url,
        token=token,
        text=first_text,
    )
    write_audio_to_asterisk_wav(first_audio, first_mime_type, answer_output_path)

    rest_output_path = rest_output_path_for(answer_output_path)
    rest_output_path.unlink(missing_ok=True)
    skip_marker = skip_marker_for(rest_output_path)
    if rest_text:
        start_rest_synthesis(
            rest_text=rest_text,
            rest_output_path=rest_output_path,
            speech_url=backend_speech_url,
            token=token,
        )
    else:
        skip_marker.write_text("no rest\n", encoding="utf-8")

    payload["progressive_audio"] = {
        "first_text": first_text,
        "rest_text": rest_text,
        "first_audio_path": str(answer_output_path),
        "rest_audio_path": str(rest_output_path) if rest_text else None,
    }
    write_status(answer_output_path, payload)
    log(
        "answered first chunk "
        f"{call_id}: {payload.get('source')} "
        f"{payload.get('confidence')} -> {answer_output_path}"
    )
    return 0


def process_full_call(
    *,
    backend_url: str,
    token: str,
    caller_number: str,
    call_id: str,
    question_audio_path: Path,
    answer_output_path: Path,
) -> int:
    payload = post_question(
        backend_url=backend_url,
        token=token,
        caller_number=caller_number,
        call_id=call_id,
        question_audio_path=question_audio_path,
    )
    audio_bytes = base64.b64decode(payload["answer_audio_base64"])
    mime_type = str(payload.get("answer_audio_mime_type") or "audio/mpeg")
    write_audio_to_asterisk_wav(audio_bytes, mime_type, answer_output_path)
    write_status(answer_output_path, payload)
    log(
        "answered call "
        f"{call_id}: {payload.get('source')} "
        f"{payload.get('confidence')} -> {answer_output_path}"
    )
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--synthesize-rest":
        return synthesize_rest_from_request(Path(sys.argv[2]))

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
    backend_text_url = os.getenv("KPI_BACKEND_PHONE_ASSISTANT_TEXT_URL", DEFAULT_BACKEND_TEXT_URL)
    backend_speech_url = os.getenv("KPI_BACKEND_PHONE_ASSISTANT_SPEECH_URL", DEFAULT_BACKEND_SPEECH_URL)
    token = os.getenv("KPI_PBX_INTERNAL_TOKEN", DEFAULT_PBX_TOKEN)
    progressive_tts = os.getenv("KPI_PHONE_PROGRESSIVE_TTS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    try:
        if progressive_tts:
            return process_progressive_call(
                backend_text_url=backend_text_url,
                backend_speech_url=backend_speech_url,
                token=token,
                caller_number=caller_number,
                call_id=call_id,
                question_audio_path=question_audio_path,
                answer_output_path=answer_output_path,
            )
        return process_full_call(
            backend_url=backend_url,
            token=token,
            caller_number=caller_number,
            call_id=call_id,
            question_audio_path=question_audio_path,
            answer_output_path=answer_output_path,
        )
    except (HTTPError, URLError, TimeoutError, subprocess.CalledProcessError, KeyError) as exc:
        log(f"failed to process call {call_id}: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        log(f"unexpected failure for call {call_id}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
