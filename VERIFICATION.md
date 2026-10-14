# v2.0 検証結果

## 実行環境

- Windows x64
- Python 3.10.11
- `.venv` に隔離した依存環境
- 実際に使った依存一覧: `requirements-lock-windows-py310.txt`

このロックはWindows/Python 3.10の検証環境用です。他OS/Python版にそのまま適用することは推奨しません。通常のセットアップはREADMEのrequirementsファイルを使用してください。

## 実行済み

- `python -m pytest -q`: **52 passed**
- `python -m ruff check .`: **All checks passed**
- `python build.py --skip-install`: **成功**
- `python scripts/smoke_exe.py dist/画像PDF変換ツール.exe`: **ウィンドウ表示・正常終了成功**

## テスト対象

- ファイル選択・検索後の削除・移動、複数選択の順序保持、ドラッグ移動モデル
- 自然な数字順、重複追加、画像拡張子のディレクトリ除外
- A4物理寸法、横長用紙、余白のポイント計算
- TIFFとGIFの全フレーム、入力順とPDFページ順の一致
- JPEG / PNG / BMP / GIF / WebP / TIFF / AVIF / HEIF
- 元JPEG圧縮データの保持、軽量化解像度、透過背景合成、EXIF方向
- DPIの不正値、余白入力の不正値
- 壊れた画像のスキップ、全件失敗、既存出力の保護
- キャンセル、ディスク不足、置換失敗、一時ファイルの除去
- 同時に作られた出力を上書きしないこと
- GUIウィジェット構築とGUI上の検索後削除
- CLI成功・失敗・一部スキップの終了コード

## ポータブル版の追加

通常版の単体EXEを維持したまま、PyInstaller onedir形式のポータブルZIPを作成するビルド処理を追加しました。ポータブル版は `portable.flag` を目印にログを実行ファイルの隣の `PortableData` へ保存し、通常版の `%LOCALAPPDATA%` は使いません。配布ZIPには両形式のSHA-256一覧も含めます。

配布処理の単体テストでは、通常版EXE・ポータブルZIP・チェックサムの作成と、ZIP内のフォルダー構成を確認します。Windows向けPyInstaller onedirビルドと実機での起動・書き込みは、まだこの変更を含めて検証していません。

今回の変更に対するLinux/Python 3.11での確認: `python -m pytest -q` は **59 passed, 2 skipped**（Tk GUIテストはディスプレイがないためskip）、`python -m ruff check .` は **All checks passed**。

## WinUI 3 UIプレビュー

C#のWinUI 3画面と、既存Python変換エンジンを呼び出すJSONLワーカーを追加しました。Linux上の自動テストでワーカーの変換・進捗・部分スキップ・サムネイルプロトコルを確認し、[Windows CI run 38367226687](https://github.com/burugou05-wq/PDF_conversion/actions/runs/38367226687) でWinUIのコンパイル／publish、同梱ワーカーによるPDF変換スモークテスト、プレビューZIPとSHA-256一覧の生成まで成功しました。Actions artifact名は `ImageToPDF-WinUI-Preview` です。実機での画面起動・操作はまだ検証していないため、これは試作版であり、通常Releaseは従来UIのままです。

## まだ実施していない確認

- Python未導入の別Windows端末での配布テスト
- ポータブルZIPのWindows上での展開、起動、ログ保存とフォルダー移動
- 実際のエクスプローラーからのDnDイベント操作
- 複数モニター・複数DPI環境での画面確認
- 大量・巨大画像による性能と長時間負荷の測定
- 実行ファイル内での全画像形式のエンドツーエンド操作

これらは起動スモークテストや単体テストだけでは代替できません。配布前の確認事項として残します。
