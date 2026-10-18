# v2.2.0.0 検証結果

## 対象

- 正式版: WinUI 3版（単一EXE `ImageToPDF-v2.2.0.0-Windows-x64.exe`）
- 今回の変更: Tkinter版の削除とWinUI 3版への一本化（Phase 5）
  - 削除: `img2pdf_app.py` / `ui_theme.py` / `build.py` / `ImageToPDF.spec` / `app_paths.py` / `tests/test_ui.py` / `tests/test_build.py` / `tests/test_app_paths.py` / `requirements-optional.txt` の `tkinterdnd2`
  - 変換エンジン（`image_processor.py`）とワーカー（`conversion_worker.py` / `ConversionWorker.spec`）の出力仕様は v2.1.1.0 から変更していません
  - `file_model.py` はCLIが利用するため残しています

## 自動テスト（Linux / Python 3.11）

- `python -m pytest -q`: **105 passed, 0 skipped**（Tk GUIのテストは削除したためskipなし）
- `python -m ruff check .`: **All checks passed**
- Windows CIでは同一スイートがPython 3.10〜3.12で実行されます。
- このリポジトリのLinux環境には .NET SDK がないため、C#は構文解析（tree-sitter）とWindows CIのコンパイル・セルフテストで検証します。

## 画面の操作（Windows実機での確認が必要なもの）

CIはコンパイルと起動、パッケージEXEの変換までしか確認できません。次は実機での確認項目です。

- 「リスト」「グリッド」の切り替えと、グリッドでのサムネイル表示・スクロール・選択（Ctrl/Shift）
- 大量画像（数百枚）をグリッドでスクロールしたときのメモリと応答（LRUの追い出し）
- 「DPI不明時の既定値」の変更と、プレビュー下の元寸法(mm)の追従
- 解像度タグのない画像での既定DPIの効果（PDFのページ寸法）
- ICCプロファイル名・DPI取得元の表示（表示内容は `inspect_image` の戻り値そのもの）
- `%LOCALAPPDATA%\ImageToPDF\app.log` の内容と、1MB到達時の `app.log.1`〜`app.log.3` への繰り下げ
- キャンセル、AVIF/HEICのサムネイル表示、ドラッグ＆ドロップ、複数モニター・複数DPI環境

## Windows CI（`build_winui.ps1`）で確認している内容

- Python テスト・ruff
- バージョン整合（`app_config.py` の VERSION と `MainWindow.xaml` の表示）
- PyInstallerによるワーカー（`ImageToPDFWorker.exe`）の作成と、x64 PEの確認、Unicodeパスでの変換
- WinUI版の `PublishSingleFile` 発行。発行先にEXE以外のファイルがないことを確認
- EXEをUnicodeパスの一時フォルダーに単独でコピーし、埋め込みワーカーで日本語ファイル名の画像をPDFに変換（`--selftest-convert`、常駐プロトコルで実行）
- **同じ実行で app.log に変換の記録が残り、1MBを超えて `app.log.1` へ繰り下げられることを確認**（`IMAGETOPDF_APP_LOG` で一時ファイルへ向けるため、実行機のログは汚しません）
- 同じEXEからウィンドウを表示し、タイトル「画像PDF変換ツール」と、**app.log への起動記録**を確認
- `SHA256SUMS.txt` とEXEのSHA-256の一致
- `LICENSE` / `THIRD_PARTY_NOTICES.md` の同梱

## エンジンの動作確認（v2.1.0.1 で実施済み・変更なし）

- CMYK TIFF + 実SWOPプロファイル → LittleCMSでsRGB変換し、PDF内は `/ICCBased`（N=3）
- 白黒スキャン（G4 TIFF）→ `/CCITTFaxDecode` `/DeviceGray` 1bppで直接埋め込み
- MPO → 主画像1ページのみ、元バイト列をそのまま埋め込み
- 6000×4000 JPEGのサムネイル生成（DCTスケーリング）約13ms
- 解像度タグのないTIFF → DPI既定値を使用し、巨大ページにならない

## リリース手順

- `app_config.py` の `VERSION`、`MainWindow.xaml` のバージョン表示、`ImageToPDF.WinUI.csproj` の `Version`、CHANGELOGの `## v2.2.0.0 ` 見出しを一致させます。
- CIが緑になったことを確認してからタグ `v2.2.0.0` をプッシュします（緑の前にタグを打たないこと）。CIがビルドしたEXEとNOTICESでGitHub Releaseを作成します（リリースノートはCHANGELOGの該当セクションから生成）。
