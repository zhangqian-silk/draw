from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


CONFIG_ENV_VAR = "DRAWBOT_CONFIG_PATH"


@dataclass(frozen=True)
class AppConfig:
    api_key: str = ""
    base_url: str = ""
    model: str = ""

    @classmethod
    def from_payload(cls, payload: dict) -> "AppConfig":
        return cls(
            api_key=str(payload.get("api_key", "") or "").strip(),
            base_url=str(payload.get("base_url", "") or "").strip(),
            model=str(payload.get("model", "") or "").strip(),
        )

    def as_payload(self) -> dict:
        return asdict(self)


def default_config_path() -> Path:
    override = os.getenv(CONFIG_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "drawbot" / "config.json"

    return Path.home() / ".drawbot" / "config.json"


class ConfigStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = default_config_path() if path is None else Path(path)

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppConfig()

        if not isinstance(payload, dict):
            return AppConfig()
        return AppConfig.from_payload(payload)

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(config.as_payload(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
