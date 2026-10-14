using System.IO;

namespace ImageToPDF.WinUI.Models;

public sealed class ImageEntry
{
    public ImageEntry(string fullPath)
    {
        FullPath = Path.GetFullPath(fullPath);
        Name = Path.GetFileName(FullPath);
        ParentDirectory = Path.GetDirectoryName(FullPath) ?? string.Empty;
        SizeText = GetSizeText(FullPath);
    }

    public string FullPath { get; }

    public string Name { get; }

    public string ParentDirectory { get; }

    public string SizeText { get; }

    private static string GetSizeText(string path)
    {
        try
        {
            var length = new FileInfo(path).Length;
            return length switch
            {
                < 1024 => $"{length} B",
                < 1024 * 1024 => $"{length / 1024d:0.#} KB",
                _ => $"{length / (1024d * 1024d):0.#} MB",
            };
        }
        catch (IOException)
        {
            return "";
        }
        catch (UnauthorizedAccessException)
        {
            return "";
        }
    }
}
