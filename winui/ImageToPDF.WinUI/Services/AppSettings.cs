using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ImageToPDF.WinUI.Services;

/// <summary>
/// 変換設定と画面の状態を `%LOCALAPPDATA%\ImageToPDF\settings.json` に保存します。
/// 読み込みに失敗したり値が範囲外のときは既定値に戻し、起動を止めません。
/// アンインストール時はフォルダーごと削除されるため、ここで消す処理は不要です。
/// </summary>
public sealed class AppSettings
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
    };

    public static string FilePath => Path.Combine(AppLog.DataDirectory, "settings.json");

    public string Quality { get; set; } = "original";

    public string PageSize { get; set; } = string.Empty;

    public double CustomPageWidthMm { get; set; } = 100;

    public double CustomPageHeightMm { get; set; } = 148;

    public double MarginMm { get; set; }

    public double DefaultDpi { get; set; } = 96;

    public string Background { get; set; } = "white";

    public bool AutoRotate { get; set; } = true;

    public bool FitToPage { get; set; }

    public string Alignment { get; set; } = "center";

    public bool OpenAfter { get; set; }

    public bool Outline { get; set; }

    public int CompactDpi { get; set; } = 150;

    public int JpegQuality { get; set; } = 85;

    public string MetadataAuthor { get; set; } = string.Empty;

    public int FolderSortIndex { get; set; }

    public bool GridView { get; set; }

    public string LastOutputDirectory { get; set; } = string.Empty;

    public int WindowWidth { get; set; } = 1320;

    public int WindowHeight { get; set; } = 860;

    public static AppSettings Load()
    {
        try
        {
            if (!File.Exists(FilePath))
            {
                return new AppSettings();
            }

            var json = File.ReadAllText(FilePath);
            var loaded = JsonSerializer.Deserialize<AppSettings>(json, SerializerOptions);
            if (loaded is null)
            {
                return new AppSettings();
            }

            loaded.Sanitize();
            return loaded;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
        {
            AppLog.Warning($"設定を読み込めませんでした（既定値を使います）: {error.GetType().Name}: {error.Message}");
            return new AppSettings();
        }
    }

    public void Save()
    {
        try
        {
            Sanitize();
            Directory.CreateDirectory(AppLog.DataDirectory);
            var temporary = FilePath + ".tmp";
            File.WriteAllText(temporary, JsonSerializer.Serialize(this, SerializerOptions));
            File.Move(temporary, FilePath, overwrite: true);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            AppLog.Warning($"設定を保存できませんでした: {error.GetType().Name}: {error.Message}");
        }
    }

    /// <summary>範囲外・未知の値を既定値に戻します。ワーカー側の検証と同じ範囲です。</summary>
    private void Sanitize()
    {
        if (Quality is not ("original" or "compact"))
        {
            Quality = "original";
        }

        if (!double.IsFinite(CustomPageWidthMm) || CustomPageWidthMm < 10 || CustomPageWidthMm > 5000)
        {
            CustomPageWidthMm = 100;
        }

        if (!double.IsFinite(CustomPageHeightMm) || CustomPageHeightMm < 10 || CustomPageHeightMm > 5000)
        {
            CustomPageHeightMm = 148;
        }

        if (!double.IsFinite(MarginMm) || MarginMm < 0 || MarginMm > 100)
        {
            MarginMm = 0;
        }

        if (!double.IsFinite(DefaultDpi) || DefaultDpi < 1 || DefaultDpi > 10000)
        {
            DefaultDpi = 96;
        }

        if (Background is not ("white" or "black" or "gray"))
        {
            Background = "white";
        }

        if (Alignment is not ("center" or "top" or "top-left"))
        {
            Alignment = "center";
        }

        if (CompactDpi < 36 || CompactDpi > 600)
        {
            CompactDpi = 150;
        }

        if (JpegQuality < 1 || JpegQuality > 100)
        {
            JpegQuality = 85;
        }

        if (FolderSortIndex is < 0 or > 2)
        {
            FolderSortIndex = 0;
        }

        if (WindowWidth < 800 || WindowWidth > 10000)
        {
            WindowWidth = 1320;
        }

        if (WindowHeight < 600 || WindowHeight > 10000)
        {
            WindowHeight = 860;
        }

        MetadataAuthor ??= string.Empty;
        LastOutputDirectory ??= string.Empty;
        PageSize ??= string.Empty;
    }
}
