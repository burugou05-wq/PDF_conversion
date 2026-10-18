# v2.1.0.1 検証結果

## 対象

- 正式版: WinUI 3版（単一EXE `ImageToPDF-v2.1.0.1-Windows-x64.exe`）
- 変換エンジン: `image_processor.py`（v2.0.1のICC対応に加え、MPO先頭フレーム埋め込み・G4 TIFF直接埋め込み・グレースケール保持・非デコード取り込みを含む）。WinUI版は常駐化した `conversion_worker.py` 経由で同じエンジンを使います。

## 自動テスト（Linux / Python 3.11）

- `python -m pytest -q`: **101 passed, 7 skipped**（Tk GUIのテストはディスプレイがないためskip、AVIF/HEIFはオプションのためskip）
- `python -m ruff check .`: **All checks passed**
- Windows CIでは同一スイートがPython 3.10〜3.12で実行され、Tk GUIのテストも含まれます。

## エンジンの動作確認（Linux上での実測）

- CMYK TIFF + 実SWOPプロファイル → LittleCMSでsRGB変換し、PDF内は `/ICCBased`（N=3）
- 白黒スキャン（G4 TIFF）→ `/CCITTFaxDecode` `/DeviceGray` 1bppで直接埋め込み。文書スキャン相当の画像でPDFサイズが約1/20（RGB PNG経由と比較）
- MPO → 主画像1ページのみ、元バイト列をそのまま埋め込み
- 6000×4000 JPEGのサムネイル生成（DCTスケーリング）約13ms
- 解像度タグのないTIFF → DPI既定値（96）を使用し、巨大ページにならない

## Windows CI（`build_winui.ps1`）で確認する内容

- Python テスト・ruff
- PyInstallerによるワーカー（`ImageToPDFWorker.exe`）の作成と、x64 PEの確認
- WinUI版の `PublishSingleFile` 発行。発行先にEXE以外のファイルがないことを確認
- EXEをUnicodeパスの一時フォルダーに単独でコピーし、埋め込みワーカーで日本語ファイル名の画像をPDFに変換（`--selftest-convert`、常駐プロトコルで実行）
- 同じEXEからウィンドウを表示し、タイトル「画像PDF変換ツール」を確認
- `SHA256SUMS.txt` とEXEのSHA-256の一致
- `LICENSE` / `THIRD_PARTY_NOTICES.md` の同梱

## リリース手順

- `app_config.py` の `VERSION`、`MainWindow.xaml` のバージョン表示、CHANGELOGの `## v2.1.0.1 ` 見出しを一致させます。
- タグ `v2.1.0.1` をプッシュすると、CIがビルドしたEXEとNOTICESでGitHub Releaseを作成します（リリースノートはCHANGELOGの該当セクションから生成）。

## まだ実施していない確認

- Python未導入の別Windows端末での起動
- 実際のエクスプローラーからのドラッグ＆ドロップ操作
- キャンセル、AVIF/HEICのサムネイル表示、プレビューの操作
- 複数モニター・複数DPI環境での画面確認
- 大量・巨大画像による性能と長時間負荷の測定
- 初回起動時の埋め込みワーカーの展開と、2回目以降の起動時間
- 別バージョンを上書きした場合の `%LOCALAPPDATA%\ImageToPDF\worker` の挙動
