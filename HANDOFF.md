# 引き継ぎ文書 — Tkinter→WinUI機能移植 → Tkinter削除（次チャットスレッド向け）

作成: 2026-10-18（v2.1.0.1 リリース直後）／更新: 2026-10-18（Phase 1〜4 実装・CI全緑・PR #5 作成後）
対象読者: 次スレッドの担当エージェント。まずこの文書を読んでから作業すること。

---

## 1. 現在の状態

- **Phase 1〜4（機能移植）は実装済み・CI全緑**（run [39106178218](https://github.com/burugou05-wq/PDF_conversion/actions/runs/39106178218)、HEAD `e10fd1f`）。残りは **Phase 5（Tkinter一式の削除）だけ**
- ブランチ `arena/7d2f6c7c-pdf-conversion`（`arena/a9ee149b-pdf-conversion` = v2.1.0.1 の先端をfast-forwardで取り込み、その上にPhase 1〜4を積んだ）
- バージョンは **2.1.1.0** に更新済み（`app_config.py` / `MainWindow.xaml` / `ImageToPDF.WinUI.csproj` / CHANGELOGの見出し）。**タグ `v2.1.1.0` はまだpushしていない**
- リリース待ちの判断: 実機Windowsでの画面確認（グリッド・DPI・画像情報・ログ）が済んでからタグをpushするのが安全（VERIFICATION.mdの「画面の操作」参照）
- 前のリリース: v2.1.0.1 https://github.com/burugou05-wq/PDF_conversion/releases/tag/v2.1.0.1
- ローカル: 110 passed / 5 skipped / ruff clean（sandboxはLinux・Tk表示不可のためTk UIテストはskip）
- GitHub上のPR: **#5（`arena/7d2f6c7c-pdf-conversion` → `main`、v2.1.1.0）を作成済み**。**#4（v2.1.0）は閉じた**（#4のコミットは#5の履歴に含まれるため内容は失われない。ブランチは削除していない）。次は #5 のレビュー／マージ

## 2. 次スレッドのミッション

> **「Tkinter版にあってWinUI版にない機能をWinUIへ段階的に追加し、揃ったらTkinterを消す」**

- Phase 1〜4は完了（下記4節）。**Phase 5（削除）だけが残っている**。実行前に「実機でグリッド・DPI・ログを確認できたか」をユーザーに確認すること
- **PR #5（v2.1.1.0 → main）のマージ**が次の作業。#4はクローズ済み
- v2.1.1.0のリリース（タグpush）がまだ。タグはCI緑の確認後にのみpushする

## 3. アーキテクチャ（ファイル地図）

```
WinUI 3版（正式）                          Tkinter版（旧・互換用／Phase 5で削除）
MainWindow.xaml(.cs)  UI本体               img2pdf_app.py  UI本体
MainViewModel.cs      状態管理             ui_theme.py     テーマ
Models/ImageEntry.cs  一覧の1件+サムネ     ↑ 直接import（ワーカー不要）
Services/AppLog.cs    app.logへの記録
Services/ConversionWorkerService.cs  通信窓口
Services/EmbeddedWorker.cs     EXE内蔵ワーカー自己抽出
Services/WorkerProtocol.cs     JSON境界のDTO
Services/SelfTest.cs/App.xaml.cs  ビルド検証モード
        │ JSON over stdin/stdout
conversion_worker.py  エンジンのJSONラッパー（convert / thumbnail / inspect）
        │ import
image_processor.py  ★変換エンジン本体（convert_to_pdf / inspect_image / make_thumbnail）
file_model.py       ファイルリスト・自然順ソート
app_config.py / app_paths.py  バージョン定数 / Tk版ログ保存先
cli.py              コマンドライン版（第3の入り口）
```

- ビルド: `build_winui.ps1`（ruff → バージョン整合チェック → PyInstallerでワーカー凍結[ConversionWorker.spec] → ワーカー単体テスト → dotnet publish単一EXE → 完成EXEのセルフテスト[app.logの記録とローテーション確認込み] → GUI起動テスト[起動ログ確認込み] → SHA256SUMS）
- CI: `.github/workflows/ci.yml`（テスト6ジョブ → winui-build → タグpushでpublish-release）
- ワーカーのプロトコル: 操作は `convert`（既定）/ `thumbnail`（`thumbnailSize` で寸法指定、既定640×480）/ `inspect`（寸法・フレーム数・DPIと取得元・ICC）。**1リクエストにつき終端イベントは1つ**（completed / thumbnail / inspect / cancelled / error）

## 4. Phase別の実装記録

### Phase 1: ログファイル（app.log）— 完了
- `Services/AppLog.cs`（新規）: `%LOCALAPPDATA%\ImageToPDF\app.log` へ UTF-8・BOMなしで追記。Tkinter版と同じ **1MB × 3世代**（`app.log.1`〜`app.log.3`）のローテーションをC#だけで実装（Python非依存 → Phase 5で `app_paths.py` を消せる）。書き込みはベストエフォートで例外を返さない
- 環境変数 **`IMAGETOPDF_APP_LOG`** で保存先を上書き可能（ワーカーの `IMAGETOPDF_WORKER_LOG` と同じ考え方）。`build_winui.ps1` はこれを使って、実行機のログを汚さずに「記録が残るか」「1MBで繰り下がるか」「GUI起動時の記録が残るか」を配布EXEで検証する
- 記録しているもの: 起動（バージョン・OS・bit）/終了、変換の開始（枚数・保存先・画質・用紙・余白・既定DPI・背景・自動回転・上書き）、完了（ページ数・保存先・所要時間・スキップ件数）、スキップ1件ずつ（パスと理由）、キャンセル、失敗（例外とスタックトレース）、既定DPIや余白などの入力エラー、画像追加の失敗、プレビュー/画像情報/サムネイルの取得失敗、ワーカーの起動・終了（exit code）・stderr（上限500行）・書き込み失敗・未完了リクエストの失敗、未処理例外と未観測タスク例外
- ローテーションのアルゴリズムはPython版と同じ挙動か、Pythonで同一ロジックを再現して確認済み（3行×400KBで `.1` へ繰り下がり、現ファイルは1MB以下）

### Phase 2: 既定DPI変更 — 完了
- Python側は既に対応済みだった（`conversion_worker.py` の `options_from_request` が `defaultDpi` を読む）
- C#: `WorkerOptions.DefaultDpi`（JSON名 `defaultDpi`、既定96）を追加。`MainWindow.xaml` に「DPI不明時の既定値」NumberBox（1〜10000、SpinButton付き）とエラー表示 `DpiErrorText`。範囲外は変換前に「DPI不明時の既定値は1〜10000で指定してください」で止め（Tkinter版・`ConversionOptions.validate` と同じ文言）、app.logにも残す
- 設定の永続化は**入れていない**（Tkinter版も永続化していなかったため。WinUI版には設定ファイル自体がない）。もし「設定を覚えてほしい」要望が出たら、それは両UIにとっての新機能として別途設計する

### Phase 3: ICC/DPI情報の詳細表示 — 完了
- ワーカーに **`inspect` 操作**を追加（`inspect_image` の戻り値をそのままJSONに）。範囲外の既定DPIは `options.validate()` で弾く
- **重要**: `inspect` を `ConversionWorkerService` の終端イベント一覧（`terminal` 判定とswitch）に追加済み。追加し忘れるとv2.1.0.1で踏んだ「pendingが消えずタイムアウト」を再発する
- 画面: プレビュー下に `PreviewDetails`（Tkinter版と同じ5行: ファイル名 / 幅×高さpx+フレーム数 / DPIと取得元 / 元寸法mm / ICC）。`IsTextSelectionEnabled=True` でコピー可能。既定DPIを変えると元寸法が変わるので引き直す
- 注意: CMYK→sRGB変換の検証資材（AGFLのArtifex SWOPプロファイルなど）は**絶対にコミットしない**（ローカルe2e専用）

### Phase 4: グリッド表示 — 完了
- 同じListViewの `ItemsPanel`（ItemsStackPanel ⇄ ItemsWrapGrid）と `ItemTemplate`（RowTemplate ⇄ TileTemplate）を `Root.Resources` から差し替える方式。選択・検索・並び替えボタンは両モードでそのまま動く
- ツールバーに「リスト」「グリッド」のToggleButton（どちらか一方だけが押された状態になる）。変換中は無効化
- サムネイルは `ContainerContentChanging`（タイルが画面に実現されたとき）に要求 → Tkinter版のページ送り（1ページ48枚・3列・前へ/次へ）は不要になった
- タイルの表示枠はTkinter版と同じ150×105。取得は2倍の300×210（高DPI対策）、`DecodePixelWidth=300`
- LRU: 最大128枚（Tkinter版は100枚）。**画面に実現されているタイルは追い出さない**（`ContainerFromItem` で判定）。一覧から削除した分は `PruneThumbnailCache` で即解放。失敗したタイルはアイコンのまま・再要求しない（Tkinter版の「読込失敗」相当）
- base64→BitmapImage は `DecodeBitmapAsync` に共通化（プレビューのフォールバックも同じ経路）

### Phase 5: Tkinter一式の削除（**残作業**）
- **削除**: `img2pdf_app.py` / `ui_theme.py` / `tests/test_ui.py` / `build.py` / `tests/test_build.py` / `ImageToPDF.spec`
- **残す**: `image_processor.py` / `conversion_worker.py` / `ConversionWorker.spec` / `cli.py` / `file_model.py`（cli.pyが使用）/ `tests/` のエンジン系
- **app_paths.py**: Phase 1をC#自己完結にしたので `tests/test_app_paths.py` ごと削除できる（`app_config.py` の `APP_DATA_DIRECTORY` / `PORTABLE_*` 定数を他に使うものが無いか確認すること。`build.py` が `PORTABLE_*` を使っているので、build.py削除とセットで）
- **README.md 書き換え箇所**: 12行（Tkinter版配布終了の記述）、38行（`img2pdf_app.py` からの起動）、構成セクションの `img2pdf_app.py, file_model.py, ui_theme.py` の行、`app_paths.py` の行、23行（Tk版GUIの動作環境）、制限・運用セクション
- **requirements-optional.txt**: `tkinterdnd2` はTk版専用なので削除候補（pillow-avif-plugin / pillow-heif はエンジンが使うので残す）
- **副次効果**: Windows CIのTk起動skip判定（runnerのTcl欠損workaround、`tests/test_ui.py` の `pytestmark`）が消え、test_matrixが安定化する
- CHANGELOGに「Tkinter版を削除」のセクションを書き、バージョンはユーザーに確認する（4セグメント形式）

## 5. リリース手順（必須手順）

1. `app_config.py` の `VERSION`（4セグメント形式、ユーザー指定）と、`MainWindow.xaml` の `Text="v{VERSION}"` と、`ImageToPDF.WinUI.csproj` の `<Version>` と、CHANGELOGの `## v{VERSION} ` 見出しを一致させる — **`build_winui.ps1` が app_config と XAML の整合をチェックして、不一致だとCIが落ちる**
2. push → CI全緑を確認（**約7分**: テスト6ジョブ + winui-build。セルフテスト込み）
3. **CI緑を確認してから** タグ `v{VERSION}` をpush（緑前にタグを打たないこと — 過去に失敗が残る）
4. publish-releaseジョブの成功とRelease資産4点（EXE / SHA256SUMS.txt / LICENSE / THIRD_PARTY_NOTICES.md）を確認
5. リリースノートは CHANGELOG の該当セクションから自動生成される（`awk 'index($0, "## v{VERSION} ") == 1'`）。見出しは必ず `## v{VERSION} ` + 半角スペース + タイトルの形にする
6. **日本語で**ユーザーに報告

## 6. 環境・デバッグの知見（重要）

- **CIログの取得方法**: このsandboxからは `gh run view --log` が使えない（`results-receiver.actions.githubusercontent.com` / `release-assets.githubusercontent.com` がブロックされている）。**代わりに `gh api repos/{owner}/{repo}/check-runs/{job_id}/annotations` でエラー内容を取れる**（`build_winui.ps1` が `::error title=...::` で失敗詳細をannotationに出しているため）。`--jq '.[].message' | tr '|' '\n' | grep "error CS"` のように使う
- **CIの監視方法**: `gh run watch <id> --exit-status` は**途中終了する**ことがある（実測47秒で返った）。`gh run view <id> --json status,conclusion` を `sleep 20` のループで回すこと。`gh run rerun` はこの環境では拒否される（「cannot be rerun; its workflow file may be broken」）ので、**再実行したいときは新しいコミットをpushする**。matrixは fail-fast なので、1ジョブが落ちると他は `cancelled` になる（`failure` と混同しないこと）
- **Windows CI の Tk テストが不安定な件（対処済み）**: `windows-latest, 3.11` で `tests/test_ui.py` が2回赤くなった。**アプリのコードではなくランナーの Tcl インストール不具合**。連鎖は `can't find package tkdnd` → アプリが plain-Tk フォールバックへ → 壊れかけのインタプリタを destroy した後の2つ目の生成が `Can't find a usable init.tcl` で失敗。同じコミットでも 3.10/3.12/ubuntu は緑で、前のrunでは 3.11 も緑だった（machine依存のフレーク）
  - 対処: `tests/test_ui.py` のモジュール読み込み時プローブを「plain Tk を1つ作って destroy → `TkinterDnD.Tk()` を作って destroy」という**起動シーケンスを真似る形**に変更し、`tk.TclError` ならモジュール全体をskip。`ImportError`/`RuntimeError`（tkinterdnd2未導入・非対応プラットフォーム）は従来どおりテストを走らせる
  - **各テスト前にプローブする autouse fixture は逆効果だった**（余計なインタプリタ生成/破棄が増え、失敗が最後のテストから最初のテストへ前倒しになった）。プローブはモジュール読み込み時の1回だけにする
  - `test_gui_falls_back_when_tkdnd_library_fails` だけは「わざとtkdndを壊す」テストなので、`tk.TclError` を捕まえて `pytest.skip` する個別ガードも残している
  - この判定一式は Phase 5 で `tests/test_ui.py` ごと消える
- **C#の構文チェック**: sandboxに .NET SDK は無いが、`.venv` に `tree-sitter` + `tree-sitter-c-sharp` を入れれば構文エラーを検出できる（型・メンバー名の誤りは検出できないので、それはCI頼み）
- **ワーカートレース**: 環境変数 `IMAGETOPDF_WORKER_LOG=<path>` で `conversion_worker.py` が起動・プロトコル各段階をトレース出力
- **アプリログのトレース**: 環境変数 `IMAGETOPDF_APP_LOG=<path>` で `AppLog.cs` の保存先を上書きできる（デバッグとCI検証用）
- **セルフテスト**: `ImageToPDF.exe --selftest-convert <画像> <PDF>` → 終了コード0で成功。タイムラインは `<出力>.selftest-log.txt`、app.logの検証とローテーション確認もここで行う
- **sandbox制約（ローカルでできないこと）**: Tkの起動（X無し）/ .NET SDK（コンパイル不可）/ PyInstallerビルド（libpython無し）/ GitHubのログ・リリース資産のダウンロード。→ **UIとEXEの実検証はWindows CIでのみ可能**
- **ローカルのvenv**: `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt -r requirements-optional.txt`（システムのpipはPEP 668で弾かれる）
- **過去の教訓（守ること）**:
  - C#→ワーカーstdinは `StandardInput.BaseStream` に**UTF-8バイトを直書き**（StreamWriterはconsole codepage問題でGUIアプリでは使えない）
  - stdoutリーダーは **terminalメッセージ（completed/thumbnail/inspect/cancelled/error）が来るまでpendingエントリを保持**（progressで削除すると完成メッセージが届かずタイムアウトする — v2.1.0.1で実際に踏んだ）。**新しいoperationを足したら必ずこの2箇所（terminal判定とswitch）に追加する**
  - ワーカー死亡チェックは `HasExited` をtry/catch(InvalidOperationException)で
  - `Environment.Is64Process` は存在しない（正しくは `Is64BitProcess`）。`UnhandledExceptionEventArgs` は `Microsoft.UI.Xaml` と `System` で名前が衝突するので**完全修飾**する
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
- 設定の永続化（前回値を覚える）はTkinter版にもWinUI版にも無い

## 8. ユーザーの設定・文化

- **日本語**でコミュニケーション・ドキュメント・UI・エラーメッセージ
- ライセンスは **MIT**（ユーザーの明示的選択）
- バージョンは **4セグメント**（v2.1.0.1 / v2.1.1.0 形式）
- スコープの大きな決定は **ask_user で確認**する文化（Phaseの範囲・バージョン番号・PRの扱いなどは確認した）
- 品質基準: ローカルでpytest+ruff全緑、CI全緑（winui-buildのセルフテスト込み）を必ず通す

## 9. 直近の履歴（文脈用・簡潔に）

- v2.1.0: Tk版の最終配布版（ワーカーは `--request` 一発モード）
- v2.1.0.1開発: WinUI版を常駐ワーカー+stdin/stdout JSONプロトコル化（高速化）。セルフテストが3回タイムアウト → トレース追加で「C#リーダーがprogressでpendingを削除していた」ことが判明 → 修正（`a37e685`）で全緑・リリース
- 2026-10-18: ユーザーが「Tkinter版の品質改善」を検討 → 実態調査（READMEでTk版は既に配布終了・WinUI版が正式）→ **機能移植後にTkinter削除する方針に決定**
- 2026-10-18（このスレッド）: Phase 1（app.log）→ CIが `UnhandledExceptionEventArgs` の名前衝突を検出 → 修正。Phase 2（既定DPI）+ Phase 3（inspect/画像情報）→ CIが `Environment.Is64Process`（存在しない名前）を検出 → `Is64BitProcess` に修正して**CI全緑**（配布EXEでのapp.log記録・1MBローテーション・GUI起動ログの確認まで成功）。Phase 4（グリッド表示・サムネイルLRU・ワーカーの `thumbnailSize`）を実装。バージョンを2.1.1.0に上げ、CHANGELOG/README/VERIFICATIONを更新
- 2026-10-18（このスレッド・続き）: Phase 4 込みのpushで `windows-latest, 3.11` のTkテストがランナーのTcl不具合で2回赤くなった（`2220580` のautouseプローブは逆効果だったので撤回）→ プローブを起動シーケンス模倣型にして `e10fd1f` で**CI全緑**（run 39106178218）。**PR #5 を作成、PR #4 をクローズ**（ユーザー方針どおり）。タグ `v2.1.1.0` は実機確認後にpushする方針で**未pushのまま**
