namespace ImageToPDF.WinUI.Services;

public sealed class WorkerRequest
{
    public string Operation { get; init; } = "convert";

    public IReadOnlyList<string> ImagePaths { get; init; } = Array.Empty<string>();

    public string OutputPath { get; init; } = string.Empty;

    public bool Overwrite { get; init; }

    public WorkerOptions Options { get; init; } = new();
}

public sealed class WorkerOptions
{
    public string Quality { get; init; } = "original";

    public string? PageSize { get; init; }

    public double MarginMm { get; init; }

    public IReadOnlyList<int> Background { get; init; } = new[] { 255, 255, 255 };

    public bool AutoRotate { get; init; } = true;
}

public sealed class WorkerMessage
{
    public string Type { get; init; } = string.Empty;

    public int Percent { get; init; }

    public string Message { get; init; } = string.Empty;

    public string OutputPath { get; init; } = string.Empty;

    public int PageCount { get; init; }

    public string Data { get; init; } = string.Empty;

    public List<SkippedInput> Skipped { get; init; } = new();
}

public sealed class SkippedInput
{
    public string Path { get; init; } = string.Empty;

    public string Reason { get; init; } = string.Empty;
}
