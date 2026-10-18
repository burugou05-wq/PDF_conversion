using System.Text;

namespace ImageToPDF.WinUI.Services;

/// <summary>
/// Headless check used by build_winui.ps1: converts one image through the embedded worker.
/// Steps are logged to &lt;output&gt;.selftest-log.txt so a hang reports where it stopped.
/// </summary>
public static class SelfTest
{
    public const string ConvertFlag = "--selftest-convert";

    public static async Task<int> RunConvertAsync(string inputPath, string outputPath)
    {
        var logPath = outputPath + ".selftest-log.txt";
        try
        {
            File.WriteAllText(logPath, $"{DateTime.UtcNow:O} selftest start\n", Encoding.UTF8);
        }
        catch (IOException)
        {
            // Diagnostics are best-effort.
        }

        void Log(string step)
        {
            try
            {
                File.AppendAllText(logPath, $"{DateTime.UtcNow:O} {step}\n", Encoding.UTF8);
            }
            catch (IOException)
            {
                // Diagnostics are best-effort.
            }
        }

        try
        {
            Log($"app log: {AppLog.LogFile ?? "(unavailable)"}");
            Log($"worker resource: {EmbeddedWorker.ResourceName}");
            var workerPath = EmbeddedWorker.TryGetWorkerPath();
            Log($"worker path: {workerPath ?? "(not embedded; source fallback)"}");

            var request = new WorkerRequest
            {
                Operation = "convert",
                ImagePaths = new[] { inputPath },
                OutputPath = outputPath,
                Overwrite = true,
                Options = new WorkerOptions(),
            };
            Log("request ready; starting worker");
            var result = await new ConversionWorkerService().RunAsync(request, null, CancellationToken.None);
            Log($"response type={result.Type} pages={result.PageCount}");
            if (result.Type != "completed" || result.PageCount != 1 || !File.Exists(outputPath))
            {
                return 1;
            }

            var header = new byte[5];
            using var stream = File.OpenRead(outputPath);
            if (stream.Read(header, 0, header.Length) != header.Length
                || Encoding.ASCII.GetString(header) != "%PDF-")
            {
                return 1;
            }

            if (!VerifyAppLog(result.PageCount, Log))
            {
                return 1;
            }

            Log("selftest ok");
            return 0;
        }
        catch (Exception error)
        {
            Log($"failed: {error}");
            try
            {
                File.WriteAllText(outputPath + ".selftest-error.txt", error.ToString(), Encoding.UTF8);
            }
            catch (IOException)
            {
                // The exit code is the primary result.
            }

            return 1;
        }
    }

    /// <summary>
    /// 変換の記録が app.log に残ることを確認します。build_winui.ps1 は
    /// IMAGETOPDF_APP_LOG で保存先を一時ファイルへ向けてから呼び出します。
    /// </summary>
    private static bool VerifyAppLog(int pageCount, Action<string> log)
    {
        var logFile = AppLog.LogFile ?? string.Empty;
        if (logFile.Length == 0)
        {
            log("app log path could not be resolved");
            return false;
        }

        var marker = Guid.NewGuid().ToString("N");
        AppLog.Info($"自己診断の変換を記録しました: pages={pageCount} marker={marker}");
        if (!File.Exists(logFile))
        {
            log($"app log was not created: {logFile}");
            return false;
        }

        string content;
        try
        {
            content = File.ReadAllText(logFile, Encoding.UTF8);
        }
        catch (IOException error)
        {
            log($"app log could not be read: {error.Message}");
            return false;
        }

        if (!content.Contains(marker, StringComparison.Ordinal))
        {
            log($"app log has no conversion record (length={content.Length})");
            return false;
        }

        log($"app log verified: {logFile} ({content.Length} chars)");
        return !AppLog.IsPathOverridden || VerifyRotation(logFile, log);
    }

    /// <summary>
    /// 1MB を超えた記録が app.log.1 へ繰り下がることを確認します。実行機のログを
    /// ダミー行で汚さないよう、保存先を上書きしたビルド検証のときだけ動かします。
    /// </summary>
    private static bool VerifyRotation(string logFile, Action<string> log)
    {
        var filler = new string('x', 400_000);
        AppLog.Info($"rotation check 1: {filler}");
        AppLog.Info($"rotation check 2: {filler}");
        AppLog.Info($"rotation check 3: {filler}");

        var rotated = logFile + ".1";
        if (!File.Exists(rotated))
        {
            log($"app log did not rotate past 1MB: {logFile}");
            return false;
        }

        var current = new FileInfo(logFile).Length;
        if (current > 1_000_000)
        {
            log($"app log is still above the 1MB limit after rotation ({current} bytes)");
            return false;
        }

        log($"app log rotated: {rotated} exists, current={current} bytes");
        return true;
    }
}
