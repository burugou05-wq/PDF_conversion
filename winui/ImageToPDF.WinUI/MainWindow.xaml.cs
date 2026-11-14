using System.Diagnostics;
using System.Globalization;
using System.IO;
using ImageToPDF.WinUI.Models;
using ImageToPDF.WinUI.Services;
using ImageToPDF.WinUI.ViewModels;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage.Pickers;
using WinRT.Interop;

namespace ImageToPDF.WinUI;

public sealed partial class MainWindow : Window
{
    /// <summary>DPI欄が範囲外のときに使う値（image_processor.DEFAULT_DPI と同じ 96）。</summary>
    private const double DefaultDpiFallback = 96.0;

    /// <summary>リスト表示とグリッド表示のテンプレートキー（Root の Resources に定義）。</summary>
    private const string ListPanelKey = "ListPanel";
    private const string GridPanelKey = "GridPanel";
    private const string RowTemplateKey = "RowTemplate";
    private const string TileTemplateKey = "TileTemplate";

    /// <summary>タイルの表示枠は150×105。高DPIでも滲まないよう2倍の寸法で取得します。</summary>
    private static readonly int[] TileThumbnailSize = { 300, 210 };

    /// <summary>メモリを守るため、Tkinter版と同じくサムネイルをLRUで追い出します。</summary>
    private const int ThumbnailCacheLimit = 128;

    private readonly ConversionWorkerService _worker = new();
    private readonly List<ImageEntry> _thumbnailOrder = new();
    private UpdateCheckResult? _updateCheck;
    private CancellationTokenSource? _conversionCancellation;
    private int _previewGeneration;
    private bool _settingsReady;
    private bool _closing;
    private readonly bool _isUiSelfTest;
    private UpdateDialog? _versionDialog;

    public MainViewModel ViewModel { get; } = new();

    public MainWindow() : this(false) { }

    internal MainWindow(bool uiSelfTest)
    {
        _isUiSelfTest = uiSelfTest;
        InitializeComponent();
        VersionText.Text = $"v{AppLog.ApplicationVersion.Split('+')[0]}";
        var settings = uiSelfTest ? new AppSettings() : AppSettings.Load();
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(WindowNative.GetWindowHandle(this));
        AppWindow.GetFromWindowId(windowId).Resize(
            new Windows.Graphics.SizeInt32(settings.WindowWidth, settings.WindowHeight));
        ApplySettings(settings);
        InitializePresets();
        UpdateListState();
        Closed += (_, _) =>
        {
            // 終了処理中のワーカー停止を「失敗」としてログに残さないための印です。
            _closing = true;
            _conversionCancellation?.Cancel();
            _worker.Dispose();
            if (!_isUiSelfTest)
            {
                CollectSettings();
                _settings.Save();
            }
            AppLog.Info("アプリを終了しました");
        };
        _settingsReady = true;
        // 起動時の更新確認は画面の表示を待たせません（結果だけバッジに反映します）。
        if (!uiSelfTest) _ = CheckForUpdatesAutomaticallyAsync();
    }

    /// <summary>
    /// バージョン表示のタップで更新ダイアログを開きます。
    /// ダイアログは開いたときに最新の状態を取り直すため、ここでは前回の結果を渡すだけです。
    /// </summary>
    private async void VersionButton_Click(object sender, RoutedEventArgs e)
    {
        if (_versionDialog is not null) return;
        var check = _isUiSelfTest ? new UpdateCheckResult(null, DateTimeOffset.UtcNow, null) : _updateCheck;
        var dialog = new UpdateDialog(check) { XamlRoot = Root.XamlRoot };
        _versionDialog = dialog;
        try
        {
            await dialog.ShowAsync();
            ApplyUpdateIndicator(dialog.Result);
        }
        finally
        {
            _versionDialog = null;
        }
    }

    /// <summary>起動時に一度だけ最新リリースを確認します（6時間キャッシュ）。</summary>
    private async Task CheckForUpdatesAutomaticallyAsync()
    {
        if (UpdateChecker.AutomaticCheckDisabled())
        {
            AppLog.Info("アップデートの自動確認は無効になっています");
            return;
        }

        try
        {
            var result = await UpdateChecker.FindLatestAsync(
                AppLog.NumericVersion, forceRefresh: false, CancellationToken.None);
            if (_closing)
            {
                return;
            }

            ApplyUpdateIndicator(result);
            // 更新直後の再起動ではインストーラー終了まで少し間があるため、数秒待ってから一時ファイルを掃除します。
            await Task.Delay(TimeSpan.FromSeconds(3));
            if (!_closing)
            {
                UpdateDownloader.CleanUpCompletedDownloads();
            }
        }
        catch (Exception error)
        {
            // 更新確認の失敗でアプリの動作を妨げません。
            AppLog.Warning($"アップデートの自動確認に失敗しました: {error.GetType().Name}: {error.Message}");
        }
    }

    /// <summary>新しい版があるときだけ青い点を出します。</summary>
    private void ApplyUpdateIndicator(UpdateCheckResult? result)
    {
        _updateCheck = result;
        if (result?.Release is { } release)
        {
            UpdateBadge.Visibility = Visibility.Visible;
            ToolTipService.SetToolTip(
                VersionButton, $"新しいバージョン {release.TagName} があります。タップして更新できます");
            AutomationProperties.SetName(
                VersionButton, $"新しいバージョン {release.TagName} があります。タップして更新できます");
            AppLog.Info($"新しいバージョンがあります: {release.TagName}（現在 v{AppLog.ApplicationVersion}）");
            return;
        }

        UpdateBadge.Visibility = Visibility.Collapsed;
        var tooltip = result is { Succeeded: false }
            ? "バージョンを確認できませんでした。タップして再試行できます"
            : "バージョン情報とアップデートを確認します";
        ToolTipService.SetToolTip(VersionButton, tooltip);
        AutomationProperties.SetName(VersionButton, tooltip);
    }

    private async void AddFilesButton_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker();
        foreach (var extension in MainViewModel.SupportedExtensions)
        {
            picker.FileTypeFilter.Add(extension);
        }

        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        var files = await picker.PickMultipleFilesAsync();
        if (files is not null)
        {
            AddPaths(files.Select(file => file.Path));
        }
    }

    private async void AddFolderButton_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        picker.FileTypeFilter.Add("*");
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        var folder = await picker.PickSingleFolderAsync();
        if (folder is not null)
        {
            AddPaths(new[] { folder.Path });
        }
    }

    private async void BrowseOutputButton_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
            SuggestedFileName = string.IsNullOrWhiteSpace(OutputPathBox.Text)
                ? "output"
                : Path.GetFileNameWithoutExtension(OutputPathBox.Text),
        };
        picker.FileTypeChoices.Add("PDF file", new List<string> { ".pdf" });
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        var file = await picker.PickSaveFileAsync();
        if (file is not null)
        {
            OutputPathBox.Text = file.Path;
        }
    }

    private void AddPaths(IEnumerable<string> paths)
    {
        try
        {
            var added = ViewModel.AddPaths(paths, GetFolderSortMode());
            if (string.IsNullOrWhiteSpace(OutputPathBox.Text) && ViewModel.Items.Count > 0)
            {
                var directory = Directory.Exists(_settings.LastOutputDirectory)
                    ? _settings.LastOutputDirectory
                    : ViewModel.Items[0].ParentDirectory;
                OutputPathBox.Text = Path.Combine(directory, "output.pdf");
            }

            var duplicates = ViewModel.LastDuplicateCount;
            StatusText.Text = added == 0
                ? (duplicates > 0 ? $"{duplicates} 件はすでに一覧にあります" : "追加できるファイルがありません")
                : (duplicates > 0 ? $"{added} 件追加しました（{duplicates} 件は追加済み）" : $"{added} 件追加しました");
            AppLog.Info($"ファイルを追加しました: {added} 件（一覧 {ViewModel.Items.Count} 件）");
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException)
        {
            StatusText.Text = $"画像の追加に失敗しました: {error.Message}";
            AppLog.Warning($"画像の追加に失敗しました: {error.GetType().Name}: {error.Message}");
        }

        UpdateListState();
    }

    private FolderSortMode GetFolderSortMode() => FolderSortBox.SelectedIndex switch
    {
        1 => FolderSortMode.Number,
        2 => FolderSortMode.Date,
        _ => FolderSortMode.Name,
    };

    private void SearchBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        ViewModel.SetSearchText(SearchBox.Text);
        UpdateListState();
    }

    private void MoveTopButton_Click(object sender, RoutedEventArgs e) => MoveSelection(toTop: true);

    private void MoveBottomButton_Click(object sender, RoutedEventArgs e) => MoveSelection(toTop: false);

    private void MoveUpButton_Click(object sender, RoutedEventArgs e) => MoveSelection(direction: -1);

    private void MoveDownButton_Click(object sender, RoutedEventArgs e) => MoveSelection(direction: 1);

    private void MoveSelection(bool? toTop = null, int direction = 0)
    {
        var selected = FilesList.SelectedItems.OfType<ImageEntry>().ToArray();
        if (selected.Length == 0)
        {
            return;
        }

        if (toTop.HasValue)
        {
            ViewModel.MoveToBoundary(selected, toTop.Value);
        }
        else
        {
            ViewModel.Move(selected, direction);
        }

        RestoreSelection(selected);
        UpdateListState();
    }

    private void RemoveButton_Click(object sender, RoutedEventArgs e)
    {
        ViewModel.Remove(FilesList.SelectedItems.OfType<ImageEntry>().ToArray());
        AfterRemoval();
    }

    private void UpdateListState()
    {
        CountText.Text = ViewModel.VisibleItems.Count == ViewModel.Items.Count
            ? $"{ViewModel.Items.Count} 件"
            : $"{ViewModel.VisibleItems.Count} / {ViewModel.Items.Count} 件";
        EmptyState.Visibility = ViewModel.VisibleItems.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        EmptyStateText.Text = ViewModel.Items.Count == 0
            ? "画像やPDFを追加するか、ここへドラッグしてください"
            : "検索条件に一致するファイルがありません";
        var pdfs = ViewModel.Items.Count(item => item.IsPdf);
        PdfInputNoticeText.Text = $"PDF {pdfs} 件のページは、用紙・画質・配置を変更せず結合します。";
        PdfInputNoticeText.Visibility = pdfs > 0 ? Visibility.Visible : Visibility.Collapsed;
        var available = _conversionCancellation is null;
        ConvertButton.IsEnabled = available && ViewModel.Items.Count > 0;
        RemoveButton.IsEnabled = available && FilesList.SelectedItems.Count > 0;
        ClearButton.IsEnabled = available && ViewModel.Items.Count > 0;
        MoveTopButton.IsEnabled = available && FilesList.SelectedItems.Count > 0;
        MoveUpButton.IsEnabled = available && FilesList.SelectedItems.Count > 0;
        MoveDownButton.IsEnabled = available && FilesList.SelectedItems.Count > 0;
        MoveBottomButton.IsEnabled = available && FilesList.SelectedItems.Count > 0;
    }

    private void RestoreSelection(IEnumerable<ImageEntry> selected)
    {
        FilesList.SelectedItems.Clear();
        foreach (var item in selected.Where(ViewModel.VisibleItems.Contains))
        {
            FilesList.SelectedItems.Add(item);
        }
    }

    /// <summary>リスト表示とグリッド表示を切り替えます（Tkinter版のラジオボタン相当）。</summary>
    private void ViewModeButton_Click(object sender, RoutedEventArgs e)
    {
        var grid = ReferenceEquals(sender, GridViewButton);
        GridViewButton.IsChecked = grid;
        ListViewButton.IsChecked = !grid;
        FilesList.ItemsPanel = (ItemsPanelTemplate)Root.Resources[grid ? GridPanelKey : ListPanelKey];
        FilesList.ItemTemplate = (DataTemplate)Root.Resources[grid ? TileTemplateKey : RowTemplateKey];
        AppLog.Info(
            $"表示を{(grid ? "グリッド" : "リスト")}に切り替えました"
            + $"（表示 {ViewModel.VisibleItems.Count} / {ViewModel.Items.Count} 件）");
    }

    private async void ConvertButton_Click(object sender, RoutedEventArgs e)
    {
        if (_conversionCancellation is not null)
        {
            return;
        }

        if (ViewModel.Items.Count == 0)
        {
            await ShowMessageAsync("ファイルがありません", "先に画像やPDFを追加してください。");
            return;
        }

        if (string.IsNullOrWhiteSpace(OutputPathBox.Text))
        {
            await ShowMessageAsync("保存先がありません", "PDFの保存先を指定してください。");
            return;
        }

        string outputPath;
        try
        {
            outputPath = Path.GetFullPath(OutputPathBox.Text.Trim());
        }
        catch (Exception error) when (error is ArgumentException or NotSupportedException or PathTooLongException)
        {
            AppLog.Warning($"保存先を解決できませんでした: {OutputPathBox.Text}: {error.Message}");
            await ShowMessageAsync("保存先を確認してください", error.Message);
            return;
        }

        if (!string.Equals(Path.GetExtension(outputPath), ".pdf", StringComparison.OrdinalIgnoreCase))
        {
            AppLog.Warning($"保存先の拡張子が .pdf ではありません: {outputPath}");
            await ShowMessageAsync("保存先を確認してください", "保存先の拡張子は .pdf にしてください。");
            return;
        }

        var overwrite = false;
        if (File.Exists(outputPath))
        {
            var confirmation = new ContentDialog
            {
                Title = "既存のPDFを上書きしますか？",
                Content = outputPath,
                PrimaryButtonText = "上書き",
                CloseButtonText = "キャンセル",
                DefaultButton = ContentDialogButton.Close,
                XamlRoot = Root.XamlRoot,
            };
            if (await confirmation.ShowAsync() != ContentDialogResult.Primary)
            {
                return;
            }

            overwrite = true;
        }

        if (!double.IsFinite(MarginBox.Value) || MarginBox.Value < 0 || MarginBox.Value > 100)
        {
            AppLog.Warning(
                $"余白が範囲外です: {MarginBox.Value.ToString(CultureInfo.InvariantCulture)}（0〜100 mm が必要）");
            await ShowMessageAsync("余白を確認してください", "余白は0〜100 mmの範囲で指定してください。");
            return;
        }

        var (defaultDpi, dpiError) = ReadDefaultDpi();
        if (dpiError is not null)
        {
            AppLog.Warning($"既定DPIが範囲外です: {DpiBox.Value.ToString(CultureInfo.InvariantCulture)}");
            await ShowMessageAsync("DPIを確認してください", dpiError);
            return;
        }

        var extraError = ValidateExtraInputs();
        if (extraError is not null)
        {
            AppLog.Warning($"設定が範囲外です: {extraError}");
            await ShowMessageAsync("設定を確認してください", extraError);
            return;
        }

        var options = BuildWorkerOptions(defaultDpi);
        var pageSize = options.PageSize;
        var quality = options.Quality;
        var backgroundName = SelectedTag(BackgroundBox) switch
        {
            "black" => "黒",
            "gray" => "グレー",
            _ => "白",
        };
        var request = new WorkerRequest
        {
            ImagePaths = ViewModel.Items.Select(item => item.FullPath).ToArray(),
            OutputPath = outputPath,
            Overwrite = overwrite,
            Options = options,
        };
        // 変換のたびに設定を保存し、クラッシュしても直前の値が残るようにします。
        CollectSettings();
        _settings.Save();

        var stopwatch = Stopwatch.StartNew();
        AppLog.Info(
            $"変換を開始します: {request.ImagePaths.Count} 件 → {outputPath}"
            + $" (画質={quality}, 用紙={(string.IsNullOrWhiteSpace(pageSize) ? "元のサイズ" : pageSize)},"
            + $" 余白={MarginBox.Value.ToString("0.##", CultureInfo.InvariantCulture)} mm,"
            + $" 既定DPI={FormatDpi(defaultDpi)}, 背景={backgroundName},"
            + $" 自動回転={(AutoRotateBox.IsChecked == true ? "あり" : "なし")}, 上書き={(overwrite ? "あり" : "なし")})");

        var cancellation = new CancellationTokenSource();
        _conversionCancellation = cancellation;
        SetBusy(true);
        ConversionProgress.Value = 0;
        StatusText.Text = "変換を開始しています…";
        var progress = new Progress<WorkerMessage>(message =>
        {
            if (message.Type == "progress"
                && ReferenceEquals(_conversionCancellation, cancellation)
                && !cancellation.IsCancellationRequested
                && !_closing)
            {
                ConversionProgress.Value = message.Percent;
                StatusText.Text = $"変換中… {message.Percent}%";
            }
        });

        try
        {
            var result = await _worker.RunAsync(
                request, progress, cancellation.Token);
            stopwatch.Stop();
            if (_closing)
            {
                return;
            }

            ConversionProgress.Value = 100;
            StatusText.Text = $"完了: {result.PageCount} ページ / {FormatBytes(result.OutputSize)} を保存しました";
            AppLog.Info(
                $"変換が完了しました: {result.PageCount} ページ → {result.OutputPath}"
                + $" ({ElapsedText(stopwatch)}, スキップ {result.Skipped.Count} 件)");
            foreach (var skipped in result.Skipped)
            {
                AppLog.Warning($"変換をスキップしました: {skipped.Path} — {skipped.Reason}");
            }

            if (result.Skipped.Count > 0)
            {
                var skippedSummary = string.Join(
                    Environment.NewLine,
                    result.Skipped.Take(10).Select(item => $"{Path.GetFileName(item.Path)}: {item.Reason}"));
                if (result.Skipped.Count > 10)
                {
                    skippedSummary += Environment.NewLine + $"ほか {result.Skipped.Count - 10} 件";
                }

                await ShowMessageAsync(
                    "一部のファイルをスキップしました",
                    $"{result.PageCount} ページを保存しました。\n\n{skippedSummary}");
            }

            if (OpenAfterBox.IsChecked == true)
            {
                Process.Start(new ProcessStartInfo(result.OutputPath) { UseShellExecute = true });
            }
        }
        catch (OperationCanceledException)
        {
            stopwatch.Stop();
            if (!_closing)
            {
                StatusText.Text = "変換をキャンセルしました";
            }

            AppLog.Info($"変換をキャンセルしました: {outputPath} ({ElapsedText(stopwatch)})");
        }
        catch (Exception error)
        {
            stopwatch.Stop();
            if (_closing)
            {
                return;
            }

            StatusText.Text = "変換に失敗しました";
            AppLog.Error($"変換に失敗しました: {outputPath} ({ElapsedText(stopwatch)})", error);
            await ShowMessageAsync("変換に失敗しました", error.Message);
        }
        finally
        {
            cancellation.Dispose();
            _conversionCancellation = null;
            if (!_closing)
            {
                SetBusy(false);
            }
        }
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        if (_conversionCancellation is null || _conversionCancellation.IsCancellationRequested)
        {
            return;
        }

        CancelButton.IsEnabled = false;
        StatusText.Text = "キャンセル中… 処理の終了を待っています";
        _conversionCancellation.Cancel();
    }

    private void SetBusy(bool isBusy)
    {
        UpdatePresetButtons();
        PresetManageButton.IsEnabled = !isBusy;
        BrowseOutputButton.IsEnabled = !isBusy;
        FileOptionsButton.IsEnabled = !isBusy;
        VersionButton.IsEnabled = !isBusy;
        AddFilesButton.IsEnabled = !isBusy;
        AddFolderButton.IsEnabled = !isBusy;
        SearchBox.IsEnabled = !isBusy;
        FolderSortBox.IsEnabled = !isBusy;
        FilesList.IsEnabled = !isBusy;
        ListViewButton.IsEnabled = !isBusy;
        GridViewButton.IsEnabled = !isBusy;
        MoveTopButton.IsEnabled = !isBusy && FilesList.SelectedItems.Count > 0;
        MoveUpButton.IsEnabled = !isBusy && FilesList.SelectedItems.Count > 0;
        MoveDownButton.IsEnabled = !isBusy && FilesList.SelectedItems.Count > 0;
        MoveBottomButton.IsEnabled = !isBusy && FilesList.SelectedItems.Count > 0;
        RemoveButton.IsEnabled = !isBusy && FilesList.SelectedItems.Count > 0;
        ClearButton.IsEnabled = !isBusy && ViewModel.Items.Count > 0;
        QualityBox.IsEnabled = !isBusy;
        CompactDpiBox.IsEnabled = !isBusy;
        JpegQualityBox.IsEnabled = !isBusy;
        CustomWidthBox.IsEnabled = !isBusy;
        CustomHeightBox.IsEnabled = !isBusy;
        FitToPageBox.IsEnabled = !isBusy;
        AlignmentBox.IsEnabled = !isBusy;
        OutlineBox.IsEnabled = !isBusy;
        MetadataExpander.IsEnabled = !isBusy;
        PaperBox.IsEnabled = !isBusy;
        MarginBox.IsEnabled = !isBusy;
        DpiBox.IsEnabled = !isBusy;
        BackgroundBox.IsEnabled = !isBusy;
        AutoRotateBox.IsEnabled = !isBusy;
        OpenAfterBox.IsEnabled = !isBusy;
        OutputPathBox.IsEnabled = !isBusy;
        ConvertButton.IsEnabled = !isBusy && ViewModel.Items.Count > 0;
        CancelButton.IsEnabled = isBusy;
    }

    private async Task ShowMessageAsync(string title, string content)
    {
        var dialog = new ContentDialog
        {
            Title = title,
            Content = content,
            CloseButtonText = "閉じる",
            XamlRoot = Root.XamlRoot,
        };
        await dialog.ShowAsync();
    }

    private static string? SelectedTag(ComboBox comboBox) =>
        (comboBox.SelectedItem as ComboBoxItem)?.Tag?.ToString();

    private static string ElapsedText(Stopwatch stopwatch) =>
        stopwatch.Elapsed.TotalSeconds.ToString("0.0", CultureInfo.InvariantCulture) + " 秒";

    private void Root_DragOver(object sender, DragEventArgs e)
    {
        if (_conversionCancellation is not null)
        {
            e.AcceptedOperation = DataPackageOperation.None;
            return;
        }

        if (_reordering)
        {
            return;
        }

        e.AcceptedOperation = e.DataView.Contains(StandardDataFormats.StorageItems)
            ? DataPackageOperation.Copy
            : DataPackageOperation.None;
    }

    private async void Root_Drop(object sender, DragEventArgs e)
    {
        if (_conversionCancellation is not null
            || _reordering || !e.DataView.Contains(StandardDataFormats.StorageItems))
        {
            // 一覧内のドラッグ並べ替えは ListView が処理します。
            return;
        }

        try
        {
            var items = await e.DataView.GetStorageItemsAsync();
            AddPaths(items.Select(item => item.Path));
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            AppLog.Warning($"ドロップした項目を読み込めません: {error.GetType().Name}: {error.Message}");
            await ShowMessageAsync("ドロップした項目を読み込めません", error.Message);
        }
    }
}
