# WinUI 3 フロントエンド（正式版）

v2.1.0 から、このWinUI 3版が正式な画面です。Windows 11 の標準的な操作感に合わせ、画像の並べ替え、プレビュー、ドラッグ＆ドロップ、PDF変換の設定を1つの画面にまとめています。

## 設計方針

- WinUI 3の標準コントロール、Windowsのシステムフォント、テーマに沿った色を使います。
- 画面は落ち着いた作業向けの構成にし、装飾用のグラデーションや不要なカードは使いません。
- 画像の一覧と変換の設定を同時に見られるようにします。エクスプローラーからの画像のドロップに対応します。

## 構成

- `MainWindow.xaml` / `.xaml.cs`: 画面、Windowsのファイル選択・保存ダイアログ。
- `ViewModels/MainViewModel.cs`: 画像一覧、検索による表示絞り込み、フォルダーの並び順、順番変更。
- `Services/ConversionWorkerService.cs`: 変換ワーカーを1つだけ起動して使い回します（stdinにJSON Linesリクエスト、stdoutからリクエストID付きの応答を受信）。進捗を画面へ流し、リクエスト単位で協調キャンセルを送ります。ワーカーは `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` のJob Objectに割り当てるためアプリが異常終了しても残らず、予期せず終了した場合は自動で再起動します。
- `Services/EmbeddedWorker.cs`: 単一EXEに埋め込んだ `ImageToPDFWorker.exe` を `%LOCALAPPDATA%\ImageToPDF\worker\<ビルドID>\` に展開します。
- `Services/SelfTest.cs`: ビルド検証用の `--selftest-convert <入力画像> <出力PDF>` の処理です。通常の利用では使いません。
- `../../conversion_worker.py`: JSONリクエストを受け取り、JSON Linesで結果を返す変換ワーカーです。既存の `image_processor.py` を使います。引数なしで起動するとstdinが閉じるまでリクエストを処理し続け、`--request <ファイル>` は1リクエストだけ処理して終了します（テスト・デバッグ用）。サムネイルもPillowで生成するため、Windowsがネイティブ表示できない形式にも対応します。

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
5. `dist\ImageToPDF-v<version>-Windows-x64.exe` と `dist\SHA256SUMS.txt` を作成します。
6. そのEXEを単独で一時フォルダーにコピーし、埋め込みワーカーによる日本語パスのPDF変換と、ウィンドウの起動を確認します。

ビルドにはWindowsと Windows App SDK の復元が必要です。CIは `windows-latest` で同じスクリプトを実行します。

## 検証状況

このリポジトリのLinux環境では .NET SDK がないため、WinUI版のコンパイルやEXEの動作は確認できません。検証はWindows CIで行います。

- v2.1.0 の正式版は、Windows CIで単一EXEの発行、埋め込みワーカーによる変換、一時フォルダーからの起動確認まで行うことを条件にします。
- 実機のWindows 11での手動確認（エクスプローラーからのドラッグ＆ドロップ、キャンセル、AVIF/HEIFのサムネイル、Unicodeパス、別端末での起動）は、リリース前の確認項目として残ります。

CI はWinUIのウィンドウ表示を確認しますが、画面の操作性や見た目の確認を代替するものではありません。
