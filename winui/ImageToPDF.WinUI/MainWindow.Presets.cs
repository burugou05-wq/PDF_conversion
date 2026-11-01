using System.IO;
using System.Text.Json;
using ImageToPDF.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace ImageToPDF.WinUI;

public sealed partial class MainWindow
{
    private readonly ConversionPresetStore _presets = new(Path.Combine(AppLog.DataDirectory, "presets.json"));
    private bool _refreshingPresets;

    private void InitializePresets()
    {
        try
        {
            if (!_isUiSelfTest) _presets.Load();
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
        {
            PresetStatusText.Text = "保存したプリセットを読み込めませんでした。標準プリセットを使えます。";
            AppLog.Warning($"プリセットを読み込めませんでした: {error.Message}");
        }

        RefreshPresets();
    }

    private void RefreshPresets(string? selectedName = null)
    {
        _refreshingPresets = true;
        try
        {
            var items = _presets.All;
            PresetBox.ItemsSource = items;
            PresetBox.SelectedItem = items.FirstOrDefault(item => item.Name == selectedName);
        }
        finally
        {
            _refreshingPresets = false;
        }

        UpdatePresetButtons();
    }

    private void UpdatePresetButtons()
    {
        var available = _conversionCancellation is null;
        var custom = PresetBox.SelectedItem is ConversionPreset { IsBuiltIn: false };
        PresetBox.IsEnabled = available;
        PresetManageButton.IsEnabled = available;
        SavePresetButton.IsEnabled = available;
        OverwritePresetButton.IsEnabled = available && custom;
        DeletePresetButton.IsEnabled = available && custom;
    }

    private void PresetBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_settingsReady || _refreshingPresets || _conversionCancellation is not null) return;
        UpdatePresetButtons();
        if (PresetBox.SelectedItem is not ConversionPreset preset) return;
        preset.Options.ApplyTo(_settings);
        ApplyConversionSettings(_settings);
        if (!_isUiSelfTest) _settings.Save();
        PresetStatusText.Text = $"「{preset.Name}」を適用しました。各設定は変更できます。";
    }

    private ConversionPresetOptions? CapturePresetOptions()
    {
        var (_, dpiError) = ReadDefaultDpi();
        var error = dpiError ?? ValidateExtraInputs();
        if (!double.IsFinite(MarginBox.Value) || MarginBox.Value < 0 || MarginBox.Value > 100)
            error = "余白は0〜100 mmで指定してください。";
        var settings = new AppSettings();
        CollectConversionSettings(settings);
        var options = ConversionPresetOptions.FromSettings(settings);
        if (options.Normalize().MarginMm != options.MarginMm)
            error ??= "余白が用紙サイズを超えています。";
        if (error is not null)
        {
            PresetStatusText.Text = error;
            return null;
        }

        return options.Normalize();
    }

    private async void SavePresetButton_Click(object sender, RoutedEventArgs e)
    {
        if (_conversionCancellation is not null || CapturePresetOptions() is not { } options) return;
        var nameBox = new TextBox
        {
            Header = "プリセット名",
            PlaceholderText = "例：毎月の提出書類",
            MaxLength = ConversionPresetStore.MaxNameLength,
        };
        var dialog = new ContentDialog
        {
            Title = "現在の設定を保存",
            Content = nameBox,
            PrimaryButtonText = "保存",
            CloseButtonText = "キャンセル",
            IsPrimaryButtonEnabled = false,
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = Root.XamlRoot,
        };
        nameBox.TextChanged += (_, _) => dialog.IsPrimaryButtonEnabled = !string.IsNullOrWhiteSpace(nameBox.Text);
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        var name = nameBox.Text.Trim();
        var existing = _presets.All.FirstOrDefault(item => string.Equals(item.Name, name, StringComparison.OrdinalIgnoreCase));
        if (existing is { IsBuiltIn: false } && !await ConfirmPresetAsync("プリセットを上書きしますか？", name, "上書き")) return;
        try
        {
            var saved = _presets.Save(name, options, overwrite: existing is { IsBuiltIn: false });
            RefreshPresets(saved.Name);
            PresetStatusText.Text = $"「{saved.Name}」を保存しました。次回起動後も使えます。";
        }
        catch (Exception error) when (IsPresetError(error))
        {
            await ShowPresetErrorAsync(error);
        }
    }

    private async void OverwritePresetButton_Click(object sender, RoutedEventArgs e)
    {
        if (_conversionCancellation is not null || PresetBox.SelectedItem is not ConversionPreset { IsBuiltIn: false } preset
            || CapturePresetOptions() is not { } options) return;
        if (!await ConfirmPresetAsync("プリセットを現在の設定で上書きしますか？", preset.Name, "上書き")) return;
        try
        {
            _presets.Save(preset.Name, options, overwrite: true);
            RefreshPresets(preset.Name);
            PresetStatusText.Text = $"「{preset.Name}」を現在の設定で上書きしました。";
        }
        catch (Exception error) when (IsPresetError(error))
        {
            await ShowPresetErrorAsync(error);
        }
    }

    private async void DeletePresetButton_Click(object sender, RoutedEventArgs e)
    {
        if (_conversionCancellation is not null || PresetBox.SelectedItem is not ConversionPreset { IsBuiltIn: false } preset) return;
        if (!await ConfirmPresetAsync("プリセットを削除しますか？", $"{preset.Name}\n現在の変換設定はそのまま残ります。", "削除")) return;
        try
        {
            _presets.Delete(preset.Name);
            RefreshPresets();
            PresetStatusText.Text = $"「{preset.Name}」を削除しました。";
        }
        catch (Exception error) when (IsPresetError(error))
        {
            await ShowPresetErrorAsync(error);
        }
    }

    private async Task<bool> ConfirmPresetAsync(string title, string content, string action)
    {
        var dialog = new ContentDialog
        {
            Title = title, Content = content, PrimaryButtonText = action, CloseButtonText = "キャンセル",
            DefaultButton = ContentDialogButton.Close, XamlRoot = Root.XamlRoot,
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }

    private static bool IsPresetError(Exception error) =>
        error is IOException or UnauthorizedAccessException or ArgumentException or JsonException;

    private async Task ShowPresetErrorAsync(Exception error)
    {
        PresetStatusText.Text = "プリセットを変更できませんでした。";
        AppLog.Warning($"プリセットを変更できませんでした: {error.Message}");
        await ShowMessageAsync("プリセットを変更できません", error.Message);
    }
}
