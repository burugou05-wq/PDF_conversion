using System.Collections.ObjectModel;
using System.IO;
using System.Text.RegularExpressions;
using ImageToPDF.WinUI.Models;

namespace ImageToPDF.WinUI.ViewModels;

public enum FolderSortMode
{
    Name,
    Number,
    Date,
}

public sealed class MainViewModel
{
    private static readonly HashSet<string> SupportedExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".jpg", ".jpeg", ".png", ".avif", ".heic", ".heif", ".webp", ".bmp", ".gif", ".tif", ".tiff",
    };

    private static readonly Regex NumericPart = new(@"(\d+)", RegexOptions.Compiled);
    private readonly List<ImageEntry> _items = new();
    private string _searchText = string.Empty;

    public ObservableCollection<ImageEntry> VisibleItems { get; } = new();

    public IReadOnlyList<ImageEntry> Items => _items;

    /// <summary>
    /// 画像ファイルやフォルダーを一覧に追加します。
    /// ドラッグ＆ドロップやファイル選択ダイアログは、掴んだファイルやクリック順でパスを渡してくるため、
    /// 渡された順序ではなく、フォルダー追加と同じ並び順（名前順・数字順・更新日時順）でそろえてから追加します。
    /// フォルダーはそれぞれの中身を並べ替え、ファイルとフォルダーの前後関係は渡された順を保ちます。
    /// </summary>
    public int AddPaths(IEnumerable<string> values, FolderSortMode folderSort)
    {
        var knownPaths = new HashSet<string>(
            _items.Select(item => item.FullPath),
            StringComparer.OrdinalIgnoreCase);
        var added = 0;
        var pendingFiles = new List<string>();

        void FlushPendingFiles()
        {
            if (pendingFiles.Count == 0)
            {
                return;
            }

            foreach (var candidate in SortPaths(pendingFiles, folderSort))
            {
                added += AddCandidate(candidate, knownPaths) ? 1 : 0;
            }

            pendingFiles.Clear();
        }

        foreach (var value in values)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                continue;
            }

            if (Directory.Exists(value))
            {
                FlushPendingFiles();
                foreach (var candidate in GetFolderImages(value, folderSort))
                {
                    added += AddCandidate(candidate, knownPaths) ? 1 : 0;
                }
            }
            else if (File.Exists(value) && IsSupported(value))
            {
                pendingFiles.Add(value);
            }
        }

        FlushPendingFiles();
        Refresh();
        return added;
    }

    private bool AddCandidate(string candidate, HashSet<string> knownPaths)
    {
        var fullPath = Path.GetFullPath(candidate);
        if (!IsSupported(fullPath) || !knownPaths.Add(fullPath))
        {
            return false;
        }

        _items.Add(new ImageEntry(fullPath));
        return true;
    }

    public void SetSearchText(string value)
    {
        _searchText = value ?? string.Empty;
        Refresh();
    }

    public void Remove(IEnumerable<ImageEntry> selected)
    {
        var selection = new HashSet<ImageEntry>(selected);
        _items.RemoveAll(selection.Contains);
        Refresh();
    }

    public void Clear()
    {
        _items.Clear();
        Refresh();
    }

    public void Move(IEnumerable<ImageEntry> selected, int direction)
    {
        var selection = new HashSet<ImageEntry>(selected);
        if (selection.Count == 0)
        {
            return;
        }

        if (direction < 0)
        {
            for (var index = 1; index < _items.Count; index++)
            {
                if (selection.Contains(_items[index]) && !selection.Contains(_items[index - 1]))
                {
                    (_items[index - 1], _items[index]) = (_items[index], _items[index - 1]);
                }
            }
        }
        else
        {
            for (var index = _items.Count - 2; index >= 0; index--)
            {
                if (selection.Contains(_items[index]) && !selection.Contains(_items[index + 1]))
                {
                    (_items[index], _items[index + 1]) = (_items[index + 1], _items[index]);
                }
            }
        }

        Refresh();
    }

    public void MoveToBoundary(IEnumerable<ImageEntry> selected, bool toTop)
    {
        var selection = new HashSet<ImageEntry>(selected);
        if (selection.Count == 0)
        {
            return;
        }

        var moving = _items.Where(selection.Contains).ToList();
        var remaining = _items.Where(item => !selection.Contains(item)).ToList();
        _items.Clear();
        _items.AddRange(toTop ? moving.Concat(remaining) : remaining.Concat(moving));
        Refresh();
    }

    private void Refresh()
    {
        VisibleItems.Clear();
        foreach (var item in _items.Where(item =>
                     item.Name.Contains(_searchText, StringComparison.CurrentCultureIgnoreCase)))
        {
            VisibleItems.Add(item);
        }
    }

    private static IEnumerable<string> GetFolderImages(string folder, FolderSortMode sortMode)
        => SortPaths(Directory.EnumerateFiles(folder).Where(IsSupported), sortMode);

    /// <summary>フォルダー追加・ファイル追加・ドロップで共通の並び替えです。</summary>
    private static IEnumerable<string> SortPaths(IEnumerable<string> paths, FolderSortMode sortMode)
    {
        return sortMode switch
        {
            FolderSortMode.Number => paths.OrderBy(
                path => Path.GetFileName(path), NaturalNameComparer.Instance),
            FolderSortMode.Date => paths
                .OrderByDescending(GetLastWriteTimeUtc)
                .ThenBy(path => Path.GetFileName(path), StringComparer.CurrentCultureIgnoreCase),
            _ => paths.OrderBy(
                path => Path.GetFileName(path), StringComparer.CurrentCultureIgnoreCase),
        };
    }

    private static bool IsSupported(string path) =>
        SupportedExtensions.Contains(Path.GetExtension(path));

    private static DateTime GetLastWriteTimeUtc(string path)
    {
        try
        {
            return File.GetLastWriteTimeUtc(path);
        }
        catch (IOException)
        {
            return DateTime.MinValue;
        }
        catch (UnauthorizedAccessException)
        {
            return DateTime.MinValue;
        }
    }

    private sealed class NaturalNameComparer : IComparer<string?>
    {
        public static NaturalNameComparer Instance { get; } = new();

        public int Compare(string? left, string? right)
        {
            if (ReferenceEquals(left, right))
            {
                return 0;
            }

            if (left is null)
            {
                return -1;
            }

            if (right is null)
            {
                return 1;
            }

            var leftParts = NumericPart.Split(left);
            var rightParts = NumericPart.Split(right);
            var commonLength = Math.Min(leftParts.Length, rightParts.Length);
            for (var index = 0; index < commonLength; index++)
            {
                var a = leftParts[index];
                var b = rightParts[index];
                var aIsNumber = index % 2 == 1;
                var comparison = aIsNumber && b.Length > 0
                    ? CompareDigits(a, b)
                    : StringComparer.CurrentCultureIgnoreCase.Compare(a, b);
                if (comparison != 0)
                {
                    return comparison;
                }
            }

            return leftParts.Length.CompareTo(rightParts.Length);
        }

        private static int CompareDigits(string left, string right)
        {
            var normalizedLeft = left.TrimStart('0');
            var normalizedRight = right.TrimStart('0');
            if (normalizedLeft.Length == 0)
            {
                normalizedLeft = "0";
            }

            if (normalizedRight.Length == 0)
            {
                normalizedRight = "0";
            }

            var lengthComparison = normalizedLeft.Length.CompareTo(normalizedRight.Length);
            if (lengthComparison != 0)
            {
                return lengthComparison;
            }

            var valueComparison = StringComparer.Ordinal.Compare(normalizedLeft, normalizedRight);
            return valueComparison != 0 ? valueComparison : left.Length.CompareTo(right.Length);
        }
    }
}
