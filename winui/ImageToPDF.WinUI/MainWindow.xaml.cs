using System.Diagnostics;
using System.Globalization;
using System.IO;
using ImageToPDF.WinUI.Models;
using ImageToPDF.WinUI.Services;
using ImageToPDF.WinUI.ViewModels;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.Storage.Streams;
using WinRT.Interop;

namespace ImageToPDF.WinUI;

public sealed partial class MainWindow : Window
{
    private static readonly string[] ImageExtensions =
    {
        ".jpg", ".jpeg", ".png", ".avif", ".heic", ".heif", ".webp", ".bmp", ".gif", ".tif", ".tiff",
    };

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
    private CancellationTokenSource? _conversionCancellation;
    private int _previewGeneration;
    private bool _settingsReady;
    private bool _closing;

    public MainViewModel ViewModel { get; } = new();

    public MainWindow()
    {
        InitializeComponent();
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(WindowNative.GetWindowHandle(this));
        AppWindow.GetFromWindowId(windowId).Resize(new Windows.Graphics.SizeInt32(1320, 860));
        UpdateListState();
        Closed += (_, _) =>
        {
            // 終了処理中のワーカー停止を「失敗」としてログに残さないための印です。
            _closing = true;
            _conversionCancellation?.Cancel();
            _worker.Dispose();
            AppLog.Info("アプリを終了しました");
        };
        _settingsReady = true;
    }

    private async void AddFilesButton_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker();
        foreach (var extension in ImageExtensions)
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
                OutputPathBox.Text = Path.Combine(ViewModel.Items[0].ParentDirectory, "output.pdf");
            }

            StatusText.Text = added == 0 ? "追加できる画像がありません" : $"{added} 枚追加しました";
            AppLog.Info($"画像を追加しました: {added} 枚（一覧 {ViewModel.Items.Count} 枚）");
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
        // 読み込み中のプレビュー・画像情報が削除後の一覧に混ざらないよう世代を進めます。
        _previewGeneration++;
        PruneThumbnailCache();
        PreviewImage.Source = null;
        PreviewDetails.Text = string.Empty;
        PreviewHint.Text = "画像を選択するとプレビューを表示します";
        PreviewHint.Visibility = Visibility.Visible;
        UpdateListState();
    }

    private void UpdateListState()
    {
        CountText.Text = ViewModel.VisibleItems.Count == ViewModel.Items.Count
            ? $"{ViewModel.Items.Count} 枚"
            : $"{ViewModel.VisibleItems.Count} / {ViewModel.Items.Count} 枚";
        EmptyState.Visibility = ViewModel.VisibleItems.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        EmptyStateText.Text = ViewModel.Items.Count == 0
            ? "画像を追加するか、ここへドラッグしてください"
            : "検索条件に一致する画像がありません";
        ConvertButton.IsEnabled = ViewModel.Items.Count > 0;
        RemoveButton.IsEnabled = FilesList.SelectedItems.Count > 0;
        MoveTopButton.IsEnabled = FilesList.SelectedItems.Count > 0;
        MoveUpButton.IsEnabled = FilesList.SelectedItems.Count > 0;
        MoveDownButton.IsEnabled = FilesList.SelectedItems.Count > 0;
        MoveBottomButton.IsEnabled = FilesList.SelectedItems.Count > 0;
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
            + $"（表示 {ViewModel.VisibleItems.Count} / {ViewModel.Items.Count} 枚）");
    }

    private bool IsGridView => GridViewButton.IsChecked == true;

    /// <summary>
    /// タイルが画面に実現されたときにサムネイルを要求します。Tkinter版のページ単位の
    /// 描画の代わりに、WinUIの仮想化に合わせて必要な分だけ取得します。
    /// </summary>
    private void FilesList_ContainerContentChanging(
        ListViewBase sender, ContainerContentChangingEventArgs args)
    {
        if (args.InRecycleQueue || !_settingsReady || !IsGridView)
        {
            return;
        }

        if (args.Item is not ImageEntry entry || entry.ThumbnailRequested)
        {
            return;
        }

        entry.ThumbnailRequested = true;
        _ = LoadTileThumbnailAsync(entry);
    }

    private async Task LoadTileThumbnailAsync(ImageEntry entry)
    {
        try
        {
            var message = await _worker.RunAsync(
                new WorkerRequest
                {
                    Operation = "thumbnail",
                    ImagePaths = new[] { entry.FullPath },
                    ThumbnailSize = TileThumbnailSize,
                },
                progress: null,
                CancellationToken.None);
            var bitmap = await DecodeBitmapAsync(message.Data, TileThumbnailSize[0]);
            if (_closing)
            {
                return;
            }

            entry.Thumbnail = bitmap;
            TouchThumbnailCache(entry);
        }
        catch (Exception error)
        {
            // 失敗したタイルはアイコンのままにし、再要求はしません（Tkinter版の「読込失敗」相当）。
            if (!_closing)
            {
                AppLog.Warning(
                    $"サムネイルを取得できませんでした: {entry.FullPath}"
                    + $": {error.GetType().Name}: {error.Message}");
            }
        }
    }

    /// <summary>新しい順に並べ替え、上限を超えたサムネイルを追い出します（LRU）。</summary>
    private void TouchThumbnailCache(ImageEntry entry)
    {
        _thumbnailOrder.Remove(entry);
        _thumbnailOrder.Insert(0, entry);
        while (_thumbnailOrder.Count > ThumbnailCacheLimit)
        {
            var oldest = _thumbnailOrder[_thumbnailOrder.Count - 1];
            _thumbnailOrder.RemoveAt(_thumbnailOrder.Count - 1);
            if (FilesList.ContainerFromItem(oldest) is not null)
            {
                // まだ画面に出ているタイルは消さず、いちばん新しい扱いに戻します。
                _thumbnailOrder.Insert(0, oldest);
                break;
            }

            oldest.Thumbnail = null;
            oldest.ThumbnailRequested = false;
        }
    }

    /// <summary>一覧から外れた画像のサムネイルをLRUから落とし、メモリを解放します。</summary>
    private void PruneThumbnailCache()
    {
        var remaining = new HashSet<ImageEntry>(ViewModel.Items);
        _thumbnailOrder.RemoveAll(entry => !remaining.Contains(entry));
    }

    /// <summary>ワーカーが返したbase64画像をBitmapImageにします。</summary>
    private static async Task<BitmapImage> DecodeBitmapAsync(string base64, int decodePixelWidth)
    {
        var bytes = Convert.FromBase64String(base64);
        using var stream = new InMemoryRandomAccessStream();
        using (var writer = new DataWriter(stream))
        {
            writer.WriteBytes(bytes);
            await writer.StoreAsync();
            await writer.FlushAsync();
            writer.DetachStream();
        }

        stream.Seek(0);
        var bitmap = new BitmapImage { DecodePixelWidth = decodePixelWidth };
        await bitmap.SetSourceAsync(stream);
        return bitmap;
    }

    private async void FilesList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        UpdateListState();
        var generation = ++_previewGeneration;
        var selection = FilesList.SelectedItems.OfType<ImageEntry>().ToArray();
        if (selection.Length != 1)
        {
            PreviewImage.Source = null;
            PreviewDetails.Text = string.Empty;
            PreviewHint.Text = selection.Length == 0
                ? "画像を選択するとプレビューを表示します"
                : "1枚選択するとプレビューを表示します";
            PreviewHint.Visibility = Visibility.Visible;
            return;
        }

        var selected = selection[0];
        PreviewImage.Source = null;
        PreviewHint.Text = "プレビューを読み込み中…";
        PreviewHint.Visibility = Visibility.Visible;
        // 寸法・DPI・ICCはワーカーの inspect で取得します（プレビュー画像とは別リクエスト）。
        _ = LoadPreviewDetailsAsync(selected, generation);
        try
        {
            var file = await StorageFile.GetFileFromPathAsync(selected.FullPath);
            using var stream = await file.OpenAsync(FileAccessMode.Read);
            var bitmap = new BitmapImage { DecodePixelWidth = 640 };
            await bitmap.SetSourceAsync(stream);
            if (generation != _previewGeneration)
            {
                return;
            }

            PreviewImage.Source = bitmap;
            PreviewHint.Visibility = Visibility.Collapsed;
        }
        catch (Exception)
        {
            try
            {
                var preview = await _worker.RunAsync(
                    new WorkerRequest
                    {
                        Operation = "thumbnail",
                        ImagePaths = new[] { selected.FullPath },
                    },
                    progress: null,
                    CancellationToken.None);
                if (generation != _previewGeneration)
                {
                    return;
                }

                var bitmap = await DecodeBitmapAsync(preview.Data, 640);
                if (generation == _previewGeneration)
                {
                    PreviewImage.Source = bitmap;
                    PreviewHint.Visibility = Visibility.Collapsed;
                }
            }
            catch (Exception error)
            {
                AppLog.Warning(
                    $"プレビューを表示できませんでした: {selected.FullPath}: {error.GetType().Name}: {error.Message}");
                if (generation == _previewGeneration)
                {
                    PreviewImage.Source = null;
                    PreviewHint.Text = "この形式のプレビューを表示できません";
                    PreviewHint.Visibility = Visibility.Visible;
                }
            }
        }
    }

    /// <summary>
    /// 選択した画像の寸法・DPI（取得元）・元寸法・ICCをワーカーの inspect で取得して表示します。
    /// Tkinter版のプレビュー下と同じ項目です。
    /// </summary>
    private async Task LoadPreviewDetailsAsync(ImageEntry selected, int generation)
    {
        var (defaultDpi, dpiError) = ReadDefaultDpi();
        PreviewDetails.Text = dpiError ?? "画像情報を読み込み中…";
        try
        {
            var info = await _worker.RunAsync(
                new WorkerRequest
                {
                    Operation = "inspect",
                    ImagePaths = new[] { selected.FullPath },
                    Options = new WorkerOptions { DefaultDpi = defaultDpi },
                },
                progress: null,
                CancellationToken.None);
            if (_closing || generation != _previewGeneration)
            {
                return;
            }

            PreviewDetails.Text = FormatDetails(selected, info, dpiError);
        }
        catch (Exception error)
        {
            if (_closing || generation != _previewGeneration)
            {
                return;
            }

            PreviewDetails.Text = dpiError ?? $"画像情報を取得できません: {error.Message}";
            AppLog.Warning(
                $"画像情報を取得できませんでした: {selected.FullPath}"
                + $": {error.GetType().Name}: {error.Message}");
        }
    }

    /// <summary>DPI欄の値を読みます。範囲外のときは既定値とTkinter版と同じエラー文言を返します。</summary>
    private (double Dpi, string? Error) ReadDefaultDpi()
    {
        var value = DpiBox.Value;
        if (!double.IsFinite(value) || value < 1 || value > 10000)
        {
            return (DefaultDpiFallback, "DPI不明時の既定値は1〜10000で指定してください");
        }

        return (value, null);
    }

    private void UpdateDpiError()
    {
        var (_, error) = ReadDefaultDpi();
        DpiErrorText.Text = error ?? string.Empty;
        DpiErrorText.Visibility = error is null ? Visibility.Collapsed : Visibility.Visible;
    }

    private void DpiBox_ValueChanged(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (!_settingsReady)
        {
            // InitializeComponent の途中でXAMLが初期値をセットしたときの通知です。
            return;
        }

        UpdateDpiError();
        // 元寸法(mm)は既定DPIに依存するため、Tkinter版と同じく表示を引き直します。
        var selection = FilesList.SelectedItems.OfType<ImageEntry>().ToArray();
        if (selection.Length == 1)
        {
            _ = LoadPreviewDetailsAsync(selection[0], _previewGeneration);
        }
    }

    private static string FormatDetails(ImageEntry selected, WorkerMessage info, string? dpiError)
    {
        var lines = new List<string>
        {
            selected.Name,
            $"{info.Width}×{info.Height}px"
                + (info.FrameCount > 1 ? $" / {info.FrameCount}フレーム" : string.Empty),
            $"DPI: {FormatDpi(info.DpiHorizontal)} × {FormatDpi(info.DpiVertical)}"
                + $"（{info.DpiSource}）",
            $"元寸法: {FormatMillimetres(info.Width, info.DpiHorizontal)}"
                + $" × {FormatMillimetres(info.Height, info.DpiVertical)} mm",
            $"ICC: {info.IccProfile}",
        };
        if (dpiError is not null)
        {
            lines.Add(dpiError);
        }

        return string.Join(Environment.NewLine, lines);
    }

    private static string FormatDpi(double value) =>
        double.IsFinite(value) && value > 0
            ? value.ToString("0.###", CultureInfo.InvariantCulture)
            : "-";

    private static string FormatMillimetres(int pixels, double dpi) =>
        double.IsFinite(dpi) && dpi > 0
            ? (pixels / dpi * 25.4).ToString("0.0", CultureInfo.InvariantCulture)
            : "-";

    private async void ConvertButton_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel.Items.Count == 0)
        {
            await ShowMessageAsync("画像がありません", "先に画像を追加してください。");
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

        var pageSize = SelectedTag(PaperBox);
        var quality = SelectedTag(QualityBox) ?? "original";
        var backgroundTag = SelectedTag(BackgroundBox) ?? "white";
        var background = backgroundTag switch
        {
            "black" => new[] { 0, 0, 0 },
            "gray" => new[] { 180, 180, 180 },
            _ => new[] { 255, 255, 255 },
        };
        var backgroundName = backgroundTag switch
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
            Options = new WorkerOptions
            {
                Quality = quality,
                PageSize = string.IsNullOrWhiteSpace(pageSize) ? null : pageSize,
                MarginMm = MarginBox.Value,
                Background = background,
                AutoRotate = AutoRotateBox.IsChecked ?? false,
                DefaultDpi = defaultDpi,
            },
        };

        var stopwatch = Stopwatch.StartNew();
        AppLog.Info(
            $"変換を開始します: {request.ImagePaths.Count} 枚 → {outputPath}"
            + $" (画質={quality}, 用紙={(string.IsNullOrWhiteSpace(pageSize) ? "元のサイズ" : pageSize)},"
            + $" 余白={MarginBox.Value.ToString("0.##", CultureInfo.InvariantCulture)} mm,"
            + $" 既定DPI={FormatDpi(defaultDpi)}, 背景={backgroundName},"
            + $" 自動回転={(AutoRotateBox.IsChecked == true ? "あり" : "なし")}, 上書き={(overwrite ? "あり" : "なし")})");

        _conversionCancellation = new CancellationTokenSource();
        SetBusy(true);
        ConversionProgress.Value = 0;
        StatusText.Text = "変換を開始しています…";
        var progress = new Progress<WorkerMessage>(message =>
        {
            if (message.Type == "progress")
            {
                ConversionProgress.Value = message.Percent;
                StatusText.Text = $"変換中… {message.Percent}%";
            }
        });

        try
        {
            var result = await _worker.RunAsync(
                request, progress, _conversionCancellation.Token);
            stopwatch.Stop();
            ConversionProgress.Value = 100;
            StatusText.Text = $"完了: {result.PageCount} ページを保存しました";
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
                    "一部の画像をスキップしました",
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
            StatusText.Text = "変換をキャンセルしました";
            AppLog.Info($"変換をキャンセルしました: {outputPath} ({ElapsedText(stopwatch)})");
        }
        catch (Exception error)
        {
            stopwatch.Stop();
            StatusText.Text = "変換に失敗しました";
            AppLog.Error($"変換に失敗しました: {outputPath} ({ElapsedText(stopwatch)})", error);
            await ShowMessageAsync("変換に失敗しました", error.Message);
        }
        finally
        {
            _conversionCancellation.Dispose();
            _conversionCancellation = null;
            SetBusy(false);
        }
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e) => _conversionCancellation?.Cancel();

    private void SetBusy(bool isBusy)
    {
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
        QualityBox.IsEnabled = !isBusy;
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
        e.AcceptedOperation = e.DataView.Contains(StandardDataFormats.StorageItems)
            ? DataPackageOperation.Copy
            : DataPackageOperation.None;
    }

    private async void Root_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
        {
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
