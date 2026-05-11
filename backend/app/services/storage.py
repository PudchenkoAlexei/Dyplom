from pathlib import Path
import shutil
from uuid import UUID, uuid4

import aiofiles
from fastapi import HTTPException, UploadFile, status

from app.core.config import PROJECT_ROOT, get_settings

settings = get_settings()

ALLOWED_AUDIO_TYPES = {
    "audio/webm": ".webm",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
}


class StoredAudio:
    def __init__(self, file_path: Path, mime_type: str, size_bytes: int) -> None:
        self.file_path = file_path
        self.mime_type = mime_type
        self.size_bytes = size_bytes


async def save_ticket_audio(ticket_id: UUID, upload: UploadFile) -> StoredAudio:
    mime_type = upload.content_type or "application/octet-stream"
    if mime_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported audio type: {mime_type}.",
        )

    directory = settings.audio_storage_dir / str(ticket_id)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = ALLOWED_AUDIO_TYPES[mime_type]
    file_path = directory / f"{uuid4()}{suffix}"

    size = 0
    async with aiofiles.open(file_path, "wb") as out_file:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_audio_bytes:
                try:
                    file_path.unlink(missing_ok=True)
                finally:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Audio file is larger than {settings.max_audio_mb} MB.",
                    ) from None
            await out_file.write(chunk)

    return StoredAudio(file_path=file_path, mime_type=mime_type, size_bytes=size)


def resolve_audio_path(file_path: str) -> Path:
    stored_path = Path(file_path)
    if stored_path.is_absolute():
        path = stored_path.resolve()
    else:
        path = (PROJECT_ROOT / stored_path).resolve()
        if not path.exists():
            path = (settings.audio_storage_dir / stored_path).resolve()
    storage_root = settings.audio_storage_dir.resolve()
    if storage_root not in path.parents:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid audio path.")
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found.")
    return path


def delete_audio_file(file_path: str) -> None:
    stored_path = Path(file_path)
    if stored_path.is_absolute():
        path = stored_path.resolve()
    else:
        path = (PROJECT_ROOT / stored_path).resolve()
        if not path.exists():
            path = (settings.audio_storage_dir / stored_path).resolve()

    storage_root = settings.audio_storage_dir.resolve()
    if storage_root not in path.parents:
        return

    path.unlink(missing_ok=True)
    parent = path.parent.resolve()
    if storage_root in parent.parents and parent.exists() and not any(parent.iterdir()):
        shutil.rmtree(parent)
