using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace ImageToPDF.WinUI.Services;

public sealed class ConversionWorkerService
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    public async Task<WorkerMessage> RunAsync(
        WorkerRequest request,
        IProgress<WorkerMessage>? progress,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var manifestPath = Path.Combine(
            Path.GetTempPath(), $"img2pdf-request-{Guid.NewGuid():N}.json");
        await File.WriteAllTextAsync(
            manifestPath,
            JsonSerializer.Serialize(request, JsonOptions),
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
            cancellationToken);

        try
        {
            using var process = new Process { StartInfo = CreateStartInfo(manifestPath) };
            if (!process.Start())
            {
                throw new InvalidOperationException("変換ワーカーを起動できませんでした。");
            }

            var errorOutput = process.StandardError.ReadToEndAsync();
            using var cancellationRegistration = cancellationToken.Register(() =>
            {
                try
                {
                    process.StandardInput.WriteLine("{\"type\":\"cancel\"}");
                    process.StandardInput.Flush();
                }
                catch (IOException)
                {
                    // The worker may have already exited successfully.
                }
                catch (ObjectDisposedException)
                {
                    // The worker may have already exited successfully.
                }
                catch (InvalidOperationException)
                {
                    // The redirected input stream may be closing during process exit.
                }
            });

            WorkerMessage? terminalMessage = null;
            string? line;
            while ((line = await process.StandardOutput.ReadLineAsync()) is not null)
            {
                WorkerMessage? message;
                try
                {
                    message = JsonSerializer.Deserialize<WorkerMessage>(line, JsonOptions);
                }
                catch (JsonException)
                {
                    continue;
                }

                if (message is null)
                {
                    continue;
                }

                if (message.Type is "progress")
                {
                    progress?.Report(message);
                }
                else if (message.Type is "completed" or "thumbnail" or "error" or "cancelled")
                {
                    terminalMessage = message;
                }
            }

            await process.WaitForExitAsync();
            var errorText = await errorOutput;
            if (terminalMessage?.Type == "cancelled" || process.ExitCode == 3)
            {
                throw new OperationCanceledException(terminalMessage?.Message, cancellationToken);
            }

            if (terminalMessage?.Type == "error")
            {
                throw new InvalidOperationException(terminalMessage.Message);
            }

            var expectedTerminalType = request.Operation == "thumbnail" ? "thumbnail" : "completed";
            var validExitCode = request.Operation == "thumbnail"
                ? process.ExitCode == 0
                : process.ExitCode is 0 or 2;
            if (terminalMessage?.Type != expectedTerminalType || !validExitCode)
            {
                var details = string.IsNullOrWhiteSpace(errorText)
                    ? "変換ワーカーから完了通知がありませんでした。"
                    : errorText.Trim();
                throw new InvalidOperationException(details);
            }

            return terminalMessage;
        }
        finally
        {
            try
            {
                File.Delete(manifestPath);
            }
            catch (IOException)
            {
                // The request contains only temporary app state; a failed cleanup is non-fatal.
            }
            catch (UnauthorizedAccessException)
            {
                // The request contains only temporary app state; a failed cleanup is non-fatal.
            }
        }
    }

    private static ProcessStartInfo CreateStartInfo(string manifestPath)
    {
        var baseDirectory = AppContext.BaseDirectory;
        var packagedWorker = Path.Combine(baseDirectory, "ImageToPDFWorker.exe");
        var startInfo = new ProcessStartInfo
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            WorkingDirectory = baseDirectory,
        };

        if (File.Exists(packagedWorker))
        {
            startInfo.FileName = packagedWorker;
        }
        else
        {
            var sourceWorker = FindSourceWorker();
            if (sourceWorker is null)
            {
                throw new FileNotFoundException(
                    "ImageToPDFWorker.exe が見つかりません。winui/README.md の手順でビルドしてください。");
            }

            startInfo.FileName = Environment.GetEnvironmentVariable("PYTHON") ?? "python";
            startInfo.ArgumentList.Add(sourceWorker);
            startInfo.WorkingDirectory = Path.GetDirectoryName(sourceWorker)!;
        }

        startInfo.ArgumentList.Add("--request");
        startInfo.ArgumentList.Add(manifestPath);
        return startInfo;
    }

    private static string? FindSourceWorker()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "conversion_worker.py");
            if (File.Exists(candidate))
            {
                return candidate;
            }

            directory = directory.Parent;
        }

        return null;
    }
}
