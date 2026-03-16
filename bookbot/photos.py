from __future__ import annotations

from pathlib import Path


LOCAL_PREFIX = "local:"


def is_local_photo_ref(photo_ref: str) -> bool:
    return photo_ref.startswith(LOCAL_PREFIX)


def build_local_photo_ref(filename: str) -> str:
    safe_name = Path(filename).name
    return f"{LOCAL_PREFIX}{safe_name}"


def extract_local_filename(photo_ref: str) -> str:
    filename = photo_ref[len(LOCAL_PREFIX) :]
    return Path(filename).name


def resolve_local_photo_path(photo_ref: str, upload_dir: Path) -> Path:
    return upload_dir / extract_local_filename(photo_ref)
