"""Desktop entry point; legacy imports remain available for existing callers."""

from opic_recorder import Recorder as Recorder
from opic_recorder import RecordingResult as RecordingResult
from opic_recorder.app import main
from opic_recorder.devices import microphone_choices as microphone_choices
from opic_recorder.metadata import APP_NAME as APP_NAME
from opic_recorder.settings import load_settings as load_settings
from opic_recorder.settings import save_settings as save_settings
from opic_recorder.ui.app import RecorderApp as RecorderApp
from opic_recorder.wav import (
    MAX_PCM_BYTES as MAX_PCM_BYTES,
)
from opic_recorder.wav import (
    WaveSink as WaveSink,
)
from opic_recorder.wav import (
    reserve_recording as reserve_recording,
)
from opic_recorder.windows import (
    desktop_folder as desktop_folder,
)
from opic_recorder.windows import (
    enable_dpi_awareness as enable_dpi_awareness,
)
from opic_recorder.windows import (
    microphone_access_issue as microphone_access_issue,
)
from opic_recorder.windows import (
    settings_file as settings_file,
)
from opic_recorder.windows import (
    windows_folder as windows_folder,
)

if __name__ == "__main__":
    raise SystemExit(main())
