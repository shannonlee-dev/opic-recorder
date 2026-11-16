# Audio Library Implementation Plan

**Goal:** Double the recorder width and add a polished dark audio-card library.
**Architecture:** A dedicated library widget owns search, date filters, selection and paging. A worker reads WAV metadata into a queue; Tk consumes results on its existing polling loop. Playback uses the existing Windows adapter.
**Tech Stack:** Python, Tk/ttk, wave, Windows winsound. No additional runtime dependencies.
**Design:** Approved in chat: left recording controls, right navy library with cyan/violet accents, search, date filter, metadata, double-click playback and stop. Cards instead of filesystem rows.

- [x] Implement recursive WAV discovery with corrupt-file handling and metadata tests.
- [x] Implement dark cards, selection, search, date filter, paging and playback controls.
- [x] Integrate refresh after recording/folder change and disable playback while recording.
- [x] Verify Windows GUI, build EXE/ZIP, install and inspect actual window.

Review focus: empty folders; invalid WAVs; disappearing files; stale scans after folder changes; playback while recording; closing during a scan. Preserve existing recordings.

Verification: 29 Windows unittest cases passed, including card/player layout, date filtering, double-click playback, recording guard and timestamp ordering. Windows sample UI inspected; PyInstaller EXE and release ZIP built. Installed executable hash and Desktop shortcut launch verified. Microphone input in automated tests was simulated.

## Light theme revision
User requested a Notion/Obsidian-inspired light interface and supplied an Obsidian screenshot. Both panels now share warm neutral typography, flat controls and generous spacing: light gray recorder, white library, soft violet selection. The timer is centered and the primary button keeps a compact height while resizing. Windows tests: 29 passed; sample UI visually inspected.
