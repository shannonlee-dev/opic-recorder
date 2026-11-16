# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets/speaking-recorder.ico', 'assets'), ('LICENSE', '.'),
         ('THIRD_PARTY_NOTICES.md', '.'), ('licenses', 'licenses')]
binaries = []
hiddenimports = ['_cffi_backend']
tmp_ret = collect_all('_sounddevice_data')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Hooks may discover ASIO as well; filter after Analysis to cover both paths.
a.binaries = [entry for entry in a.binaries if 'asio' not in entry[0].lower()]
a.datas = [entry for entry in a.datas if 'asio' not in entry[0].lower()]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Speaking_Recorder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\speaking-recorder.ico'],
)
