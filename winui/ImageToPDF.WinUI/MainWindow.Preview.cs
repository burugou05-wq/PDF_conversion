using System.Globalization;
using ImageToPDF.WinUI.Models;
using ImageToPDF.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Storage;
using Windows.Storage.Streams;

namespace ImageToPDF.WinUI;

public sealed partial class MainWindow
{
    private bool IsGridView => GridViewButton.IsChecked == true;

    /// <summary>右ペインの「変換設定」と「プレビュー &amp; 情報」タブを切り替えます。</summary>
    private void InspectorTabButton_Click(object sender, RoutedEventArgs e)
    {
        var showPreview = ReferenceEquals(sender, PreviewTabButton);
        SettingsTabButton.IsChecked = !showPreview;
        PreviewTabButton.IsChecked = showPreview;
        SettingsScroll.Visibility = showPreview ? Visibility.Collapsed : Visibility.Visible;
        PreviewPanel.Visibility = showPreview ? Visibility.Visible : Visibility.Collapsed;
    }

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
                : "1件選択するとプレビューを表示します";
            PreviewHint.Visibility = Visibility.Visible;
            return;
        }

        var selected = selection[0];
        PreviewImage.Source = null;
        if (selected.IsPdf)
        {
            // PDFはプレビュー画像を作らず、ページ数と用紙寸法だけを inspect で表示します。
            PreviewHint.Text = "PDFはプレビューを表示しません";
            PreviewHint.Visibility = Visibility.Visible;
            _ = LoadPreviewDetailsAsync(selected, generation);
            return;
        }

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

            PreviewDetails.Text = info.IsPdf ? FormatPdfDetails(selected, info) : FormatDetails(selected, info, dpiError);
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

    private static string FormatPdfDetails(ImageEntry selected, WorkerMessage info)
    {
        return string.Join(
            Environment.NewLine,
            selected.Name,
            $"PDF: {info.FrameCount} ページ",
            $"用紙: {info.PageWidthMm.ToString("0.0", CultureInfo.InvariantCulture)}"
                + $" × {info.PageHeightMm.ToString("0.0", CultureInfo.InvariantCulture)} mm",
            "ページをそのまま結合します（用紙・画質の設定は適用されません）");
    }

    private static string FormatDpi(double value) =>
        double.IsFinite(value) && value > 0
            ? value.ToString("0.###", CultureInfo.InvariantCulture)
            : "-";

    private static string FormatMillimetres(int pixels, double dpi) =>
        double.IsFinite(dpi) && dpi > 0
            ? (pixels / dpi * 25.4).ToString("0.0", CultureInfo.InvariantCulture)
            : "-";
}
