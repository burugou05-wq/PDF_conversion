# v2.0.1 ICC / DPI改善

- 画像内のICCプロファイルを使い、再エンコードが必要な画像をsRGBへ色変換。中間PNG/JPEGにもsRGB ICCを埋め込み、`img2pdf` がPDFのICCBased色空間として出力する回帰テストを追加。
- ICCのないDeviceRGB画像にもsRGB ICCBased色空間をPDF側で付与。JPEGの画像ストリームは元データのまま維持。
- 不正なICCプロファイルは理由付きでスキップし、誤った色を黙って出力しない。
- DPI値だけでなく取得元も返す `resolve_dpi` を追加。JPEGはEXIFのX/Y解像度を優先、TIFFはタグを優先し、PNG/JFIF等はPillowのDPI情報を使用。
- DPIが取得できない場合の既定値を `ConversionOptions`・GUI・CLIで指定可能にし、プレビューとCLI verboseで値・出所・元寸法を表示。
- ICC、プロファイル変換、DPIの単位・フォールバックを回帰テストに追加。

# v2.0 再構築記録

旧版の改善記録は実装と一致しなかったため、現在の構成に合わせて更新しました。

## 実装した変更

- GUIから画像処理・テーマを分離し、重複した変換処理を削除。
- 選択は表示インデックスではなくファイルパスで管理。検索後の削除・移動を修正。
- DnDデータはルートのTclインタープリターで解析。
- A4/A3/Letterと余白をPDFの物理座標で指定。画像キャンバスの再圧縮を廃止。
- 複数フレーム画像は設定にかかわらず全フレームを処理。
- 元画質優先／軽量化の2モードに統一。軽量化は150dpi上限・JPEG品質85。
- EXIF方向補正、透過背景合成、DPI検証を共通処理化。
- PIL画像処理をワーカーで行い、Tk画像はメインスレッドで生成。
- キュー通知、協調キャンセル、終了処理を追加。
- グリッド表示を48件ずつ、サムネイルキャッシュを100件に制限。
- 失敗理由の通知とローテーションログを追加。
- 一時ディレクトリとアトミックな出力公開で既存PDFを保護。
- 未検証の自己更新とTurboJPEG依存を削除。
- CLI、回帰テスト、CIを追加。
- ビルドは共通specへ一本化。PowerShellはラッパー化。
- 実行／任意／開発依存を分離し、直接依存バージョンを固定。

## 残る制約

- CMYK画像のICC変換はsRGBへの変換のみ。16bit画像は8bitに変換される。
- PDF結合時のメモリ使用量は総入力サイズに依存する。
- キャンセルは処理境界で反映される。
- 上書きなしの保存はWindowsではexFAT/FAT32対応、POSIXではハードリンク対応のファイルシステムが必要。
- 完全な推移依存ロックとコード署名（Authenticode）は未実装。配布は v2.3.1.0 以降インストーラーに一本化し、`SHA256SUMS.txt` の電子署名は導入済み（[RELEASING.md](RELEASING.md)）。
- 実際のWindows画面での操作確認とPython未導入環境の配布確認は必要。

## v2.1.0.1 での追加改善

- MPO形式JPEGは先頭フレーム（主画像）のみをページ化し、バイト列をそのまま埋め込む。
- 再エンコード時にICCプロファイルを保持し、CMYKはImageCmsでsRGBに変換。
- JPEG/PNGパススルー時に全画素デコードを廃止（ヘッダ情報のみで判定）。
- グレースケール/白黒のモード保持とCCITT G4 TIFFの直接埋め込み。
- Windowsの上書きしない保存をos.renameに変更し、exFAT/FAT32に対応。
- フォルダモードの検索は一覧キャッシュでメモリ上の絞り込みに変更。
- サムネイルのDCTスケーリング縮小デコードとLRUキャッシュ。
- 複数選択ドラッグの選択保持を修正、natural_keyを位置ベース判定に変更。
- WinUIワーカーを常駐化（リクエストID多重化）し、Job Objectで寿命管理。
- LICENSE（MIT）とTHIRD_PARTY_NOTICES.mdを追加。ActionsをSHA固定しDependabotを導入。

## v2.1.1.0 での追加改善（Tkinter版の機能をWinUI版へ移植）

- `Services/AppLog.cs` を追加。app.log（1MB×3世代のローテーション）をPython非依存のC#だけで実装。
- ワーカーに `inspect`（画像情報）と `thumbnailSize`（サムネイル寸法）を追加。終端イベント判定とswitchの両方に登録。
- 「DPI不明時の既定値」（1〜10000）をNumberBoxで指定可能にし、範囲外は変換前に拒否。
- プレビュー下の画像情報表示（寸法・フレーム数・DPI取得元・元寸法mm・ICC）。
- リスト／グリッド表示の切り替え。サムネイルは仮想化（`ContainerContentChanging`）+ LRU 128枚、実現中のタイルは追い出さない。

## v2.2.0.0 での整理（Tkinter版の削除）

- Tkinter版のUI（`img2pdf_app.py` / `ui_theme.py`）、旧ビルド（`build.py` / `build.ps1` / `ImageToPDF.spec` / `dpi_aware.manifest`）、ポータブル版のログ解決（`app_paths.py`）と対応テストを削除。
- `app_config.py` は `APP_NAME` と `VERSION` だけにした（`APP_DATA_DIRECTORY` / `PORTABLE_*` は利用者が消えた）。
- 任意依存から `tkinterdnd2` を削除し、THIRD_PARTY_NOTICES.md とロックファイルも追随。
- Windows CIのTk起動skip判定（ランナーのTcl欠損workaround）が消え、テストは 105 passed / 0 skipped で安定。
- 変換エンジン（`image_processor.py` / `conversion_worker.py` / `ConversionWorker.spec`）とCLI（`cli.py` / `file_model.py`）は変更なし。

## v2.3.0.0 での追加改善（アップデート確認）

- `Services/UpdateChecker.cs`: GitHub Release API の最新版を取得し、タグを数値バージョンに変換して比較。下書き・プレリリース・数値でないタグは無視。結果は `update-cache.json` に保存し、自動確認は6時間に1回。通信できないときは前回の内容で判定する。
- `Services/UpdateDownloader.cs`: EXEと `SHA256SUMS.txt` を `updates\<タグ>\` へ取得し、サイズ・SHA-256（sha256sum形式、`*` 表記対応）・MZ形式を検証。検証に失敗したファイルは削除。チェックサムが無いリリースは中止。古い版のダウンロードは次の更新時に掃除する。
- `UpdateDialog.xaml(.cs)`: バージョン表示（ボタン）から開くダイアログ。リリースノートのMarkdownは見出し・本文・URLリンクに変換して表示。ダウンロード中の進捗とキャンセルに対応し、成功時は新しいEXEを起動してアプリを終了する。
- `Services/UpdateSelfTest.cs` と `--selftest-update`: ネットワークなしで解析・比較・照合・ダイアログ生成を検証し、`build_winui.ps1` が単一EXEで実行する。
- バージョン表示を、押せるボタン＋新しい版があるときだけ出る青い点に変更（`AutomationProperties.Name` も更新）。
- 起動確認のCIでは `IMAGETOPDF_DISABLE_UPDATE_CHECK=1` を設定し、外部通信を行わない。
