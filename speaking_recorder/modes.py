"""Recording modes that share one recorder but keep separate storage."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    key: str
    label: str
    folder_name: str
    settings_name: str


ENGLISH = Mode("english", "English", "Speaking_Recordings", "settings.json")
SONG = Mode("song", "Song", "Song_Recordings", "song-settings.json")
MODES = (ENGLISH, SONG)
