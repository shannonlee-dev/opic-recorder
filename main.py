"""Desktop entry point; legacy imports remain available for existing callers."""

from speaking_recorder import Recorder as Recorder
from speaking_recorder import RecordingResult as RecordingResult
from speaking_recorder.app import main
from speaking_recorder.devices import microphone_choices as microphone_choices
from speaking_recorder.metadata import APP_NAME as APP_NAME
from speaking_recorder.settings import load_settings as load_settings
from speaking_recorder.settings import save_settings as save_settings
from speaking_recorder.ui.app import RecorderApp as RecorderApp
from speaking_recorder.wav import (
    MAX_PCM_BYTES as MAX_PCM_BYTES,
)
from speaking_recorder.wav import (
    WaveSink as WaveSink,
)
from speaking_recorder.wav import (
    reserve_recording as reserve_recording,
)
from speaking_recorder.windows import (
    desktop_folder as desktop_folder,
)
from speaking_recorder.windows import (
    enable_dpi_awareness as enable_dpi_awareness,
)
from speaking_recorder.windows import (
    microphone_access_issue as microphone_access_issue,
)
from speaking_recorder.windows import (
    settings_file as settings_file,
)
from speaking_recorder.windows import (
    windows_folder as windows_folder,
)

if __name__ == "__main__":
    raise SystemExit(main())
