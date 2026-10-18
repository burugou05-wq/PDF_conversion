using System.Text;

namespace ImageToPDF.WinUI.Services;

/// <summary>
/// Headless check used by build_winui.ps1: converts one image through the embedded worker.
/// </summary>
public static class SelfTest
{
    public const string ConvertFlag = "--selftest-convert";

    public static async Task<int> RunConvertAsync(string inputPath, string outputPath)
    {
        try
        {
            var request = new WorkerRequest
            {
                Operation = "convert",
                ImagePaths = new[] { inputPath },
                OutputPath = outputPath,
                Overwrite = true,
                Options = new WorkerOptions(),
            };
            var result = await new ConversionWorkerService().RunAsync(request, null, CancellationToken.None);
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

            return 0;
        }
        catch (Exception error)
        {
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
