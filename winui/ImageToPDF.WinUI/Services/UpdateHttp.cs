using System.Net;
using System.Net.Http;

namespace ImageToPDF.WinUI.Services;

/// <summary>
/// アップデート用の共通 HTTP クライアント。
///
/// - <c>HttpClient.Timeout</c> は使いません。<c>ResponseHeadersRead</c> の場合、本体の
///   <c>ReadAsync</c> にはタイムアウトが及ばないため、呼び出し側が無通信タイムアウトを
///   管理します（<see cref="UpdateDownloader"/>）。
/// - <c>update-cache.json</c> はユーザーが書き換えられるため、URL のホストを許可リストに
///   限定します。自動リダイレクトを無効にし、1ホップごとにホストを検査します。
/// </summary>
internal static class UpdateHttp
{
    /// <summary>起動時の Release API 確認（ヘッダー＋本文）のタイムアウト。</summary>
    internal static readonly TimeSpan ApiTimeout = TimeSpan.FromSeconds(15);

    /// <summary>インストーラーのレスポンスヘッダーを待つタイムアウト。</summary>
    internal static readonly TimeSpan HeaderTimeout = TimeSpan.FromSeconds(30);

    /// <summary>インストーラー本体の無通信タイムアウト（読み込みごとに延長）。</summary>
    internal static readonly TimeSpan InactivityTimeout = TimeSpan.FromSeconds(60);

    /// <summary>チェックサム・署名など小さいファイル全体のタイムアウト。</summary>
    internal static readonly TimeSpan MetadataTimeout = TimeSpan.FromSeconds(30);

    private const int MaxRedirects = 5;
    private const string GitHubHost = "github.com";
    private const string GitHubApiHost = "api.github.com";
    private const string UserContentSuffix = ".githubusercontent.com";
    private const string ObjectsHost = "objects.githubusercontent.com";

    internal static readonly HttpClient Client = Create();

    private static HttpClient Create()
    {
        var handler = new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.All,
            // リダイレクト先も検査するため、HttpClient の自動追跡は使いません。
            AllowAutoRedirect = false,
        };
        var client = new HttpClient(handler)
        {
            // タイムアウトはすべて呼び出し側の CancellationTokenSource で管理します。
            Timeout = System.Threading.Timeout.InfiniteTimeSpan,
        };
        client.DefaultRequestHeaders.UserAgent.ParseAdd(
            "ImageToPDF/" + AppLog.NumericVersion.ToString(4));
        client.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github+json");
        client.DefaultRequestHeaders.Add("X-GitHub-Api-Version", "2022-11-28");
        return client;
    }

    /// <summary>Release API（api.github.com）の応答を取得します。</summary>
    internal static Task<HttpResponseMessage> GetApiAsync(
        string url, CancellationToken cancellationToken) =>
        GetAsync(url, HttpCompletionOption.ResponseContentRead, cancellationToken, isReleaseAsset: false);

    /// <summary>配布ファイル（github.com の Release）を取得します。</summary>
    internal static Task<HttpResponseMessage> GetAssetAsync(
        string url,
        HttpCompletionOption completion,
        CancellationToken cancellationToken) =>
        GetAsync(url, completion, cancellationToken, isReleaseAsset: true);

    /// <summary>キャッシュから来た URL が GitHub の配布ホストかどうかを判定します。</summary>
    internal static bool IsAllowedAssetUrl(string? url)
    {
        try
        {
            RequireAllowedHost(ParseUrl(url), isReleaseAsset: true, isRedirect: false);
            return true;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    private static async Task<HttpResponseMessage> GetAsync(
        string url,
        HttpCompletionOption completion,
        CancellationToken cancellationToken,
        bool isReleaseAsset)
    {
        var current = ParseUrl(url);
        RequireAllowedHost(current, isReleaseAsset, isRedirect: false);

        for (var hops = 0; ; hops++)
        {
            if (hops > MaxRedirects)
            {
                throw new InvalidOperationException("配布ファイルのリダイレクトが多すぎます。");
            }

            using var request = new HttpRequestMessage(HttpMethod.Get, current);
            var response = await Client.SendAsync(request, completion, cancellationToken);
            if (!IsRedirect(response.StatusCode))
            {
                return response;
            }

            var location = response.Headers.Location;
            response.Dispose();
            if (location is null)
            {
                throw new InvalidOperationException("配布ファイルのリダイレクト先が不明です。");
            }

            // GitHub は Release のダウンロードを objects.githubusercontent.com 等へ
            // リダイレクトします。相対 Location は現在の URL を基準に解決します。
            current = location.IsAbsoluteUri ? location : new Uri(current, location);
            RequireAllowedHost(current, isReleaseAsset, isRedirect: true);
        }
    }

    private static Uri ParseUrl(string? url)
    {
        if (string.IsNullOrWhiteSpace(url)
            || !Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            throw new InvalidOperationException("更新ファイルの URL が正しくありません。");
        }

        return uri;
    }

    private static bool IsRedirect(HttpStatusCode status) =>
        (int)status is 301 or 302 or 303 or 307 or 308;

    private static void RequireAllowedHost(Uri uri, bool isReleaseAsset, bool isRedirect)
    {
        if (uri.Scheme != Uri.UriSchemeHttps || uri.Port != 443 || uri.UserInfo.Length != 0)
        {
            throw new InvalidOperationException(
                "更新ファイルの取得は HTTPS 経由の GitHub に限定しています。");
        }

        var host = uri.Host.ToLowerInvariant();
        if (!isReleaseAsset)
        {
            if (host != GitHubApiHost)
            {
                throw new InvalidOperationException("更新確認の通信先が正しくありません。");
            }

            return;
        }

        // 最初の URL は github.com だけ（API 応答を書き換えられても他ホストへ送らない）。
        // リダイレクト先は GitHub の配信ホストに限定します。
        var allowed = host == GitHubHost
            || (isRedirect
                && (host.EndsWith(UserContentSuffix, StringComparison.Ordinal)
                    || host == ObjectsHost));
        if (!allowed)
        {
            throw new InvalidOperationException(
                "更新ファイルの取得先が GitHub ではありません。更新を中止しました。");
        }
    }
}
