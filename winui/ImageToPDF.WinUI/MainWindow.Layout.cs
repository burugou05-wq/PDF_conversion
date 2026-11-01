using Microsoft.UI.Xaml;

namespace ImageToPDF.WinUI;

public sealed partial class MainWindow
{
    private void Root_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        // SizeChanged can run before named controls are connected by InitializeComponent.
        if (PreviewCard is null || PanesGrid is null) return;
        PreviewCard.Height = e.NewSize.Height < 700 ? 144 : 192;
        PanesGrid.ColumnDefinitions[1].Width = new GridLength(e.NewSize.Width < 1100 ? 310 : 340);
        // Keep preset errors visible on smaller windows, below the picker instead of beside it.
        var compact = e.NewSize.Width < 1000;
        Microsoft.UI.Xaml.Controls.Grid.SetRow(PresetStatusText, compact ? 1 : 0);
        Microsoft.UI.Xaml.Controls.Grid.SetColumn(PresetStatusText, compact ? 0 : 3);
        Microsoft.UI.Xaml.Controls.Grid.SetColumnSpan(PresetStatusText, compact ? 4 : 1);
        PresetStatusText.Margin = new Thickness(0, compact ? 6 : 0, 0, 0);
    }
}
