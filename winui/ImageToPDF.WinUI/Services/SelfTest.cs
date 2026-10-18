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
}
