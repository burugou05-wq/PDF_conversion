# v2.1.0 検証結果

## 対象

- 正式版: WinUI 3版（単一EXE `ImageToPDF-v2.1.0-Windows-x64.exe`）
- 変換エンジン: `image_processor.py`（v2.0.1のICC対応を含む）。WinUI版は `conversion_worker.py` 経由で同じエンジンを使います。

## 自動テスト（Linux / Python 3.11）

- `python -m pytest -q`: **76 passed, 3 skipped**（Tk GUIのテストはディスプレイがないためskip）
- `python -m ruff check .`: **All checks passed**

## Windows CI（`build_winui.ps1`）で確認する内容

- Python テスト・ruff
- PyInstallerによるワーカー（`ImageToPDFWorker.exe`）の作成と、x64 PEの確認
- WinUI版の `PublishSingleFile` 発行。発行先にEXE以外のファイルがないことを確認
- EXEをUnicodeパスの一時フォルダーに単独でコピーし、埋め込みワーカーで日本語ファイル名の画像をPDFに変換（`--selftest-convert`）
- 同じEXEからウィンドウを表示し、タイトル「画像PDF変換ツール」を確認
- `SHA256SUMS.txt` とEXEのSHA-256の一致

## まだ実施していない確認

- Python未導入の別Windows端末での起動
- 実際のエクスプローラーからのドラッグ＆ドロップ操作
- キャンセル、AVIF/HEICのサムネイル表示、プレビューの操作
- 複数モニター・複数DPI環境での画面確認
- 大量・巨大画像による性能と長時間負荷の測定
- 初回起動時の埋め込みワーカーの展開と、2回目以降の起動時間
- 別バージョンを上書きした場合の `%LOCALAPPDATA%\ImageToPDF\worker` の挙動

これらはCIの起動確認や単体テストでは代替できません。正式Releaseの前に手動で確認してください。
