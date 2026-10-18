using ImageToPDF.WinUI.Services;
using Microsoft.UI.Xaml;

namespace ImageToPDF.WinUI;

public partial class App : Application
{
    private Window? _window;

    public App()
    {
        InitializeComponent();
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        var commandLine = Environment.GetCommandLineArgs();
        if (commandLine.Length == 4 && commandLine[1] == SelfTest.ConvertFlag)
        {
            var exitCode = await SelfTest.RunConvertAsync(commandLine[2], commandLine[3]);
            Environment.Exit(exitCode);
            return;
        }

        _window = new MainWindow();
        _window.Activate();
    }
}
