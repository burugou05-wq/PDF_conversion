# v2.1.1.0 検証結果

## 対象

- 正式版: WinUI 3版（単一EXE `ImageToPDF-v2.1.1.0-Windows-x64.exe`）
- 今回の変更: Tkinter版にあってWinUI版に無かった機能の移植（Phase 1〜4）
  - Phase 1: 操作ログ（`app.log`、1MB×3世代のローテーション）
  - Phase 2: DPI不明時の既定値（1〜10000）
  - Phase 3: 画像情報の表示（寸法・フレーム数・DPIの取得元・元寸法・ICC）
  - Phase 4: グリッド表示（サムネイル、LRU 128枚、仮想化による遅延読み込み）
- 変換エンジン（`image_processor.py`）の出力仕様は v2.1.0.1 から変更していません。ワーカーに追加したのは `inspect` 操作と `thumbnailSize` の指定だけで、`convert` の挙動は同じです。

## 自動テスト（Linux / Python 3.11）

- `python -m pytest -q`: **110 passed, 5 skipped**（Tk GUIのテストはディスプレイがないためskip、AVIF/HEIFはオプションのためskip）
- `python -m ruff check .`: **All checks passed**
- 追加したテスト: ワーカーの `inspect`（寸法・DPI・ICC、既定DPIの反映、範囲外の既定DPIの拒否、サーバーモードでの終端イベント）と `thumbnailSize`（指定寸法の反映、既定の640×480、範囲外の拒否）
- Windows CIでは同一スイートがPython 3.10〜3.12で実行され、Tk GUIのテストも含まれます。
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

- `app_config.py` の `VERSION`、`MainWindow.xaml` のバージョン表示、`ImageToPDF.WinUI.csproj` の `Version`、CHANGELOGの `## v2.1.1.0 ` 見出しを一致させます。
- CIが緑になったことを確認してからタグ `v2.1.1.0` をプッシュします（緑の前にタグを打たないこと）。CIがビルドしたEXEとNOTICESでGitHub Releaseを作成します（リリースノートはCHANGELOGの該当セクションから生成）。
