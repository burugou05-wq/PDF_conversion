using System.IO;
using System.Text;
using ImageToPDF.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using Microsoft.UI.Xaml.Controls;
using Windows.Foundation;

namespace ImageToPDF.WinUI;

public sealed partial class MainWindow
{
    /// <summary>Exercise the real window, including the version button's Click event, without user settings or network access.</summary>
    internal async Task<int> RunUiSelfTestAsync(string reportPath)
    {
        var log = new StringBuilder();
        var fixture = reportPath + ".input.pdf";
        void Check(bool value, string description)
        {
            if (!value) throw new InvalidOperationException(description);
            log.AppendLine("PASS " + description);
        }

        try
        {
            await WaitForUiAsync(() => Root.IsLoaded, "Window did not load.");
            var version = "v" + AppLog.ApplicationVersion.Split('+')[0];
            Check(VersionText.Text == version, "Visible version matches the release assembly.");
            Check(ImageExtensions.Contains(".pdf"), "The file picker accepts PDF inputs.");

            PresetBox.SelectedIndex = 2;
            await LayoutSettledAsync();
            Check(SelectedTag(QualityBox) == "compact" && CompactDpiBox.Value == 120
                && JpegQualityBox.Value == 75 && MarginBox.Value == 5,
                "Selecting the email preset updates the existing conversion controls.");
            PresetManageButton.Flyout.ShowAt(PresetManageButton);
            await LayoutSettledAsync();
            Check(SavePresetButton.IsEnabled && !OverwritePresetButton.IsEnabled && !DeletePresetButton.IsEnabled,
                "Preset management is available and protects the selected built-in preset.");
            PresetManageButton.Flyout.Hide();

            File.WriteAllText(fixture, "%PDF-1.4\n");
            ViewModel.AddPaths(new[] { fixture }, ViewModels.FolderSortMode.Name);
            UpdateListState();
            Check(CountText.Text == "1 件" && PdfInputNoticeText.Visibility == Visibility.Visible,
                "PDF inputs update the file count and the settings applicability notice.");

            _conversionCancellation = new CancellationTokenSource();
            SetBusy(true);
            Check(!BrowseOutputButton.IsEnabled && !PresetManageButton.IsEnabled
                && !FileOptionsButton.IsEnabled && !ConvertButton.IsEnabled && !VersionButton.IsEnabled,
                "Conversion locks file, preset, output and update actions.");
            _conversionCancellation.Dispose();
            _conversionCancellation = null;
            SetBusy(false);
            Check(BrowseOutputButton.IsEnabled && PresetManageButton.IsEnabled && ConvertButton.IsEnabled,
                "Finishing conversion restores the actions.");

            BasicSettingsExpander.IsExpanded = true;
            LayoutSettingsExpander.IsExpanded = true;
            MetadataExpander.IsExpanded = true;
            AdvancedSettingsExpander.IsExpanded = true;
            SelectByTag(PaperBox, "Custom");
            foreach (var (width, height) in new[] { (1320, 860), (1000, 720), (900, 680) })
            {
                var scale = Root.XamlRoot.RasterizationScale;
                AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(width * scale), (int)(height * scale)));
                await LayoutSettledAsync();
                Check(IsInsideRoot(ExportArea) && IsInsideRoot(ConvertButton) && IsInsideRoot(OutputPathBox)
                    && IsInsideRoot(VersionButton), $"Save controls and tappable version stay visible at {width}x{height}.");
                Check(SettingsScroll.ScrollableHeight > 0 && FilesList.ActualHeight > 0,
                    $"Expanded settings scroll independently of the file list at {width}x{height}.");
                var left = SettingsScroll.TransformToVisual(Root).TransformPoint(new Point());
                foreach (var box in new FrameworkElement[] { CustomWidthBox, CustomHeightBox, CompactDpiBox, JpegQualityBox, DpiBox })
                {
                    var position = box.TransformToVisual(Root).TransformPoint(new Point());
                    Check(position.X >= left.X - 1 && position.X + box.ActualWidth <= left.X + SettingsScroll.ActualWidth + 1,
                        $"{box.Name} fits the settings width at {width}x{height}.");
                }
            }

            var update = new UpdateRelease(new Version(9, 0, 0), "v9.0.0", "Test release", null,
                UpdateChecker.ReleasesPageUrl, null, null, 0, null, null);
            ApplyUpdateIndicator(new UpdateCheckResult(update, DateTimeOffset.UtcNow, null));
            Check(UpdateBadge.Visibility == Visibility.Visible
                && AutomationProperties.GetName(VersionButton).Contains("v9.0.0")
                && !AutomationProperties.GetName(VersionButton).Contains("vv"), "Update badge and version label remain correct.");
            ApplyUpdateIndicator(new UpdateCheckResult(null, DateTimeOffset.UtcNow, null));

            var peer = new ButtonAutomationPeer(VersionButton);
            var invoke = peer.GetPattern(PatternInterface.Invoke) as IInvokeProvider
                ?? throw new InvalidOperationException("The version button does not support Invoke.");
            invoke.Invoke();
            await WaitForUiAsync(() => _versionDialog?.IsLoaded == true, "Tapping the version did not open the update dialog.");
            Check((_versionDialog!.FindName("CurrentVersionText") as TextBlock)?.Text == "現在のバージョン: " + version,
                "Invoking the real version button opens the dialog with the correct version.");
            _versionDialog.Hide();
            await WaitForUiAsync(() => _versionDialog is null, "The update dialog did not close.");
            log.AppendLine("ui selftest ok");
            File.WriteAllText(reportPath, log.ToString());
            return 0;
        }
        catch (Exception error)
        {
            log.AppendLine(error.ToString());
            File.WriteAllText(reportPath, log.ToString());
            return 1;
        }
        finally
        {
            _versionDialog?.Hide();
            if (File.Exists(fixture)) File.Delete(fixture);
        }
    }

    private bool IsInsideRoot(FrameworkElement element)
    {
        var point = element.TransformToVisual(Root).TransformPoint(new Point());
        return element.ActualWidth > 0 && element.ActualHeight > 0 && point.X >= -1 && point.Y >= -1
            && point.X + element.ActualWidth <= Root.ActualWidth + 1
            && point.Y + element.ActualHeight <= Root.ActualHeight + 1;
    }

    private async Task LayoutSettledAsync()
    {
        await Task.Delay(200);
        Root.UpdateLayout();
    }

    private static async Task WaitForUiAsync(Func<bool> ready, string failure)
    {
        for (var attempt = 0; attempt < 100; attempt++)
        {
            if (ready()) return;
            await Task.Delay(50);
        }

        throw new TimeoutException(failure);
    }
}
