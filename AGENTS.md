# 작업 규칙

## 변경 후 항상 Windows 바탕화면 링크 갱신

코드·아이콘·에셋을 바꾼 작업은 끝내기 전에 **반드시** Windows 빌드를 다시 돌려
바탕화면 `Speaking Recorder.lnk`와 설치된 EXE를 최신 상태로 맞춘다.

```bash
# WSL에서 실행 (테스트 → EXE 빌드 → 배포 ZIP 검증 → 설치·바탕화면 링크 갱신)
WIN=$(wslpath -w "$PWD"); cd /mnt/c && cmd.exe /c "$WIN\\build.bat --no-pause"
```

- 성공하면 `Installed: ...\Programs\SpeakingRecorder\Speaking_Recorder.exe`와
  `Shortcut: ...\Desktop\Speaking Recorder.lnk`가 출력된다. 둘 다 확인한 뒤 작업을 마친다.
- 앱이 실행 중이면 EXE 복사가 실패한다. 앱을 닫고 다시 실행한다.
- 빌드나 테스트가 실패하면 링크가 갱신되지 않은 것이다. 실패를 그대로 보고한다.

## 구조

모듈 경계와 검증 기준은 `docs/architecture.md`를 따른다.
