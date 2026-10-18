using System.Diagnostics;
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

    private readonly ConversionWorkerService _worker = new();
    private CancellationTokenSource? _conversionCancellation;
    private int _previewGeneration;

    public MainViewModel ViewModel { get; } = new();

    public MainWindow()
    {
        InitializeComponent();
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(WindowNative.GetWindowHandle(this));
        AppWindow.GetFromWindowId(windowId).Resize(new Windows.Graphics.SizeInt32(1320, 860));
        UpdateListState();
        Closed += (_, _) =>
        {
            _conversionCancellation?.Cancel();
            _worker.Dispose();
        };
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
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException)
        {
            StatusText.Text = $"画像の追加に失敗しました: {error.Message}";
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
        PreviewImage.Source = null;
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

    private async void FilesList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        UpdateListState();
        var generation = ++_previewGeneration;
        var selection = FilesList.SelectedItems.OfType<ImageEntry>().ToArray();
        if (selection.Length != 1)
        {
            PreviewImage.Source = null;
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

                var bytes = Convert.FromBase64String(preview.Data);
                using var stream = new InMemoryRandomAccessStream();
                using (var writer = new DataWriter(stream))
                {
                    writer.WriteBytes(bytes);
                    await writer.StoreAsync();
                    await writer.FlushAsync();
                    writer.DetachStream();
                }

                stream.Seek(0);
                var bitmap = new BitmapImage { DecodePixelWidth = 640 };
                await bitmap.SetSourceAsync(stream);
                if (generation == _previewGeneration)
                {
                    PreviewImage.Source = bitmap;
                    PreviewHint.Visibility = Visibility.Collapsed;
                }
            }
            catch (Exception)
            {
                if (generation == _previewGeneration)
                {
                    PreviewImage.Source = null;
                    PreviewHint.Text = "この形式のプレビューを表示できません";
                    PreviewHint.Visibility = Visibility.Visible;
                }
            }
        }
    }

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
            await ShowMessageAsync("保存先を確認してください", error.Message);
            return;
        }

        if (!string.Equals(Path.GetExtension(outputPath), ".pdf", StringComparison.OrdinalIgnoreCase))
        {
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
            await ShowMessageAsync("余白を確認してください", "余白は0〜100 mmの範囲で指定してください。");
            return;
        }

        var pageSize = SelectedTag(PaperBox);
        var quality = SelectedTag(QualityBox) ?? "original";
        var background = SelectedTag(BackgroundBox) switch
        {
            "black" => new[] { 0, 0, 0 },
            "gray" => new[] { 180, 180, 180 },
            _ => new[] { 255, 255, 255 },
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
            },
        };

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
            ConversionProgress.Value = 100;
            StatusText.Text = $"完了: {result.PageCount} ページを保存しました";
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
            StatusText.Text = "変換をキャンセルしました";
        }
        catch (Exception error)
        {
            StatusText.Text = "変換に失敗しました";
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
        MoveTopButton.IsEnabled = !isBusy && FilesList.SelectedItems.Count > 0;
        MoveUpButton.IsEnabled = !isBusy && FilesList.SelectedItems.Count > 0;
        MoveDownButton.IsEnabled = !isBusy && FilesList.SelectedItems.Count > 0;
        MoveBottomButton.IsEnabled = !isBusy && FilesList.SelectedItems.Count > 0;
        RemoveButton.IsEnabled = !isBusy && FilesList.SelectedItems.Count > 0;
        QualityBox.IsEnabled = !isBusy;
        PaperBox.IsEnabled = !isBusy;
        MarginBox.IsEnabled = !isBusy;
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
            await ShowMessageAsync("ドロップした項目を読み込めません", error.Message);
        }
    }
}
