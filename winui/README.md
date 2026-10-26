# WinUI 3 フロントエンド（正式版）

このWinUI 3版が唯一の画面です（v2.1.0 で正式版になり、v2.2.0.0 で従来のTkinter版を削除しました）。Windows 11 の標準的な操作感に合わせ、画像の並べ替え、プレビュー、ドラッグ＆ドロップ、PDF変換の設定を1つの画面にまとめています。

## 設計方針

- WinUI 3の標準コントロール、Windowsのシステムフォント、テーマに沿った色を使います。
- 画面は落ち着いた作業向けの構成にし、装飾用のグラデーションや不要なカードは使いません。
- 画像の一覧と変換の設定を同時に見られるようにします。エクスプローラーからの画像のドロップに対応します。

## 構成

- `MainWindow.xaml` / `.xaml.cs`: 画面、Windowsのファイル選択・保存ダイアログ。リスト表示とグリッド表示は同じListViewの `ItemsPanel`（ItemsStackPanel / ItemsWrapGrid）と `ItemTemplate` を `Root.Resources` から差し替えます。グリッドのサムネイルは `ContainerContentChanging` で画面に見えている分だけワーカーに要求し、LRU（128枚）を超えたら解放します。プレビュー下の画像情報（寸法・DPI取得元・元寸法・ICC）は `inspect` 要求で取得します。
- `ViewModels/MainViewModel.cs`: 画像一覧、検索による表示絞り込み、フォルダーの並び順、順番変更。
- `Services/ConversionWorkerService.cs`: 変換ワーカーを1つだけ起動して使い回します（stdinにJSON Linesリクエスト、stdoutからリクエストID付きの応答を受信）。進捗を画面へ流し、リクエスト単位で協調キャンセルを送ります。ワーカーは `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` のJob Objectに割り当てるためアプリが異常終了しても残らず、予期せず終了した場合は自動で再起動します。
- `Services/EmbeddedWorker.cs`: 単一EXEに埋め込んだ `ImageToPDFWorker.exe` を `%LOCALAPPDATA%\ImageToPDF\worker\<ビルドID>\` に展開します。
- `Services/AppLog.cs`: 起動、変換の開始・完了・キャンセル・失敗理由、スキップした画像、ワーカーの起動と終了を `%LOCALAPPDATA%\ImageToPDF\app.log` に記録します。1MB×3世代のローテーションで、Python側に依存せずC#だけで完結します。書き込みはベストエフォートで、失敗しても変換は止まりません。環境変数 `IMAGETOPDF_APP_LOG` で保存先を上書きできます（ビルド検証とデバッグ用）。
- `Services/UpdateChecker.cs`: GitHub Release の最新版を取得・解析し、6時間キャッシュ（`%LOCALAPPDATA%\ImageToPDF\update-cache.json`）します。キャッシュは改変されうるため、タグ名・アセット名・URL（ホストとパス）を厳しく検証します。`ParseLatestRelease` は通信を含まない純粋な処理なので、自己診断から検証できます。
- `Services/UpdateHttp.cs`: 更新用の共通 HttpClient。タイムアウトは呼び出し側の `CancellationTokenSource` が管理し、自動リダイレクトを無効にして1ホップごとに GitHub のホストを検査します。
- `Services/ReleaseSignature.cs`: `SHA256SUMS.txt` の署名（ECDSA P-256 / DER）を内蔵公開鍵で検証します。秘密鍵は `release` environment のシークレットにだけ置きます。
- `Services/UpdateDownloader.cs`: インストーラー・`SHA256SUMS.txt`・`SHA256SUMS.txt.sig` を `%LOCALAPPDATA%\ImageToPDF\updates\<タグ>\` へ取得し、署名 → タグ → サイズ・SHA-256 → PE形式（MZ）の順に確認してから起動します。署名やチェックサムが無いリリースは中止し、単体 EXE 版の更新経路はありません。
- `UpdateDialog.xaml` / `.cs`: バージョン表示から開く更新ダイアログ。現在のバージョン、確認時刻、リリースノート（Markdownを段落とリンクに変換）、進捗、更新ボタンを持ちます。開いたときに5分より古い情報なら取り直します。
- `Services/SelfTest.cs`: ビルド検証用の `--selftest-convert <入力画像> <出力PDF>` の処理です。変換に加えて、app.log に記録が残り1MBで繰り下げられることも確認します。通常の利用では使いません。
- `../../conversion_worker.py`: JSONリクエストを受け取り、JSON Linesで結果を返す変換ワーカーです。既存の `image_processor.py` を使います。引数なしで起動するとstdinが閉じるまでリクエストを処理し続け、`--request <ファイル>` は1リクエストだけ処理して終了します（テスト・デバッグ用）。操作は `convert`（既定）・`thumbnail`（`thumbnailSize` で寸法を指定、既定は640×480）・`inspect`（寸法・フレーム数・DPIの取得元・ICCの説明）の3つで、1リクエストにつき終端イベントを1つ返します。サムネイルもPillowで生成するため、Windowsがネイティブ表示できない形式にも対応します。

## 開発

Windows 10 / 11 x64 で、.NET 8 SDK、Visual Studio 2022 のMSBuild、Windows App SDKを復元できる環境、Python 3.10〜3.12 を用意します。

```powershell
python -m pip install -r requirements-dev.txt -r requirements-optional.txt
dotnet run --project .\winui\ImageToPDF.WinUI\ImageToPDF.WinUI.csproj -p:Platform=x64
```

`ImageToPDFWorker.exe` がないときは、リポジトリの `conversion_worker.py` を `python`（または環境変数 `PYTHON` で指定したPython）で実行します。これは開発用です。

## 単一EXEのビルド

PowerShellで次を実行します。

```powershell
.\build_winui.ps1
```

スクリプトは次の順に進みます。

1. Pythonのテスト、ruffのチェック、バージョンの確認。
2. PyInstallerで `dist\ImageToPDFWorker.exe` を作成し、変換を試します。
3. MSBuildでWinUI版を `PublishSingleFile` の self-contained として発行します。ワーカーはEXE内に埋め込まれます。
4. 発行されたファイルがEXE1つだけであることを確認します。
5. Inno Setup（`installer\ImageToPDF.iss`）で `dist\ImageToPDF-Setup-v<version>-Windows-x64.exe` と、`# tag:` 行を含む `dist\SHA256SUMS.txt` を作成します（署名 `SHA256SUMS.txt.sig` は Release 公開時にCIが追加します。詳細は [`RELEASING.md`](../RELEASING.md)）。
6. そのインストーラーを一時フォルダーへサイレント実行し、インストールされた `ImageToPDF.exe` で埋め込みワーカーによる日本語パスのPDF変換、`app.log` への記録と1MBローテーション、アップデート機能の自己診断（`--selftest-update`）、ウィンドウの起動と起動ログの記録、最後にアンインストーラー（`unins000.exe`）の実行を確認します（ログは `IMAGETOPDF_APP_LOG` で一時ファイルへ向けるため、実行機のログは汚しません）。

ビルドにはWindowsと Windows App SDK の復元が必要です。CIは `windows-latest` で同じスクリプトを実行します。

## 検証状況

このリポジトリのLinux環境では .NET SDK がないため、WinUI版のコンパイルやEXEの動作は確認できません。検証はWindows CIで行います。

- 正式版は、Windows CIで単一EXEの発行、埋め込みワーカーによる変換、一時フォルダーからの起動確認まで行うことを条件にします。
- 実機のWindows 11での手動確認（エクスプローラーからのドラッグ＆ドロップ、キャンセル、AVIF/HEIFのサムネイル、Unicodeパス、別端末での起動）は、リリース前の確認項目として残ります。

CI はWinUIのウィンドウ表示を確認しますが、画面の操作性や見た目の確認を代替するものではありません。

## 開発メモ（デバッグ・CI・C#の落とし穴）

### デバッグ用の環境変数とセルフテスト

- `IMAGETOPDF_WORKER_LOG=<path>`: `conversion_worker.py` が起動とプロトコル各段階のトレースを出力します。EXEだけで起きるハングの切り分けに使います。
- `IMAGETOPDF_APP_LOG=<path>`: `Services/AppLog.cs` の保存先を上書きします（デバッグとビルド検証用。実行機の `%LOCALAPPDATA%` を汚しません）。
- `IMAGETOPDF_DISABLE_UPDATE_CHECK=1`: 起動時のアップデート確認を止めます（ビルド検証・オフライン確認用）。バージョン表示からの手動確認は動きます。
- `ImageToPDF.exe --selftest-update <ログ>`: ネットワークを使わず、リリース応答の解析・バージョン比較・URL検証・一時鍵による署名検証・SHA-256照合・更新ダイアログの生成を確認します。終了コード0で成功、`update selftest ok` をログに書きます。
- `ImageToPDF.exe --selftest-convert <入力画像> <出力PDF>`: 終了コード0で成功。タイムラインは `<出力>.selftest-log.txt` に出ます。app.logの記録と1MBローテーションの確認もここで行います。

### CI（GitHub Actions）の運用

- 全体で約5〜7分（テスト6ジョブ → winui-build。セルフテスト込み）。
- `gh run watch <id> --exit-status` は途中で返ることがあるため、`gh run view <id> --json status,conclusion` のポーリングで完了を待つほうが確実です。
- ログ本体を取得できない環境では、`gh api repos/{owner}/{repo}/check-runs/{job_id}/annotations` で失敗詳細を読めます（`build_winui.ps1` が `::error title=...::` でannotationを出しているため）。
- matrixは fail-fast なので、1ジョブが落ちると残りは `cancelled` になります（`failure` と混同しないこと）。
- 再実行は「新しいコミットをpushする」のが確実です（`gh run rerun` は状況によって拒否されます）。
- タグはCIが緑になったことを確認してからpushします。緑の前に打つと失敗がReleaseの履歴に残ります。
- `publish-release` は `v*` タグの push だけで動き、`release` environment の承認を待ちます。`workflow_dispatch` ではビルド・テストのみで、Release は一切変更しません。同名タグの Release が既にある場合は上書きせず失敗します。

### C#（WinUI）で過去に踏んだ落とし穴

- ワーカーのstdinへは `StandardInput.BaseStream` に**UTF-8バイトを直書き**します（`StreamWriter` はGUIアプリでconsole codepageの問題を起こします）。
- stdoutリーダーは**terminalメッセージ（completed / thumbnail / inspect / cancelled / error）が来るまでpendingエントリを保持**します。progressで削除すると完成メッセージが届かずタイムアウトします（v2.1.0.1で実際に発生）。**operationを追加したら、terminal判定とswitchの2箇所を必ず更新**してください。
- ワーカーの死亡チェックは `HasExited` を `try/catch (InvalidOperationException)` で囲みます。
- `Environment.Is64Process` は存在しません（正しくは `Is64BitProcess`）。`UnhandledExceptionEventArgs` は `Microsoft.UI.Xaml` と `System` で名前が衝突するため**完全修飾**します。
- `TaskCompletionSource` に `TrySetCanceled(Exception)` はありません。
- .NET SDKが無い環境では `tree-sitter` + `tree-sitter-c-sharp` で構文エラーを検出できます（型・メンバー名の誤りは検出できないため、そこはCI頼みです）。
