# 画像 → PDF 変換ツール v2.1.1.0

Windows 11向けのネイティブ画面（WinUI 3）で、画像を並べてPDFにまとめるツールです。画像の追加・フォルダー追加、順番変更、検索、リスト／グリッド表示、プレビューと画像情報（寸法・DPI・ICC）、ドラッグ＆ドロップに対応します。CLIからも同じ変換エンジンを利用できます。

今回の変更内容は [更新履歴（一般ユーザー向け）](CHANGELOG.md) をご覧ください。

## EXEのダウンロード（一般ユーザー向け）

[最新のGitHub Release](https://github.com/burugou05-wq/PDF_conversion/releases/latest) の「Assets」から、`ImageToPDF-v<version>-Windows-x64.exe` を1つだけダウンロードして実行してください。ZIPの展開や、Pythonのインストールは不要です。

- 初回起動時、EXE内の変換エンジンを `%LOCALAPPDATA%\ImageToPDF\worker` に展開します。
- 正式版はWinUI 3版です。従来のTkinter版は v2.1.0 で配布を終了しました（ソースは互換性確認用に残しています）。
- 正式配布EXEにコード署名はありません。警告が出た場合は入手元を確認し、セキュリティソフトが危険と判定したファイルは実行しないでください。
- 同じ Release の `SHA256SUMS.txt` で、ダウンロードしたEXEのSHA-256を確認できます。

検証状況と制限は [更新履歴](CHANGELOG.md) をご確認ください。

## 動作環境

- Windows 10（2004 / ビルド19041以降）または Windows 11、64bit（x64）
- EXE利用時: Pythonのインストール不要
- ソース実行・ビルド: Python 3.10〜3.12（推奨3.11）。WinUI版のビルドには .NET 8 SDK と Visual Studio 2022 のMSBuildが必要です
- CLIと変換テストはLinuxでも実行可能（Tk版GUIにはTkとディスプレイが必要）

## 開発の起動

WinUI版の開発手順は [`winui/README.md`](winui/README.md) を参照してください。

Python変換エンジンのテストや CLI は、PowerShellでこのフォルダを開いて次を実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# AVIF/HEIFとドラッグ＆ドロップを使う場合（Tk版）
.\.venv\Scripts\python.exe -m pip install -r requirements-optional.txt
```

従来のTkinter版は `img2pdf_app.py` から起動できます（参考・互換用）。

基本対応形式: JPEG / PNG / WebP / BMP / GIF / TIFF。
AVIF対応はPillowの機能または追加プラグイン、HEIF/HEIC対応は追加プラグインが必要です。利用できない形式は理由付きでスキップされます。

## 操作

1. 「画像を追加」で画像を選ぶか、「フォルダーを追加」で対象フォルダーを選びます。画像ファイルやフォルダーをウィンドウにドラッグ＆ドロップすることもできます。
2. 「先頭へ」「上へ」「下へ」「末尾へ」で順番を変更します。「フォルダー並び順」（名前順・数字順・更新日時順）は、フォルダーから追加するときの並び方を決めます。
3. 一覧の画像を選ぶとプレビューを表示します。検索欄で表示を絞り込めます。「リスト」「グリッド」で表示を切り替えられ、グリッドはサムネイルを並べます（画面に見えている分だけを読み込みます）。
4. プレビューの下に、ファイル名・幅×高さpx（フレーム数）・DPIとその取得元・元寸法(mm)・ICCプロファイルを表示します。
5. 画質・用紙・余白・DPI不明時の既定値・透過画像の背景色を選びます。横長用紙への自動回転、完了後のPDFを開く設定もあります。
6. 出力先の `.pdf` パスを指定して「PDFに変換」を押します。処理中は「キャンセル」で中止できます。

- 検索は表示の絞り込みのみです。PDFには一覧の全画像が入ります。
- 検索中の削除・移動は選択したファイルに作用します。非表示のファイルも含む全体順序を変更します。
- フォルダモードの並び順: 名前、番号順（自然な数字順）、更新日（新しい順）。一覧はメモリにキャッシュし、検索文字の入力で再スキャンしません。反映するには「再読込」を押してください。
- サブフォルダは対象外です。
- 複数ページTIFF、アニメーションGIF/WebP等は全フレームをページ化します。カメラ・スマホのMPO形式（複数画像JPEG）は先頭の主画像のみを1ページにします。
- 壊れた入力はファイル単位でスキップし、完了時に理由を表示します。途中フレームが壊れた場合、そのファイル全体をスキップします。

## 画質と用紙の仕様

### 元画質優先

- 透過なし・向き補正不要の単一JPEG/PNGは直接取り込みます。JPEGの圧縮データは保持され、全画素のデコードも行いません。MPO形式（複数画像JPEG）は先頭の主画像のバイト列をそのまま埋め込みます。
- CCITT Group 4圧縮の白黒TIFF（スキャン文書で一般的）は、ファックスデータをそのままPDFに埋め込みます。グレースケール・白黒画像をRGBに展開しないため、サイズが膨らみません。
- その他の画像はデコードし、EXIF方向を補正、必要に応じて背景合成してPNGへ変換します。このときグレースケール・白黒はモードを保ちます。
- 再エンコード時は元画像のICCプロファイルを保持します。iPhoneのDisplay P3やAdobe RGBの画像も、PDF内でICCベースの色空間として埋め込まれます。CMYK画像はICCプロファイルに基づきLittleCMSでsRGBに変換します（プロファイルがない場合は単純変換）。
- 用紙サイズと余白のために画像を再圧縮することはありません。PDF上の配置サイズで調整します。
- 「すべてのメタデータ・ビット深度を完全保存」するモードではありません。16bit画像は8bitに変換されます。

### 軽量化

- PDF上の表示寸法に対して最大150dpiへ縮小し、JPEG品質85で保存します。拡大しません。
- 画像内容によってはファイルが小さくならない場合があります。

### 用紙と余白

- A4 / A3 / Letterの物理寸法をPDFのポイント座標で設定します。
- 画像は中央配置し、余白内に収めます。元の物理寸法より大きく拡大しません。
- 横長画像の用紙自動回転は解除できます。
- 「元のサイズ」では元画像のDPIを参照し、不正・不明なら96dpiとして計算します。
- 余白は0〜100mmです。背景色は画像の透過部分への合成色であり、PDFの余白は通常白表示です。

## 保存・キャンセル

出力先と同じフォルダに一時ファイルを保存し、完成してから公開します。既存PDFの上書きは明示確認が必要です。キャンセルや保存失敗では既存PDFを置き換えません。

上書きなしの公開は、Windowsでは既存ファイルを決して上書きしない `os.rename` を使うため、NTFSだけでなくexFAT/FAT32のUSBメモリやSDカードにも保存できます。POSIX環境ではハードリンクで同じ保証を得ます。安全性を優先し、直接書き込みへのフォールバックは行いません。

キャンセルは画像・フレーム間と保存前に確認します。実行中の画像デコードやPDF書き込みを強制中断しないため、反映まで時間がかかる場合があります。

## EXEビルド（正式版: WinUI 3・単一EXE）

Windows 11 / 10 x64 で、PowerShellから次を実行します。Python 3.10〜3.12、.NET 8 SDK、Visual Studio 2022 のMSBuildが必要です。

```powershell
.\build_winui.ps1
```

テスト・コードチェック後、次を作成して検証します。

- `dist\ImageToPDF-v<version>-Windows-x64.exe`: 配布用の単一EXE（Releaseに添付するファイル）
- `dist\SHA256SUMS.txt`: 上記EXEのSHA-256

スクリプトはPyInstallerで変換ワーカー（`ImageToPDFWorker.exe`）を作り、WinUI版EXEの中に埋め込みます。公開されたEXEを一時フォルダーへ単独でコピーし、次を確認します。

- 日本語パスの画像を、埋め込みワーカーでPDFに変換できること
- ウィンドウが表示されて起動できること

従来のTkinter版は `build.py`（PyInstaller、ローカル用）から引き続きビルドできますが、正式配布の対象ではありません。両者とも `dist\` に `ImageToPDF-v<version>-Windows-x64.exe` を出力するため、同じフォルダーで両方をビルドする場合は名前を変えて保存してください。

GitHub Actions（`ci.yml`）は、テスト成功後に上記のWinUI版をビルドします。`app_config.py` のバージョンに一致する `v<バージョン>` タグをpushすると、そのEXEと `SHA256SUMS.txt` をGitHub Releaseに公開します。CHANGELOG.mdの該当セクションがリリースノートになります。既存ReleaseのAssetsは、タグをpushしただけでは変更されません。

## WinUI 3版の開発

画面は `winui/ImageToPDF.WinUI/` にあります。開発手順と構成は [`winui/README.md`](winui/README.md) を参照してください。

## CLI

```powershell
.\.venv\Scripts\python.exe cli.py image1.jpg image2.png -o result.pdf --page A4 --margin 10
.\.venv\Scripts\python.exe cli.py .\images -o result.pdf --quality compact --overwrite
```

終了コード: `0`=成功、`1`=失敗、`2`=一部スキップして成功。

## 開発・テスト

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

CIはWindows/LinuxのPython 3.10〜3.12でテストし、Windows上でWinUI版の単一EXEを生成します。バージョンタグ（`v` + app_config.py のVERSION）からはGitHub Releaseも公開します。
直接依存は固定しています。完全な推移依存ロックではありません。依存とGitHub Actionsの更新はDependabotが週次で提案します（ActionsはコミットSHAに固定しています）。

## ライセンス

このリポジトリのコードはMIT License（[LICENSE](LICENSE)）の下で公開しています。配布物に含まれる依存ライブラリのライセンスと、特にpillow-heifのバイナリwheel（GPLv2）に関する注意は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を確認してください。

構成:

- `winui/ImageToPDF.WinUI/`: 正式版のWinUI 3画面（C#）
- `conversion_worker.py`: WinUI版から呼び出す変換ワーカー（JSON Lines）。PyInstallerで `ImageToPDFWorker.exe` にしてEXEへ埋め込みます
- `image_processor.py`: 変換エンジン（画像処理、PDF配置、安全な保存）
- `cli.py`: CLI（Pythonソースから実行）
- `img2pdf_app.py`, `file_model.py`, `ui_theme.py`: 従来のTkinter版（互換用）
- `app_config.py`: 名前・バージョン・配布設定
- `app_paths.py`: Tkinter版のログ保存先（ポータブル版はアプリフォルダー内）。WinUI版のログ保存先はC#側（`Services/AppLog.cs`）で解決します
- `tests/`: 選択操作、用紙寸法、画像処理、キャンセル、配布パス、ワーカープロトコルの回帰テスト
- `build_winui.ps1`: 正式版のWinUI単一EXEのビルドと検証

## 制限・運用

- 自己更新機能はありません。配布元から新しいEXEを手動で取得してください。
- グリッド表示のサムネイルは、画面に見えている分だけを作り、最近使った順に最大128枚をメモリに保持します。上限を超えた分は解放し、再び表示されるときに作り直します。
- 画像前処理は逐次実行し、巨大画像の同時展開を避けます。ただしPDF結合のオブジェクトはメモリに保持されるため、無制限の大量画像処理を保証しません。
- 画像パーサーの安全性のため、Pillowの巨大画像保護を無効にしていません。
- ログ: 起動、変換の開始・完了・キャンセル・失敗理由、スキップした画像、ワーカーの起動と終了を `%LOCALAPPDATA%\ImageToPDF\app.log` に記録します（WinUI版・Tkinter版とも）。1MBを超えると `app.log.1`〜`app.log.3` へ繰り下げ、最大4ファイル（約4MB）まで保持します。Tkinter版のポータブル版は実行ファイルの隣の `PortableData\app.log` です。画像パスや失敗理由を含むため、共有前に内容を確認してください。
- WinUI版が展開する変換エンジンは `%LOCALAPPDATA%\ImageToPDF\worker` にあります。古いバージョンのフォルダーは自動では削除しません。不要になったら手動で削除できます。
- 配布ライセンスはMIT Licenseです。依存ライブラリの条件（img2pdfのLGPL、pillow-heifバイナリwheelのGPLv2など）は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。
