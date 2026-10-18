using System.Globalization;
using System.Reflection;
using System.Text;

namespace ImageToPDF.WinUI.Services;

/// <summary>
/// 変換の結果と失敗理由を %LOCALAPPDATA%\ImageToPDF\app.log に残します。
///
/// Tkinter版の RotatingFileHandler（maxBytes=1MB / backupCount=3）と同じ振る舞いを
/// C# だけで再現しており、Python側（app_paths.py）に依存しません。保存先は
/// 環境変数 IMAGETOPDF_APP_LOG で上書きでき、build_winui.ps1 のビルド検証は
/// これを使って実行機のログを汚さずに記録の有無を確認します。
///
/// ログはベストエフォートです。書き込みに失敗しても例外を呼び出し元へ返さず、
/// 変換や画面の操作を止めません。
/// </summary>
public static class AppLog
{
    /// <summary>保存先を上書きする環境変数（ワーカーの IMAGETOPDF_WORKER_LOG と同じ考え方）。</summary>
    public const string PathOverrideVariable = "IMAGETOPDF_APP_LOG";

    /// <summary>1ファイルあたりの上限。Tkinter版と同じ 1MB（1,000,000バイト）。</summary>
    private const long MaxBytes = 1_000_000;

    /// <summary>繰り下げて残す世代数。app.log.1 〜 app.log.3 まで保持します。</summary>
    private const int BackupCount = 3;

    private static readonly object Gate = new();
    private static readonly UTF8Encoding Utf8NoBom = new(false);

    private static string? _logFile;
    private static bool _resolved;

    /// <summary>記録先のパス。解決できなかったときは null。</summary>
    public static string? LogFile
    {
        get
        {
            lock (Gate)
            {
                return ResolveUnlocked();
            }
        }
    }

    /// <summary>環境変数で保存先を上書きしているか。ビルド検証のみが true になります。</summary>
    public static bool IsPathOverridden { get; private set; }

    /// <summary>EXEに埋め込まれたバージョン（app_config.py の VERSION が元）。</summary>
    public static string ApplicationVersion
    {
        get
        {
            var assembly = typeof(AppLog).Assembly;
            var informational = assembly
                .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?
                .InformationalVersion;
            if (!string.IsNullOrWhiteSpace(informational))
            {
                return informational!;
            }

            return assembly.GetName().Version?.ToString() ?? "unknown";
        }
    }

    /// <summary>保存先を解決します。何度呼んでも安全です。</summary>
    public static void Initialize()
    {
        lock (Gate)
        {
            ResolveUnlocked();
        }
    }

    public static void Info(string message) => Write("INFO", message, null);

    public static void Warning(string message) => Write("WARNING", message, null);

    public static void Error(string message) => Write("ERROR", message, null);

    public static void Error(string message, Exception? error) => Write("ERROR", message, error);

    private static void Write(string level, string message, Exception? error)
    {
        var record = Format(level, message, error);
        lock (Gate)
        {
            var logFile = ResolveUnlocked();
            if (logFile is null)
            {
                return;
            }

            try
            {
                var directory = Path.GetDirectoryName(logFile);
                if (!string.IsNullOrWhiteSpace(directory))
                {
                    Directory.CreateDirectory(directory);
                }

                RotateIfNeeded(logFile, Utf8NoBom.GetByteCount(record));
                File.AppendAllText(logFile, record, Utf8NoBom);
            }
            catch (Exception)
            {
                // ログは診断用の副産物です。ディスクが満杯でも読み取り専用でも、
                // アプリの操作はそのまま続けられるようにします。
            }
        }
    }

    /// <summary>呼び出し元は Gate を保持している必要があります。</summary>
    private static string? ResolveUnlocked()
    {
        if (_resolved)
        {
            return _logFile;
        }

        _resolved = true;
        string? overridePath = null;
        try
        {
            overridePath = Environment.GetEnvironmentVariable(PathOverrideVariable);
        }
        catch (Exception)
        {
            // 環境変数が読めない環境でも既定のパスへ記録します。
        }

        IsPathOverridden = !string.IsNullOrWhiteSpace(overridePath);
        _logFile = IsPathOverridden ? overridePath : DefaultLogFile();
        return _logFile;
    }

    private static string? DefaultLogFile()
    {
        try
        {
            var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (string.IsNullOrWhiteSpace(localAppData))
            {
                localAppData = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                    "AppData",
                    "Local");
            }

            return Path.Combine(localAppData, "ImageToPDF", "app.log");
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static string Format(string level, string message, Exception? error)
    {
        var builder = new StringBuilder();
        builder
            .Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff", CultureInfo.InvariantCulture))
            .Append(' ')
            .Append(level.PadRight(7, ' '))
            .Append(' ')
            .Append(Flatten(message))
            .Append(Environment.NewLine);
        if (error is not null)
        {
            // スタックトレースは Tkinter版の logging.exception と同じくそのまま残します。
            builder.Append(error).Append(Environment.NewLine);
        }

        return builder.ToString();
    }

    private static string Flatten(string message)
    {
        if (message.IndexOf('\n') < 0 && message.IndexOf('\r') < 0)
        {
            return message;
        }

        return message.Replace("\r\n", " / ").Replace('\r', ' ').Replace('\n', ' ');
    }

    /// <summary>上限を超えそうなら app.log を app.log.1 へ繰り下げます（.3 は破棄）。</summary>
    private static void RotateIfNeeded(string logFile, int incomingBytes)
    {
        long currentBytes;
        try
        {
            var info = new FileInfo(logFile);
            if (!info.Exists)
            {
                return;
            }

            currentBytes = info.Length;
        }
        catch (Exception)
        {
            return;
        }

        if (currentBytes + incomingBytes <= MaxBytes)
        {
            return;
        }

        try
        {
            var oldest = BackupFile(logFile, BackupCount);
            if (File.Exists(oldest))
            {
                File.Delete(oldest);
            }

            for (var index = BackupCount - 1; index >= 1; index--)
            {
                var source = BackupFile(logFile, index);
                if (File.Exists(source))
                {
                    File.Move(source, BackupFile(logFile, index + 1), overwrite: true);
                }
            }

            File.Move(logFile, BackupFile(logFile, 1), overwrite: true);
        }
        catch (Exception)
        {
            // 繰り下げに失敗しても、今のファイルへの追記は試みます。
        }
    }

    private static string BackupFile(string logFile, int index) =>
        logFile + "." + index.ToString(CultureInfo.InvariantCulture);
}
