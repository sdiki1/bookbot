from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ENV_FILE = ".env"


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int
    db_path: Path
    upload_dir: Path
    web_admin_user: str
    web_admin_password: str
    web_host: str
    web_port: int


def _load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def load_config() -> Config:
    _load_dotenv(Path(DEFAULT_ENV_FILE))

    token = os.getenv("BOT_TOKEN", "").strip()
    admin_id_raw = os.getenv("BOT_ADMIN_ID", "").strip()
    db_path_raw = os.getenv("BOOKBOT_DB_PATH", "data/books.db").strip()
    upload_dir_raw = os.getenv("BOOKBOT_UPLOAD_DIR", "data/uploads").strip()
    web_admin_user = os.getenv("WEB_ADMIN_USER", "admin").strip()
    web_admin_password = os.getenv("WEB_ADMIN_PASSWORD", "").strip()
    web_host = os.getenv("WEB_HOST", "0.0.0.0").strip()
    web_port_raw = os.getenv("WEB_PORT", "8080").strip()

    if not token:
        raise RuntimeError("Missing BOT_TOKEN in environment or .env file")
    if not admin_id_raw:
        raise RuntimeError("Missing BOT_ADMIN_ID in environment or .env file")
    if not admin_id_raw.isdigit():
        raise RuntimeError("BOT_ADMIN_ID must be an integer Telegram user id")
    if not web_admin_password:
        raise RuntimeError("Missing WEB_ADMIN_PASSWORD in environment or .env file")
    if not web_port_raw.isdigit():
        raise RuntimeError("WEB_PORT must be an integer")
    web_port = int(web_port_raw)
    if web_port < 1 or web_port > 65535:
        raise RuntimeError("WEB_PORT must be in range 1..65535")

    return Config(
        bot_token=token,
        admin_id=int(admin_id_raw),
        db_path=Path(db_path_raw),
        upload_dir=Path(upload_dir_raw),
        web_admin_user=web_admin_user,
        web_admin_password=web_admin_password,
        web_host=web_host,
        web_port=web_port,
    )
