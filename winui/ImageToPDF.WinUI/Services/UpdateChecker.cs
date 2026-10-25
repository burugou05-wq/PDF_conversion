using System.Globalization;
using System.Net;
using System.Net.Http;
using System.Text.Json;

namespace ImageToPDF.WinUI.Services;

/// <summary>
/// GitHub Release から取得した最新版の情報です。
/// </summary>
/// <param name="Version">タグを数値化したバージョン（例: 2.3.0.0）。</param>
/// <param name="TagName">タグ名（例: v2.3.0.0）。表示とキャッシュのキーに使います。</param>
/// <param name="Notes">リリースノート（CHANGELOG.md の該当セクション）。</param>
public sealed record UpdateRelease(
    Version Version,
    string TagName,
    string Notes,
    DateTimeOffset? PublishedAt,
    string ReleasePageUrl,
    string? AssetName,
    string? DownloadUrl,
    long DownloadSize,
    string? ChecksumsUrl);

/// <summary>
/// アップデート確認の結果です。通信できなかった場合も <see cref="Error"/> に理由を入れ、
/// 呼び出し元が「最新である」と「確認できなかった」を区別できるようにします。
/// </summary>
public sealed record UpdateCheckResult(UpdateRelease? Release, DateTimeOffset? CheckedAt, string? Error)
{
    public bool Succeeded => Error is null;
}

/// <summary>
/// 最新リリースの問い合わせと解析を行います。
///
/// 通信先は api.github.com と github.com（配布ファイル）だけで、送信するのは
/// User-Agent と標準ヘッダーだけです。識別子や利用状況は送りません。
/// 結果は <c>%LOCALAPPDATA%\ImageToPDF\update-cache.json</c> に保存し、
/// 自動確認は6時間に1回だけ、手動（バージョン表示のタップ）では常に取り直します。
/// </summary>
public static class UpdateChecker
{
    public const string Repository = "burugou05-wq/PDF_conversion";
    public const string LatestReleaseApiUrl =
        "https://api.github.com/repos/" + Repository + "/releases/latest";
    public const string ReleasesPageUrl = "https://github.com/" + Repository + "/releases";

    /// <summary>この環境変数が設定されていると自動確認を行いません（CI・オフライン検証用）。</summary>
    public const string DisableVariable = "IMAGETOPDF_DISABLE_UPDATE_CHECK";

    private const string ChecksumsAssetName = "SHA256SUMS.txt";
    private const string ExecutableSuffix = ".exe";
    private const string ExecutablePrefix = "ImageToPDF-";

    private static readonly TimeSpan AutomaticCheckInterval = TimeSpan.FromHours(6);

    /// <summary>自動確認が無効化されているかどうか。</summary>
    public static bool AutomaticCheckDisabled()
    {
        try
        {
            return !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable(DisableVariable));
        }
        catch (Exception)
        {
            // 環境変数が読めない環境では、外部通信を控える側に倒します。
            return true;
        }
    }

    public static string CacheFilePath => Path.Combine(AppLog.DataDirectory, "update-cache.json");

    /// <summary>
    /// 最新リリースを取得します。<paramref name="currentVersion"/> と同じか古い場合は
    /// <see cref="UpdateRelease"/> が null になります（＝最新を使用中）。
    /// </summary>
    public static async Task<UpdateCheckResult> FindLatestAsync(
        Version currentVersion,
        bool forceRefresh,
        CancellationToken cancellationToken)
    {
        var cache = TryReadCache(CacheFilePath);
        var checkedAt = cache?.FetchedAt;
        string? payload = null;
        string? error = null;

        if (!forceRefresh && cache is not null
            && DateTimeOffset.UtcNow - cache.FetchedAt < AutomaticCheckInterval)
        {
            payload = cache.Payload;
        }

        if (payload is null)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, LatestReleaseApiUrl);
                using var response = await UpdateHttp.Client.SendAsync(
                    request, HttpCompletionOption.ResponseContentRead, cancellationToken);
                if (!response.IsSuccessStatusCode)
                {
                    error = $"GitHub API が {(int)response.StatusCode} を返しました";
                    AppLog.Warning($"アップデート確認: APIがHTTP {(int)response.StatusCode} を返しました");
                }
                else
                {
                    payload = await response.Content.ReadAsStringAsync(cancellationToken);
                    checkedAt = DateTimeOffset.UtcNow;
                    WriteCache(CacheFilePath, checkedAt.Value, payload);
                }
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                // HttpClient のタイムアウトも OperationCanceledException で届きます。
                error = "接続がタイムアウトしました";
                AppLog.Warning("アップデート確認: 接続がタイムアウトしました");
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception exception) when (
                exception is HttpRequestException or IOException or UriFormatException)
            {
                error = "GitHubに接続できませんでした";
                AppLog.Warning($"アップデート確認: 接続できませんでした: {exception.GetType().Name}");
            }

            if (payload is null && cache is not null)
            {
                // オフラインでも、前回取得した内容から更新の有無を判定します。
                payload = cache.Payload;
                checkedAt = cache.FetchedAt;
            }
        }

        if (payload is null)
        {
            return new UpdateCheckResult(null, checkedAt, error ?? "最新版を取得できませんでした");
        }

        try
        {
            // 通信に失敗してキャッシュを使った場合も、Error は残して画面で理由を示します。
            return new UpdateCheckResult(ParseLatestRelease(payload, currentVersion), checkedAt, error);
        }
        catch (JsonException)
        {
            AppLog.Warning("アップデート確認: 応答を解釈できませんでした");
            return new UpdateCheckResult(null, checkedAt, "応答を解釈できませんでした");
        }
    }

    /// <summary>
    /// Release API のJSONを解析します。解析とバージョン比較だけを行う純粋な処理なので、
    /// ネットワークなしで自己診断（<c>--selftest-update</c>）から検証できます。
    /// </summary>
    public static UpdateRelease? ParseLatestRelease(string json, Version currentVersion)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        if (IsTrue(root, "draft") || IsTrue(root, "prerelease"))
        {
            // 下書きとプレリリースは配布対象外です。
            return null;
        }

        var tagName = GetString(root, "tag_name");
        if (!TryParseVersion(tagName, out var version))
        {
            return null;
        }

        if (!IsNewer(version, currentVersion))
        {
            return null;
        }

        string? assetName = null;
        string? downloadUrl = null;
        string? checksumsUrl = null;
        long downloadSize = 0;
        if (root.TryGetProperty("assets", out var assets) && assets.ValueKind == JsonValueKind.Array)
        {
            foreach (var asset in assets.EnumerateArray())
            {
                var name = GetString(asset, "name");
                var url = GetString(asset, "browser_download_url");
                if (string.IsNullOrEmpty(name) || string.IsNullOrEmpty(url))
                {
                    continue;
                }

                if (downloadUrl is null
                    && name.EndsWith(ExecutableSuffix, StringComparison.OrdinalIgnoreCase)
                    && name.StartsWith(ExecutablePrefix, StringComparison.OrdinalIgnoreCase))
                {
                    assetName = name;
                    downloadUrl = url;
                    downloadSize = GetInt64(asset, "size");
                }
                else if (checksumsUrl is null
                    && string.Equals(name, ChecksumsAssetName, StringComparison.OrdinalIgnoreCase))
                {
                    checksumsUrl = url;
                }
            }
        }

        return new UpdateRelease(
            version,
            tagName!,
            GetString(root, "body") ?? string.Empty,
            TryGetDateTimeOffset(root, "published_at"),
            GetString(root, "html_url") ?? ReleasesPageUrl,
            assetName,
            downloadUrl,
            downloadSize,
            checksumsUrl);
    }

    /// <summary>"v2.3.0.0" のようなタグを数値のバージョンに変換します。</summary>
    public static bool TryParseVersion(string? value, out Version version)
    {
        version = new Version(0, 0, 0, 0);
        if (string.IsNullOrWhiteSpace(value))
        {
            return false;
        }

        var text = value.Trim();
        if (text.StartsWith('v') || text.StartsWith('V'))
        {
            text = text[1..];
        }

        var length = 0;
        while (length < text.Length && (char.IsAsciiDigit(text[length]) || text[length] == '.'))
        {
            length++;
        }

        text = text[..length].TrimEnd('.');
        if (text.Length == 0)
        {
            return false;
        }

        var parts = text.Split('.');
        if (parts.Length > 4)
        {
            return false;
        }

        var numbers = new int[4];
        for (var index = 0; index < parts.Length; index++)
        {
            if (!int.TryParse(parts[index], NumberStyles.None, CultureInfo.InvariantCulture, out var number))
            {
                return false;
            }

            numbers[index] = number;
        }

        version = new Version(numbers[0], numbers[1], numbers[2], numbers[3]);
        return true;
    }

    public static bool IsNewer(Version? candidate, Version? current)
    {
        if (candidate is null || current is null)
        {
            return false;
        }

        // 2.3.0（リビジョン省略）と 2.3.0.0 を同じものとして扱います。
        return Normalize(candidate) > Normalize(current);
    }

    private static Version Normalize(Version version) =>
        new(
            version.Major,
            version.Minor,
            version.Build < 0 ? 0 : version.Build,
            version.Revision < 0 ? 0 : version.Revision);

    private static bool IsTrue(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;

    private static string? GetString(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        var text = value.GetString();
        return string.IsNullOrWhiteSpace(text) ? null : text;
    }

    private static long GetInt64(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.TryGetInt64(out var number) ? number : 0;

    private static DateTimeOffset? TryGetDateTimeOffset(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        return value.TryGetDateTimeOffset(out var parsed) ? parsed : null;
    }

    private sealed record StoredCache(DateTimeOffset FetchedAt, string Payload);

    private static StoredCache? TryReadCache(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return null;
            }

            using var document = JsonDocument.Parse(File.ReadAllText(path));
            if (!document.RootElement.TryGetProperty("fetchedAt", out var fetchedAt)
                || !fetchedAt.TryGetDateTimeOffset(out var parsed))
            {
                return null;
            }

            var payload = GetString(document.RootElement, "payload");
            return payload is null ? null : new StoredCache(parsed, payload);
        }
        catch (Exception exception) when (
            exception is IOException or JsonException or UnauthorizedAccessException or FormatException)
        {
            return null;
        }
    }

    private static void WriteCache(string path, DateTimeOffset fetchedAt, string payload)
    {
        try
        {
            var directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
            }

            var json = JsonSerializer.Serialize(
                new Dictionary<string, string>
                {
                    ["fetchedAt"] = fetchedAt.ToString("O", CultureInfo.InvariantCulture),
                    ["payload"] = payload,
                });
            File.WriteAllText(path, json);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // キャッシュは補助なので、書けなくても確認自体は成立します。
            AppLog.Warning($"アップデート確認: キャッシュを保存できません: {exception.GetType().Name}");
        }
    }
}

/// <summary>アップデート関連のHTTPクライアント（共通のヘッダーとタイムアウト）。</summary>
internal static class UpdateHttp
{
    internal static readonly HttpClient Client = Create();

    private static HttpClient Create()
    {
        var handler = new HttpClientHandler { AutomaticDecompression = DecompressionMethods.All };
        var client = new HttpClient(handler) { Timeout = TimeSpan.FromMinutes(5) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd(
            "ImageToPDF/" + AppLog.NumericVersion.ToString(4));
        client.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github+json");
        client.DefaultRequestHeaders.Add("X-GitHub-Api-Version", "2022-11-28");
        return client;
    }
}
