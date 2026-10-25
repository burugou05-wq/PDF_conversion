# v2.2.0.0 検証結果

## 対象

- 正式版: WinUI 3版（単一EXE `ImageToPDF-v2.2.0.0-Windows-x64.exe`）
- 今回の変更: Tkinter版の削除とWinUI 3版への一本化（Phase 5）
  - 削除: `img2pdf_app.py` / `ui_theme.py` / `build.py` / `ImageToPDF.spec` / `app_paths.py` / `tests/test_ui.py` / `tests/test_build.py` / `tests/test_app_paths.py` / `requirements-optional.txt` の `tkinterdnd2`
  - 変換エンジン（`image_processor.py`）とワーカー（`conversion_worker.py` / `ConversionWorker.spec`）の出力仕様は v2.1.1.0 から変更していません
  - `file_model.py` はCLIが利用するため残しています

## v2.3.1.0 での追加（インストーラー化と上書き自動更新）

- Inno Setup（`installer/ImageToPDF.iss`）でユーザー領域インストーラー `ImageToPDF-Setup-v<version>-Windows-x64.exe` を生成する（デスクトップショートカット作成のチェックボックス付き）
- 自動更新時は `ImageToPDF-Setup-*.exe` を優先して選び、サイレント更新引数（`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /AUTOLAUNCH=1`）で起動する
- インストール先から起動した際に `%LOCALAPPDATA%\ImageToPDF\updates\` 内の一時ファイルを自動削除する
- `build_winui.ps1` で実際にインストーラーをサイレント実行し、展開された `ImageToPDF.exe` と `unins000.exe` に対して変換・更新自己診断・起動確認・アンインストール確認を行う

## v2.3.0.0 での追加（アップデート機能）

- 起動時に最新リリースを確認し、新しい版があるときだけバージョン表示に青い点を出す
- バージョン表示のタップで、現在のバージョン・確認時刻・リリースノート・更新ボタンを表示する
- 「更新する」で取得したファイルのサイズ・SHA-256・MZ形式を検証し、失敗したら削除して中止する
- 通信できないときは理由を表示し、前回の情報があればそれで判定する

CIでは `--selftest-update` により、解析・バージョン比較・SHA-256照合・ダイアログ生成までをネットワークなしで確認します。実際の通信・ダウンロード・起動の置き換えはCIでは行いません（実機での確認項目です）。

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
- アップデート: 青い点の表示、ダイアログの見た目とリリースノートのリンク、実際の更新（オフライン時の表示、キャンセル、検証失敗時のメッセージ）

## Windows CI（`build_winui.ps1`）で確認している内容

- Python テスト・ruff
- バージョン整合（`app_config.py` の VERSION と `MainWindow.xaml` の表示）
- PyInstallerによるワーカー（`ImageToPDFWorker.exe`）の作成と、x64 PEの確認、Unicodeパスでの変換
- WinUI版の `PublishSingleFile` 発行。発行先にEXE以外のファイルがないことを確認
- EXEをUnicodeパスの一時フォルダーに単独でコピーし、埋め込みワーカーで日本語ファイル名の画像をPDFに変換（`--selftest-convert`、常駐プロトコルで実行）
- **同じ実行で app.log に変換の記録が残り、1MBを超えて `app.log.1` へ繰り下げられることを確認**（`IMAGETOPDF_APP_LOG` で一時ファイルへ向けるため、実行機のログは汚しません）
- `--selftest-update` で、リリース応答の解析・バージョン比較・SHA-256照合・更新ダイアログの生成を確認（ネットワークなし）
- 同じEXEからウィンドウを表示し、タイトル「画像PDF変換ツール」と、**app.log への起動記録**を確認
- `SHA256SUMS.txt` とEXEのSHA-256の一致
- `LICENSE` / `THIRD_PARTY_NOTICES.md` の同梱

## エンジンの動作確認（v2.1.0.1 で実施済み・変更なし）

- CMYK TIFF + 実SWOPプロファイル → LittleCMSでsRGB変換し、PDF内は `/ICCBased`（N=3）
- 白黒スキャン（G4 TIFF）→ `/CCITTFaxDecode` `/DeviceGray` 1bppで直接埋め込み
- MPO → 主画像1ページのみ、元バイト列をそのまま埋め込み
- 6000×4000 JPEGのサムネイル生成（DCTスケーリング）約13ms
- 解像度タグのないTIFF → DPI既定値を使用し、巨大ページにならない

検証に使う実ICCプロファイル（SWOPなど第三者の配布物）はリポジトリにコミットしません。ローカルのe2e検証でのみ使用します。

## リリース手順

- `app_config.py` の `VERSION`、`MainWindow.xaml` のバージョン表示、`ImageToPDF.WinUI.csproj` の `Version`、CHANGELOGの `## v2.2.0.0 ` 見出しを一致させます（`build_winui.ps1` が app_config と XAML の整合をチェックし、不一致だとCIが落ちます）。
- CIが緑になったことを確認してからタグ `v2.2.0.0` をプッシュします（緑の前にタグを打たないこと）。CIがビルドしたEXEとNOTICESでGitHub Releaseを作成します（リリースノートはCHANGELOGの該当セクションから生成）。
- リリースノートは `awk 'index($0, "## v<バージョン> ") == 1'` でCHANGELOGから抽出されます。見出しは必ず `## v<バージョン> ` + 半角スペース + タイトルの形にしてください。
- publish-releaseジョブの成功と、Release資産4点（`ImageToPDF-v<バージョン>-Windows-x64.exe` / `SHA256SUMS.txt` / `LICENSE` / `THIRD_PARTY_NOTICES.md`）を確認します。
- 依存ライブラリのバージョンを上げたときは、`THIRD_PARTY_NOTICES.md` の表も合わせて更新します（NOTICESはRelease資産として配布物に同梱されるため）。
