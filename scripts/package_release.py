"""Verify bundled notices and non-ASIO audio, then create the release ZIP."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from PyInstaller.archive.readers import CArchiveReader


def main():
    root = Path(__file__).resolve().parents[1]
    executable = root / "dist" / "Speaking_Recorder.exe"
    archive = CArchiveReader(str(executable))
    names = {name.replace("\\", "/"): name for name in archive.toc}
    if any("asio" in name.lower() for name in names):
        raise RuntimeError("ASIO DLL found in release executable")
    if not any("portaudio" in name.lower() and name.endswith(".dll") for name in names):
        raise RuntimeError("PortAudio DLL missing from release executable")
    if "native/ta_autotune.dll" not in names:
        raise RuntimeError("Hard Tune DLL missing from release executable")
    documents = [root / "LICENSE", root / "THIRD_PARTY_NOTICES.md"]
    documents.extend(sorted((root / "licenses").glob("*.txt")))
    for document in documents:
        name = document.relative_to(root).as_posix()
        if name not in names:
            raise RuntimeError(f"Missing bundled notice: {name}")
        if archive.extract(names[name]) != document.read_bytes():
            raise RuntimeError(f"Outdated bundled notice: {name}")
    destination = root / "dist" / "Speaking_Recorder-windows.zip"
    with ZipFile(destination, "w", ZIP_DEFLATED) as bundle:
        bundle.write(executable, executable.name)
        for document in documents:
            bundle.write(document, document.relative_to(root).as_posix())
    print(f"Verified notices and non-ASIO PortAudio. Release: {destination}")


if __name__ == "__main__":
    main()
