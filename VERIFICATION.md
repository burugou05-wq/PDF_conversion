# v2.0.1 検証結果

## ICC / DPI追加検証

- `python -m pytest -q`: **67 passed, 2 skipped**（Python 3.11 / Linux、Tk display tests skipped）
- `python -m ruff check .`: **All checks passed**
- PDF内のICCBased色空間、sRGBへの実色変換、壊れたICCのスキップを回帰テスト
- PNG pHYs、JPEG EXIFの異なるX/Y解像度と単位変換、DPI既定値を回帰テスト
- Windows GUI / EXEのビルド・表示確認はCI実行後に追記します。

# v2.0 検証結果（過去のリリース）

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

## まだ実施していない確認

- Python未導入の別Windows端末での配布テスト
- 実際のエクスプローラーからのDnDイベント操作
- 複数モニター・複数DPI環境での画面確認
- 大量・巨大画像による性能と長時間負荷の測定
- 実行ファイル内での全画像形式のエンドツーエンド操作
- GitHub Actionsのリモート実行（ワークフローは追加済み）

これらは起動スモークテストや単体テストだけでは代替できません。配布前の確認事項として残します。
