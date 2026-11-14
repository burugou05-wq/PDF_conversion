using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace ImageToPDF.WinUI;

public sealed partial class MainWindow
{
    private void Root_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        // SizeChanged can run before named controls are connected by InitializeComponent.
        if (PanesGrid is null || PresetStatusText is null) return;
        PanesGrid.ColumnDefinitions[1].Width = new GridLength(e.NewSize.Width < 1100 ? 320 : 350);
        // Keep preset errors visible on smaller windows, below the picker instead of beside it.
        var compact = e.NewSize.Width < 1020;
        Grid.SetRow(PresetStatusText, compact ? 1 : 0);
        Grid.SetColumn(PresetStatusText, compact ? 0 : 4);
        Grid.SetColumnSpan(PresetStatusText, compact ? 5 : 1);
        PresetStatusText.Margin = new Thickness(0, compact ? 4 : 0, 0, 0);
    }
}
