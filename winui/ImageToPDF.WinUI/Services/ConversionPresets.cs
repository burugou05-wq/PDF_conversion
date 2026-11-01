using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ImageToPDF.WinUI.Services;

/// <summary>Only reusable conversion options; paths, document information and window state stay private to the job.</summary>
public sealed record ConversionPresetOptions
{
    public string Quality { get; init; } = "original";
    public string PageSize { get; init; } = string.Empty;
    public double CustomPageWidthMm { get; init; } = 100;
    public double CustomPageHeightMm { get; init; } = 148;
    public double MarginMm { get; init; }
    public double DefaultDpi { get; init; } = 96;
    public string Background { get; init; } = "white";
    public bool AutoRotate { get; init; } = true;
    public bool FitToPage { get; init; }
    public string Alignment { get; init; } = "center";
    public bool OpenAfter { get; init; }
    public bool Outline { get; init; }
    public int CompactDpi { get; init; } = 150;
    public int JpegQuality { get; init; } = 85;

    public static ConversionPresetOptions FromSettings(AppSettings settings) => new()
    {
        Quality = settings.Quality,
        PageSize = settings.PageSize,
        CustomPageWidthMm = settings.CustomPageWidthMm,
        CustomPageHeightMm = settings.CustomPageHeightMm,
        MarginMm = settings.MarginMm,
        DefaultDpi = settings.DefaultDpi,
        Background = settings.Background,
        AutoRotate = settings.AutoRotate,
        FitToPage = settings.FitToPage,
        Alignment = settings.Alignment,
        OpenAfter = settings.OpenAfter,
        Outline = settings.Outline,
        CompactDpi = settings.CompactDpi,
        JpegQuality = settings.JpegQuality,
    };

    public void ApplyTo(AppSettings settings)
    {
        var value = Normalize();
        settings.Quality = value.Quality;
        settings.PageSize = value.PageSize;
        settings.CustomPageWidthMm = value.CustomPageWidthMm;
        settings.CustomPageHeightMm = value.CustomPageHeightMm;
        settings.MarginMm = value.MarginMm;
        settings.DefaultDpi = value.DefaultDpi;
        settings.Background = value.Background;
        settings.AutoRotate = value.AutoRotate;
        settings.FitToPage = value.FitToPage;
        settings.Alignment = value.Alignment;
        settings.OpenAfter = value.OpenAfter;
        settings.Outline = value.Outline;
        settings.CompactDpi = value.CompactDpi;
        settings.JpegQuality = value.JpegQuality;
    }

    /// <summary>Recover invalid stored values, including incompatible paper/margin combinations.</summary>
    public ConversionPresetOptions Normalize()
    {
        var page = PageSize is "" or "A3" or "A4" or "A5" or "B4" or "B5" or "Letter"
            or "Legal" or "Postcard" or "L" or "2L" or "Custom" ? PageSize : string.Empty;
        var width = Valid(CustomPageWidthMm, 10, 5000, 100);
        var height = Valid(CustomPageHeightMm, 10, 5000, 148);
        var minimumSide = page switch
        {
            "A3" => 297, "A4" => 210, "A5" => 148, "B4" => 257, "B5" => 182,
            "Letter" or "Legal" => 215.9, "Postcard" => 100, "L" => 89, "2L" => 127,
            "Custom" => Math.Min(width, height), _ => double.PositiveInfinity,
        };
        var margin = Valid(MarginMm, 0, 100, 0);
        return this with
        {
            Quality = Quality is "original" or "compact" ? Quality : "original",
            PageSize = page,
            CustomPageWidthMm = width,
            CustomPageHeightMm = height,
            MarginMm = margin * 2 >= minimumSide ? 0 : margin,
            DefaultDpi = Valid(DefaultDpi, 1, 10000, 96),
            Background = Background is "white" or "black" or "gray" ? Background : "white",
            Alignment = Alignment is "center" or "top" or "top-left" ? Alignment : "center",
            CompactDpi = CompactDpi is >= 36 and <= 600 ? CompactDpi : 150,
            JpegQuality = JpegQuality is >= 1 and <= 100 ? JpegQuality : 85,
        };
    }

    private static double Valid(double value, double minimum, double maximum, double fallback) =>
        double.IsFinite(value) && value >= minimum && value <= maximum ? value : fallback;
}

public sealed record ConversionPreset(string Name, ConversionPresetOptions Options)
{
    [JsonIgnore]
    public bool IsBuiltIn { get; init; }

    [JsonIgnore]
    public string DisplayName => IsBuiltIn ? $"{Name}（標準）" : Name;
}

/// <summary>Persist user presets separately from the previous-session settings. Writes succeed before changing the catalog.</summary>
public sealed class ConversionPresetStore
{
    public const int MaxNameLength = 60;
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private readonly string _filePath;
    private List<ConversionPreset> _custom = new();

    public ConversionPresetStore(string filePath) => _filePath = filePath;

    public static IReadOnlyList<ConversionPreset> BuiltIns => new[]
    {
        new ConversionPreset("提出書類用", new ConversionPresetOptions
        {
            PageSize = "A4", MarginMm = 10, Outline = true,
        }) { IsBuiltIn = true },
        new ConversionPreset("写真用", new ConversionPresetOptions()) { IsBuiltIn = true },
        new ConversionPreset("メール添付用", new ConversionPresetOptions
        {
            Quality = "compact", PageSize = "A4", MarginMm = 5, CompactDpi = 120, JpegQuality = 75,
        }) { IsBuiltIn = true },
    };

    public IReadOnlyList<ConversionPreset> All => BuiltIns.Concat(_custom).ToArray();

    public void Load()
    {
        _custom.Clear();
        if (!File.Exists(_filePath)) return;
        using var document = JsonDocument.Parse(File.ReadAllText(_filePath));
        if (document.RootElement.ValueKind != JsonValueKind.Array)
            throw new JsonException("プリセットの形式が正しくありません。");

        var loaded = new List<ConversionPreset>();
        var names = new HashSet<string>(BuiltIns.Select(item => item.Name), StringComparer.OrdinalIgnoreCase);
        foreach (var element in document.RootElement.EnumerateArray())
        {
            try
            {
                var preset = element.Deserialize<ConversionPreset>(JsonOptions);
                if (preset?.Options is null) continue;
                var name = ValidateName(preset.Name);
                if (names.Add(name)) loaded.Add(new ConversionPreset(name, preset.Options.Normalize()));
            }
            catch (Exception error) when (error is JsonException or ArgumentException)
            {
                // One damaged entry must not discard the other saved presets.
            }
        }

        _custom = loaded;
    }

    public ConversionPreset Save(string name, ConversionPresetOptions options, bool overwrite = false)
    {
        name = ValidateName(name);
        if (BuiltIns.Any(item => SameName(item.Name, name)))
            throw new ArgumentException("標準プリセットと同じ名前では保存できません。別の名前を付けてください。");
        var index = _custom.FindIndex(item => SameName(item.Name, name));
        if (index >= 0 && !overwrite) throw new ArgumentException("同じ名前のプリセットがあります。");
        var saved = new ConversionPreset(name, options.Normalize());
        var next = new List<ConversionPreset>(_custom);
        if (index >= 0) next[index] = saved;
        else next.Add(saved);
        Persist(next);
        _custom = next;
        return saved;
    }

    public void Delete(string name)
    {
        if (BuiltIns.Any(item => SameName(item.Name, name)))
            throw new ArgumentException("標準プリセットは削除できません。");
        var next = _custom.Where(item => !SameName(item.Name, name)).ToList();
        if (next.Count == _custom.Count) return;
        Persist(next);
        _custom = next;
    }

    private void Persist(List<ConversionPreset> presets)
    {
        var path = Path.GetFullPath(_filePath);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(presets, JsonOptions));
            File.Move(temporary, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }

    private static string ValidateName(string? name)
    {
        name = name?.Trim();
        if (string.IsNullOrEmpty(name) || name.Length > MaxNameLength || name.Any(char.IsControl))
            throw new ArgumentException($"名前は1〜{MaxNameLength}文字で入力してください（改行は使えません）。");
        return name;
    }

    private static bool SameName(string first, string second) =>
        string.Equals(first, second, StringComparison.OrdinalIgnoreCase);
}
