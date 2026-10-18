namespace ImageToPDF.WinUI.Services;

public sealed class WorkerRequest
{
    public string Operation { get; init; } = "convert";

    public IReadOnlyList<string> ImagePaths { get; init; } = Array.Empty<string>();

    public string OutputPath { get; init; } = string.Empty;

    public bool Overwrite { get; init; }

    /// <summary>
    /// thumbnail要求時の最大寸法 [幅, 高さ]。空ならワーカーの既定値（640×480）。
    /// グリッド表示のタイルは小さな寸法を要求してメモリを抑えます。
    /// </summary>
    public IReadOnlyList<int> ThumbnailSize { get; init; } = Array.Empty<int>();

    public WorkerOptions Options { get; init; } = new();
}

public sealed class WorkerOptions
{
    public string Quality { get; init; } = "original";

    public string? PageSize { get; init; }

    public double MarginMm { get; init; }

    public IReadOnlyList<int> Background { get; init; } = new[] { 255, 255, 255 };

    public bool AutoRotate { get; init; } = true;

    /// <summary>DPIを持たない画像に使う既定値（1〜10000）。JSON名は defaultDpi。</summary>
    public double DefaultDpi { get; init; } = 96;
}

public sealed class WorkerMessage
{
    /// <summary>Id of the request this message answers; null for unrelated output.</summary>
    public string? Id { get; init; }

    public string Type { get; init; } = string.Empty;

    public int Percent { get; init; }

    public string Message { get; init; } = string.Empty;

    public string OutputPath { get; init; } = string.Empty;

    public int PageCount { get; init; }

    public string Data { get; init; } = string.Empty;

    public List<SkippedInput> Skipped { get; init; } = new();

    /// <summary>inspect応答: 先頭フレームのピクセル寸法（EXIFの回転を反映した値）。</summary>
    public int Width { get; init; }

    public int Height { get; init; }

    public int FrameCount { get; init; }

    public double DpiHorizontal { get; init; }

    public double DpiVertical { get; init; }

    /// <summary>DPIの取得元（例: EXIF解像度タグ / PNG pHYs / 既定値 (96 DPI)）。</summary>
    public string DpiSource { get; init; } = string.Empty;

    /// <summary>DPIが見つからず既定値を使ったかどうか。</summary>
    public bool DpiUsedDefault { get; init; }

    /// <summary>埋め込みICCプロファイルの説明。</summary>
    public string IccProfile { get; init; } = string.Empty;
}

public sealed class SkippedInput
{
    public string Path { get; init; } = string.Empty;

    public string Reason { get; init; } = string.Empty;
}
