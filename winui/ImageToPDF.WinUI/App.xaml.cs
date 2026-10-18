using ImageToPDF.WinUI.Services;
using Microsoft.UI.Xaml;

namespace ImageToPDF.WinUI;

public partial class App : Application
{
    private Window? _window;

    public App()
    {
        InitializeComponent();
        AppLog.Initialize();
        // 画面に出せない異常も app.log に残し、事後に原因を追えるようにします。
        AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;
        TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        AppLog.Initialize();
        var commandLine = Environment.GetCommandLineArgs();
        if (commandLine.Length == 4 && commandLine[1] == SelfTest.ConvertFlag)
        {
            AppLog.Info($"自己診断を開始します: {commandLine[2]} → {commandLine[3]}");
            var exitCode = await SelfTest.RunConvertAsync(commandLine[2], commandLine[3]);
            AppLog.Info($"自己診断を終了しました: exit={exitCode}");
            Environment.Exit(exitCode);
            return;
        }

        AppLog.Info(
            "アプリを開始しました"
            + $" (v{AppLog.ApplicationVersion}, Windows {Environment.OSVersion.Version}, {(Environment.Is64Process ? "x64" : "x86")})");
        _window = new MainWindow();
        _window.Activate();
    }

    private static void OnUnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        AppLog.Error(
            $"未処理の例外が発生しました (IsTerminating={e.IsTerminating})",
            e.ExceptionObject as Exception);
    }

    private static void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs e)
    {
        AppLog.Error("未観測のタスク例外が発生しました", e.Exception);
        e.SetObserved();
    }
}
