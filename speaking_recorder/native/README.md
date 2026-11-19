# Native components

`ta_autotune.dll` — hard-tune pitch correction (YIN + chromatic snap + TD-PSOLA), built from
the sibling project `~/__dev/trap-autotune` (`src/api/ta_autotune.h`, C ABI version 1).
Static CRT, baseline x64; no runtime dependencies.

License: MIT (same author as this project; see `LICENSE` in trap-autotune). The statically
linked Microsoft C/C++ runtime is redistributable under the Visual Studio license terms.

Refresh after changing the DSP:

```bash
(cd ~/__dev/trap-autotune && scripts/build-windows.sh) && cp ~/__dev/trap-autotune/dist/ta_autotune.dll speaking_recorder/native/
```
