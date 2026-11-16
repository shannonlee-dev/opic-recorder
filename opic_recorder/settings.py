"""Read and atomically persist the selected recording directory."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def load_settings(path: Path) -> tuple[Path | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data["save_folder"]
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            raise ValueError("저장 위치가 올바른 절대 경로가 아닙니다.")
        return Path(value), None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return None, f"설정을 읽을 수 없어 기본 저장 위치를 사용합니다.\n{exc}"


def save_settings(path: Path, folder: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix="settings-",
            suffix=".tmp",
            delete=False,
        ) as file:
            temp_path = Path(file.name)
            json.dump({"save_folder": str(folder)}, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
