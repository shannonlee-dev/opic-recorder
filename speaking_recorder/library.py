"""Read recording metadata without importing the desktop interface."""
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import wave


@dataclass(frozen=True)
class Recording:
    path: Path
    date: str
    seconds: float
    size: int
    modified: float = 0


def scan_recordings(folder: Path) -> list[Recording]:
    records = []
    if not folder.exists():
        return records
    for path in folder.rglob('*'):
        if path.suffix.lower() != '.wav' or not path.is_file():
            continue
        # Hidden folders (e.g. .raw originals kept under autotuned takes) are not takes.
        if any(part.startswith('.') for part in path.relative_to(folder).parts[:-1]):
            continue
        try:
            stat = path.stat()
            with wave.open(str(path), 'rb') as audio:
                seconds = audio.getnframes() / audio.getframerate()
            date = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d')
            records.append(Recording(path, date, seconds, stat.st_size, stat.st_mtime))
        except (OSError, EOFError, wave.Error, ZeroDivisionError):
            continue
    return sorted(records, key=lambda item: (item.modified, item.path.name), reverse=True)
