using System.Diagnostics;
using System.Globalization;
using System.IO;
using ImageToPDF.WinUI.Models;
using ImageToPDF.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Windows.ApplicationModel.DataTransfer;

namespace ImageToPDF.WinUI;

/// <summary>
/// v2.3.2 で追加した機能: 設定の保存、ドラッグ並べ替え、右クリックメニュー、
/// キーボード操作、用紙・配置・文書情報の入力欄。
/// </summary>
public sealed partial class MainWindow
{
    private AppSettings _settings = new();

    /// <summary>内部ドラッグ（並べ替え）中は Root_Drop を無視するための印です。</summary>
    private bool _reordering;

    // ---------------------------------------------------------------- 設定の保存・復元

    private void ApplySettings(AppSettings settings)
    {
        _settings = settings;
        SelectByTag(QualityBox, settings.Quality);
        SelectByTag(PaperBox, settings.PageSize);
        CustomWidthBox.Value = settings.CustomPageWidthMm;
        CustomHeightBox.Value = settings.CustomPageHeightMm;
        MarginBox.Value = settings.MarginMm;
        DpiBox.Value = settings.DefaultDpi;
        SelectByTag(BackgroundBox, settings.Background);
        AutoRotateBox.IsChecked = settings.AutoRotate;
        FitToPageBox.IsChecked = settings.FitToPage;
        SelectByTag(AlignmentBox, settings.Alignment);
        OpenAfterBox.IsChecked = settings.OpenAfter;
        OutlineBox.IsChecked = settings.Outline;
        CompactDpiBox.Value = settings.CompactDpi;
        JpegQualityBox.Value = settings.JpegQuality;
        AuthorBox.Text = settings.MetadataAuthor;
        FolderSortBox.SelectedIndex = settings.FolderSortIndex;
        if (settings.GridView)
        {
            ViewModeButton_Click(GridViewButton, new RoutedEventArgs());
        }

        UpdateQualityPanels();
        UpdatePagePanels();
    }

    private void CollectSettings()
    {
        _settings.Quality = SelectedTag(QualityBox) ?? "original";
        _settings.PageSize = SelectedTag(PaperBox) ?? string.Empty;
        _settings.CustomPageWidthMm = CustomWidthBox.Value;
        _settings.CustomPageHeightMm = CustomHeightBox.Value;
        _settings.MarginMm = MarginBox.Value;
        _settings.DefaultDpi = DpiBox.Value;
        _settings.Background = SelectedTag(BackgroundBox) ?? "white";
        _settings.AutoRotate = AutoRotateBox.IsChecked == true;
        _settings.FitToPage = FitToPageBox.IsChecked == true;
        _settings.Alignment = SelectedTag(AlignmentBox) ?? "center";
        _settings.OpenAfter = OpenAfterBox.IsChecked == true;
        _settings.Outline = OutlineBox.IsChecked == true;
        _settings.CompactDpi = (int)Math.Round(CompactDpiBox.Value);
        _settings.JpegQuality = (int)Math.Round(JpegQualityBox.Value);
        _settings.MetadataAuthor = AuthorBox.Text;
        _settings.FolderSortIndex = FolderSortBox.SelectedIndex;
        _settings.GridView = IsGridView;
        if (!string.IsNullOrWhiteSpace(OutputPathBox.Text))
        {
            _settings.LastOutputDirectory = Path.GetDirectoryName(OutputPathBox.Text) ?? string.Empty;
        }

        try
        {
            var size = AppWindow.Size;
            _settings.WindowWidth = size.Width;
            _settings.WindowHeight = size.Height;
        }
        catch (Exception)
        {
            // ウィンドウが既に閉じていれば前回の値を保ちます。
        }
    }

    private static void SelectByTag(ComboBox comboBox, string? tag)
    {
        for (var index = 0; index < comboBox.Items.Count; index++)
        {
            if (comboBox.Items[index] is ComboBoxItem item
                && string.Equals(item.Tag?.ToString() ?? string.Empty, tag ?? string.Empty, StringComparison.Ordinal))
            {
                comboBox.SelectedIndex = index;
                return;
            }
        }

        comboBox.SelectedIndex = 0;
    }

    // ---------------------------------------------------------------- 設定欄の表示切り替え

    private void QualityBox_SelectionChanged(object sender, SelectionChangedEventArgs e) => UpdateQualityPanels();

    private void PaperBox_SelectionChanged(object sender, SelectionChangedEventArgs e) => UpdatePagePanels();

    private void UpdateQualityPanels()
    {
        if (CompactPanel is null)
        {
            return;
        }

        CompactPanel.Visibility = SelectedTag(QualityBox) == "compact" ? Visibility.Visible : Visibility.Collapsed;
    }

    private void UpdatePagePanels()
    {
        if (CustomPagePanel is null || PagePlacementPanel is null)
        {
            return;
        }

        var tag = SelectedTag(PaperBox);
        CustomPagePanel.Visibility = tag == "Custom" ? Visibility.Visible : Visibility.Collapsed;
        PagePlacementPanel.Visibility = string.IsNullOrEmpty(tag) ? Visibility.Collapsed : Visibility.Visible;
    }

    /// <summary>変換リクエストに載せるオプションをUIから組み立てます。</summary>
    private WorkerOptions BuildWorkerOptions(double defaultDpi)
    {
        var pageSize = SelectedTag(PaperBox);
        var backgroundTag = SelectedTag(BackgroundBox) ?? "white";
        var background = backgroundTag switch
        {
            "black" => new[] { 0, 0, 0 },
            "gray" => new[] { 180, 180, 180 },
            _ => new[] { 255, 255, 255 },
        };
        var metadata = new Dictionary<string, string>();
        AddIfPresent(metadata, "title", TitleBox.Text);
        AddIfPresent(metadata, "author", AuthorBox.Text);
        AddIfPresent(metadata, "subject", SubjectBox.Text);
        AddIfPresent(metadata, "keywords", KeywordsBox.Text);
        return new WorkerOptions
        {
            Quality = SelectedTag(QualityBox) ?? "original",
            PageSize = string.IsNullOrWhiteSpace(pageSize) ? null : pageSize,
            CustomPageMm = pageSize == "Custom"
                ? new[] { CustomWidthBox.Value, CustomHeightBox.Value }
                : null,
            MarginMm = MarginBox.Value,
            Background = background,
            AutoRotate = AutoRotateBox.IsChecked ?? false,
            DefaultDpi = defaultDpi,
            CompactDpi = (int)Math.Round(CompactDpiBox.Value),
            JpegQuality = (int)Math.Round(JpegQualityBox.Value),
            FitToPage = FitToPageBox.IsChecked == true,
            Alignment = SelectedTag(AlignmentBox) ?? "center",
            Metadata = metadata.Count > 0 ? metadata : null,
            Outline = OutlineBox.IsChecked == true,
        };
    }

    private static void AddIfPresent(Dictionary<string, string> target, string key, string? value)
    {
        if (!string.IsNullOrWhiteSpace(value))
        {
            target[key] = value.Trim();
        }
    }

    /// <summary>用紙・軽量化の数値欄を変換前に検査します。問題があれば文言を返します。</summary>
    private string? ValidateExtraInputs()
    {
        if (SelectedTag(PaperBox) == "Custom")
        {
            foreach (var value in new[] { CustomWidthBox.Value, CustomHeightBox.Value })
            {
                if (!double.IsFinite(value) || value < 10 || value > 5000)
                {
                    return "カスタム用紙は10〜5000 mmの範囲で指定してください。";
                }
            }

            if (MarginBox.Value * 2 >= Math.Min(CustomWidthBox.Value, CustomHeightBox.Value))
            {
                return "余白がカスタム用紙のサイズを超えています。";
            }
        }

        if (SelectedTag(QualityBox) == "compact")
        {
            if (!double.IsFinite(CompactDpiBox.Value) || CompactDpiBox.Value < 36 || CompactDpiBox.Value > 600)
            {
                return "軽量化の最大DPIは36〜600で指定してください。";
            }

            if (!double.IsFinite(JpegQualityBox.Value) || JpegQualityBox.Value < 1 || JpegQualityBox.Value > 100)
            {
                return "JPEG品質は1〜100で指定してください。";
            }
        }

        return null;
    }

    private static string FormatBytes(long length) => length switch
    {
        < 1024 => $"{length} B",
        < 1024 * 1024 => $"{length / 1024d:0.#} KB",
        _ => $"{length / (1024d * 1024d):0.#} MB",
    };

    // ---------------------------------------------------------------- 一覧の操作

    private void ClearButton_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel.Items.Count == 0)
        {
            return;
        }

        ViewModel.Clear();
        AfterRemoval();
        AppLog.Info("一覧をすべて削除しました");
    }

    private void DeleteAccelerator_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        if (FilesList.SelectedItems.Count > 0)
        {
            RemoveButton_Click(sender, new RoutedEventArgs());
            args.Handled = true;
        }
    }

    private void SelectAllAccelerator_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        FilesList.SelectAll();
        args.Handled = true;
    }

    /// <summary>右クリックされた項目。共有 MenuFlyout には DataContext が渡らないため、ここで覚えます。</summary>
    private ImageEntry? _contextEntry;

    private void Item_RightTapped(object sender, RightTappedRoutedEventArgs e)
    {
        _contextEntry = (sender as FrameworkElement)?.DataContext as ImageEntry;
        // 右クリックした項目が未選択なら、その1件を選択してメニュー操作の対象にします。
        if (_contextEntry is not null && !FilesList.SelectedItems.Contains(_contextEntry))
        {
            FilesList.SelectedItems.Clear();
            FilesList.SelectedItems.Add(_contextEntry);
        }
    }

    private ImageEntry? ContextTarget(object sender)
    {
        if (_contextEntry is not null && ViewModel.Items.Contains(_contextEntry))
        {
            return _contextEntry;
        }

        return FilesList.SelectedItems.OfType<ImageEntry>().FirstOrDefault();
    }

    private void ShowInExplorer_Click(object sender, RoutedEventArgs e)
    {
        var entry = ContextTarget(sender);
        if (entry is null)
        {
            return;
        }

        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{entry.FullPath}\"") { UseShellExecute = false });
        }
        catch (Exception error)
        {
            AppLog.Warning($"エクスプローラーを開けませんでした: {error.GetType().Name}: {error.Message}");
        }
    }

    private void CopyPath_Click(object sender, RoutedEventArgs e)
    {
        var selected = FilesList.SelectedItems.OfType<ImageEntry>().Select(item => item.FullPath).ToList();
        if (selected.Count == 0 && ContextTarget(sender) is { } entry)
        {
            selected.Add(entry.FullPath);
        }

        if (selected.Count == 0)
        {
            return;
        }

        var package = new DataPackage();
        package.SetText(string.Join(Environment.NewLine, selected));
        Clipboard.SetContent(package);
        StatusText.Text = selected.Count == 1 ? "パスをコピーしました" : $"{selected.Count} 件のパスをコピーしました";
    }

    private void ReloadThumbnail_Click(object sender, RoutedEventArgs e)
    {
        var targets = FilesList.SelectedItems.OfType<ImageEntry>().ToList();
        if (targets.Count == 0 && ContextTarget(sender) is { } entry)
        {
            targets.Add(entry);
        }

        foreach (var target in targets)
        {
            target.Thumbnail = null;
            target.ThumbnailRequested = false;
            _thumbnailOrder.Remove(target);
            if (IsGridView)
            {
                target.ThumbnailRequested = true;
                _ = LoadTileThumbnailAsync(target);
            }
        }
    }

    private void RemoveAbove_Click(object sender, RoutedEventArgs e) => RemoveRelative(sender, above: true);

    private void RemoveBelow_Click(object sender, RoutedEventArgs e) => RemoveRelative(sender, above: false);

    private void RemoveRelative(object sender, bool above)
    {
        var anchor = ContextTarget(sender);
        if (anchor is null)
        {
            return;
        }

        ViewModel.RemoveRelativeTo(anchor, above);
        AfterRemoval();
    }

    /// <summary>削除系の操作後に、プレビューとサムネイルキャッシュを一覧に合わせます。</summary>
    private void AfterRemoval()
    {
        _previewGeneration++;
        PruneThumbnailCache();
        PreviewImage.Source = null;
        PreviewDetails.Text = string.Empty;
        PreviewHint.Text = "画像を選択するとプレビューを表示します";
        PreviewHint.Visibility = Visibility.Visible;
        UpdateListState();
    }

    // ---------------------------------------------------------------- ドラッグ並べ替え

    private void FilesList_DragItemsStarting(object sender, DragItemsStartingEventArgs e)
    {
        if (ViewModel.IsFiltered)
        {
            // 絞り込み中は表示順と全体順がずれるため、並べ替えを許可しません。
            e.Cancel = true;
            StatusText.Text = "検索中は並べ替えできません。検索欄を空にしてください";
            return;
        }

        _reordering = true;
    }

    private void FilesList_DragItemsCompleted(ListViewBase sender, DragItemsCompletedEventArgs args)
    {
        _reordering = false;
        if (args.DropResult != DataPackageOperation.Move)
        {
            return;
        }

        // ListView は VisibleItems（ObservableCollection）を直接並べ替えているので、
        // その順序を全体の順序（_items）へ書き戻します。
        var moved = args.Items.OfType<ImageEntry>().ToList();
        if (moved.Count == 0)
        {
            return;
        }

        var first = ViewModel.VisibleItems.IndexOf(moved[0]);
        if (first < 0)
        {
            return;
        }

        var targetIndex = ViewModel.VisibleItems.Take(first).Count(item => !moved.Contains(item));
        ViewModel.MoveTo(moved, targetIndex);
        RestoreSelection(moved);
        UpdateListState();
    }

    // ---------------------------------------------------------------- 画像情報（PDF入力）

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

    internal bool IsReordering => _reordering;
}
