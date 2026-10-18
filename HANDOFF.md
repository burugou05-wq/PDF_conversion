# 引き継ぎ文書 — Tkinter→WinUI機能移植 → Tkinter削除（次チャットスレッド向け）

作成: 2026-10-18（v2.1.0.1 リリース直後）
対象読者: 次スレッドの担当エージェント。まずこの文書を読んでから作業すること。

---

## 1. 現在の状態

- **v2.1.0.1 リリース完了済み**
  https://github.com/burugou05-wq/PDF_conversion/releases/tag/v2.1.0.1
  資産: ImageToPDF-v2.1.0.1-Windows-x64.exe（約104MB）/ SHA256SUMS.txt / LICENSE (MIT) / THIRD_PARTY_NOTICES.md
- ブランチ `arena/a9ee149b-pdf-conversion` @ `a37e685`、タグ `v2.1.0.1`（mainは `ccbf9df` から分岐）
- CI run 39099333183 **全緑**（テスト6ジョブ + winui-build + publish-release）
- ローカル: 101 passed / 7 skipped / ruff clean（sandboxはLinux・Tk表示不可のためTk UIテストはskip）

## 2. 次スレッドのミッション（ユーザー決定・2026-10-18）

> **「Tkinter版にあってWinUI版にない機能をWinUIへ段階的に追加し、揃ったらTkinterを消す」**

- 各Phaseを独立して実装 → CI全緑 → （ユーザーの判断で）リリース。Phase 5（削除）は**全機能の移植完了後のみ**実行する
- 順序案（小さい・独立したものから。順序はユーザーと相談可）:
  1. **Phase 1: ログファイル**（app.log）
  2. **Phase 2: 既定DPI変更**（Python側は既に対応済み、C#側のみ）
  3. **Phase 3: ICC/DPI情報の詳細表示**（ワーカーにinspect operationの追加が必要）
  4. **Phase 4: グリッド表示**（最大のUI作業）
  5. **Phase 5: Tkinter一式の削除**

## 3. アーキテクチャ（ファイル地図）

```
WinUI 3版（正式）                          Tkinter版（旧・互換用）
MainWindow.xaml(.cs)  UI本体               img2pdf_app.py (794行)  UI本体
MainViewModel.cs      状態管理             ui_theme.py (38行)      テーマ
ConversionWorkerService.cs  通信窓口       ↑ 直接import（ワーカー不要）
EmbeddedWorker.cs     EXE内蔵ワーカー自己抽出
WorkerProtocol.cs     JSON境界のDTO
SelfTest.cs/App.xaml.cs  ビルド検証モード
        │ JSON over stdin/stdout
conversion_worker.py (262行)  エンジンのJSONラッパー
        │ import
image_processor.py (782行)  ★変換エンジン本体（convert_to_pdf / inspect_image / make_thumbnail）
file_model.py (110行)       ファイルリスト・自然順ソート
app_config.py / app_paths.py  バージョン定数 / ログ保存先
cli.py (81行)               コマンドライン版（第3の入り口）
```

- ビルド: `build_winui.ps1`（ruff → バージョン整合チェック → PyInstallerでワーカー凍結[ConversionWorker.spec] → ワーカー単体テスト → dotnet publish単一EXE → 完成EXEのセルフテスト → SHA256SUMS）
- CI: `.github/workflows/ci.yml`（テスト6ジョブ → winui-build → タグpushでpublish-release）

## 4. Phase別の実装ガイド

### Phase 1: ログファイル（app.log）
- **Tk実装**: `img2pdf_app.py:41-56` `configure_logging()` — RotatingFileHandler(maxBytes=1MB, backupCount=3, utf-8, INFO)。保存先は `app_paths.py:10` `log_directory()`（通常 `%LOCALAPPDATA%\ImageToPDF\app.log`、ポータブル版はEXE横の `PortableData\`）
- **WinUI現状**: ログを一切作らない
- **やること**: C#側（System.IO）で `%LOCALAPPDATA%\ImageToPDF\app.log` に変換の成功/失敗（画像パス・理由・ページ数）を記録。簡易ローテーション（1MB×3世代）でよい。WinUI版にポータブル版は無いので固定パスでOK
- **設計メモ**: Pythonのapp_paths.pyに依存しない（C#自己完結）にするとPhase 5でapp_paths.pyごと削除できる

### Phase 2: 既定DPI変更
- **Tk実装**: `img2pdf_app.py:140,150,305-311`（UI: 「DPI不明時の既定値」Entry）と `:507-529`（検証: 1〜10000、エラー文言「DPI不明時の既定値は1〜10000で指定してください」）
- **★重要: Python側は実装済み** — `conversion_worker.py:78` はリクエストの `defaultDpi` を既に受け取り `ConversionOptions(default_dpi=...)` に渡す。検証（1〜10000）も `image_processor.py` ConversionOptionsにある。エンジン一式の変更は**不要**
- **やること（C#のみ）**: `WorkerProtocol.cs` の WorkerOptions に `DefaultDpi` を追加（JSON名は `defaultDpi`）、MainWindow.xaml(.cs) にEntry+検証+永続化、ConversionWorkerServiceへの受け渡し

### Phase 3: ICC/DPI情報の詳細表示
- **Tk実装**: `img2pdf_app.py:690-712` — プレビュー下に「{width}×{height}px / Nフレーム」「DPI: h × v (取得元)」「元寸法: mm × mm」「ICC: プロファイル名」を表示
- **エンジンは実装済み**: `image_processor.py:248` `inspect_image()` → `ImageInfo`（width/height/dpi: DpiInfo{horizontal,vertical,source}/frame_count/icc_profile）
- **不足**: ワーカーは `convert` / `thumbnail` の2 operationのみ（`conversion_worker.py:87-101`）。**`inspect` operationを conversion_worker.py に追加**し、C#のDTO（WorkerMessageに幅・高さ・DPI・ICC等）とMainWindowの情報パネル（PreviewHint付近）を実装
- **注意**:ICCの詳細表示は `inspect_image` の戻り値だけで作れる。CMYK→sRGB変換の検証資材（AGPLのArtifex SWOPプロファイル `/tmp/cmyk.icc`）は**絶対にコミットしない**（ローカルe2e専用）

### Phase 4: グリッド表示
- **Tk実装**: `img2pdf_app.py:124-129`（grid_page/grid_selection/grid_anchor/grid_cells状態）、`:202`（リスト/グリッド切替）、`:232-244`（Canvas+スクロールバー）、`:545` `render_grid`、`:587` `grid_click`、`:607` `apply_thumbnail`、サムネLRUキャッシュ100枚
- **サムネ生成は実装済み**: engine `make_thumbnail(240x200)`、かつワーカー `thumbnail` operationはWinUIのプレビュー・フォールバック（`MainWindow.xaml.cs` FilesList_SelectionChanged内）で**使用実績あり**
- **やること**: WinUIのGridView/ItemsRepeater+仮想化でサムネ一覧、リスト/グリッド切替、複数選択。Tkのページング相当はWinUIの仮想化で不要になる見込み
- **参考**: サムネ生成は13ms/枚（6000×4000画像）。ローカルのtkinterdnd2問題・Tk制約は移植対象外（WinUIのD&Dは実装済み）

### Phase 5: Tkinter一式の削除（全Phase完了後のみ）
- **削除**: `img2pdf_app.py` / `ui_theme.py` / `tests/test_ui.py` / `build.py` / `tests/test_build.py` / `ImageToPDF.spec`
- **残す**: `image_processor.py` / `conversion_worker.py` / `ConversionWorker.spec` / `cli.py` / `file_model.py`（cli.pyが使用）/ `tests/`のエンジン系
- **app_paths.py**: Phase 1をC#自己完結にした場合は `tests/test_app_paths.py` ごと削除候補
- **README.md 書き換え箇所**: 12行（配布終了の記述）、38行、108行、146行、155行（機能差の記述）、158行（ログの記述）。制限・運用セクションも更新
- **副次効果**: Windows CIのTk起動skip判定（runnerのTcl欠損workaround）が消え、test_matrixが安定化

## 5. リリース手順（各Phaseの締め・必須手順）

1. `app_config.py` の `VERSION` を更新 — **4セグメント形式**（例: `2.1.1.0`。ユーザー指定の形式。次の番号はユーザーに確認）
2. `winui/ImageToPDF.WinUI/MainWindow.xaml` のバージョン表示 `"v{VERSION}"` も更新 — **`build_winui.ps1:289` が整合チェックして不一致だとCIが落ちる**
3. push → CI全緑を確認（winui-buildのセルフテスト込み。**約4分+ビルド3分かかる**）
4. **CI緑を確認してから** タグ `v{VERSION}` をpush（緑前にタグを打たないこと — 過去に失敗が残る）
5. publish-releaseジョブの成功とRelease資産4点（EXE/SHA256SUMS/LICENSE/THIRD_PARTY_NOTICES.md）を確認
6. **日本語で**ユーザーに報告

## 6. 環境・デバッグの知見（短期で必要なもの）

- **ワーカートレース**: 環境変数 `IMAGETOPDF_WORKER_LOG=<path>` で `conversion_worker.py` が起動・プロトコル各段階をトレース出力（serve設定/stdin状態/読み取りバイト数/パース結果/emit）。パッケージEXEのデバッグで必須級
- **セルフテスト**: `ImageToPDF.exe --selftest-convert <画像> <PDF>` → 終了コード0/2で成功、タイムラインは `<出力>.selftest-log.txt`
- **sandbox制約（ローカルでできないこと）**: Tkの起動（X無し）/ PyInstallerビルド（libpython無し）/ release-assets.githubusercontent.com のダウンロード（ブロック）。→ **UIとEXEの実検証はWindows CIでのみ可能**
- **過去の教訓（守ること）**:
  - C#→ワーカーstdinは `StandardInput.BaseStream` に**UTF-8バイトを直書き**（StreamWriterはconsole codepage問題でGUIアプリでは使えない）
  - stdoutリーダーは **terminalメッセージ（completed/thumbnail/cancelled/error）が来るまでpendingエントリを保持**（progressで削除すると完成メッセージが届かずタイムアウトする — v2.1.0.1で実際に踏んだ）
  - ワーカー死亡チェックは `HasExited` をtry/catch(InvalidOperationException)で
  - PowerShellのバックティックエスケープはpython heredocで触ると壊れる → `edit_file` か行番号spliceで編集し、必ず `grep`/`repr()` で検証
  - 並列 `edit_file` は失敗が黙ることがある → 1個ずつ
  - `TaskCompletionSource` に `TrySetCanceled(Exception)` は無い
  - タグはCI緑の後のみ

## 7. 既知の仕様・制限（README記載・変更しない方針のもの）

- 自己更新機能なし（手動更新）
- ワーカー展開先 `%LOCALAPPDATA%\ImageToPDF\worker\<ビルドID>\` の旧バージョンは自動削除しない
- 画像前処理は逐次実行（巨大画像の同時展開を避ける）。PDF結合オブジェクトはメモリ保持
- Pillowの巨大画像保護（decompression bomb）は無効化しない
- 依存ライブラリ: img2pdf (LGPL) / pillow-heifバイナリwheel (GPLv2。THIRD_PARTY_NOTICES.md参照)。**新しいライブラリを足す場合は通知ファイルの更新が必要**

## 8. ユーザーの設定・文化

- **日本語**でコミュニケーション・ドキュメント・UI・エラーメッセージ
- ライセンスは **MIT**（ユーザーの明示的選択）
- バージョンは **4セグメント**（v2.1.0.1形式）
- スコープの大きな決定は **ask_user で確認**する文化
- 品質基準: ローカルでpytest+ruff全緑、CI全緑（winui-buildのセルフテスト込み）を必ず通す

## 9. 直近の履歴（文脈用・簡潔に）

- v2.1.0: Tk版の最終配布版（ワーカーは `--request` 一発モード）
- v2.1.0.1開発: WinUI版を常駐ワーカー+stdin/stdout JSONプロトコル化（高速化）。セルフテストが3回タイムアウト → トレース追加で「C#リーダーがprogressでpendingを削除していた」ことが判明 → 修正（`a37e685`）で全緑・リリース
- 2026-10-18: ユーザーが「Tkinter版の品質改善」を検討 → 実態調査（READMEでTk版は既に配布終了・WinUI版が正式）→ **機能移植後にTkinter削除する方針に決定**
