# MacroNode Editor

화면 인식 기반 시각적 매크로 자동화 도구입니다. 코딩 없이 노드(Node)를 연결하여 누구나 쉽게 자동화 매크로를 작성할 수 있습니다.

## 시작하기

다음 명령어로 매크로 노드 에디터를 실행할 수 있습니다:

```bash
python ui/node_editor_main.py
```

## Windows exe 배포

다음 명령어로 Windows에서 더블클릭 실행 가능한 배포 폴더를 만들 수 있습니다:

```bash
python -m PyInstaller --clean --noconfirm SheerHeartAttack.spec
```

빌드가 끝나면 `dist/SheerHeartAttack/SheerHeartAttack.exe`를 실행하면 됩니다.
`build` 폴더는 PyInstaller 중간 작업 폴더이므로 그 안의 exe는 실행하지 마세요.
GitHub Release에는 `dist/SheerHeartAttack` 폴더를 zip으로 압축해서 올리면 됩니다.

자세한 사용법 가이드는 [USAGE.md](USAGE.md) 파일을 참고하세요.