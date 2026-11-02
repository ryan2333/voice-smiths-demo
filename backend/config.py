from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    upload_dir: Path
    audio_dir: Path
    workers: int = 2
    connect_timeout: int = 10
    receive_timeout: int = 60
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.environ.get("VOICE_SMITHS_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
        return cls(
            data_dir=data_dir,
            upload_dir=Path(os.environ.get("VOICE_SMITHS_UPLOAD_DIR", str(data_dir / "uploads"))).expanduser().resolve(),
            audio_dir=Path(os.environ.get("VOICE_SMITHS_AUDIO_DIR", str(data_dir / "audio"))).expanduser().resolve(),
            workers=max(1, min(8, int(os.environ.get("VOICE_SMITHS_WORKERS", "2")))),
            connect_timeout=max(1, int(os.environ.get("VOICE_SMITHS_CONNECT_TIMEOUT", "10"))),
            receive_timeout=max(1, int(os.environ.get("VOICE_SMITHS_RECEIVE_TIMEOUT", "60"))),
            cors_origins=tuple(origin.strip() for origin in os.environ.get(
                "VOICE_SMITHS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",") if origin.strip()),
        )
