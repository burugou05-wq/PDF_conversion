using System.ComponentModel;
using System.IO;
using Microsoft.UI.Xaml.Media.Imaging;

namespace ImageToPDF.WinUI.Models;

/// <summary>
/// 一覧の1件。パスとサイズは生成時に決まりますが、グリッド表示のサムネイルは
/// 後から届くため、その1項目だけ INotifyPropertyChanged を実装しています。
/// </summary>
public sealed class ImageEntry : INotifyPropertyChanged
{
    private BitmapImage? _thumbnail;

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

    /// <summary>
    /// グリッドのタイルに表示するサムネイル。未取得、またはLRUで追い出されたときは
    /// null で、タイルはファイルアイコンを表示します。
    /// </summary>
    public BitmapImage? Thumbnail
    {
        get => _thumbnail;
        set
        {
            if (ReferenceEquals(_thumbnail, value))
            {
                return;
            }

            _thumbnail = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Thumbnail)));
        }
    }

    /// <summary>サムネイルを要求済みかどうか。同じ画像を繰り返し取りに行かないための印です。</summary>
    public bool ThumbnailRequested { get; set; }

    public event PropertyChangedEventHandler? PropertyChanged;

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
