using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;

namespace ImageToPDF.WinUI.Services;

/// <summary>ダウンロードの進捗（ダウンロード済みバイト数と全体のバイト数）。</summary>
public sealed record UpdateDownloadProgress(long Received, long Total)
{
    public double Fraction => Total > 0 ? Math.Clamp((double)Received / Total, 0, 1) : 0;
}

/// <summary>
/// インストーラーの取得と検証、起動までを受け持ちます。
///
/// 更新は次の順で行います。
/// 1. URL・タグ名・アセット名を検証し、インストーラー / <c>SHA256SUMS.txt</c> /
///    <c>SHA256SUMS.txt.sig</c> を <c>%LOCALAPPDATA%\ImageToPDF\updates\&lt;tag&gt;\</c> へ保存
/// 2. <c>SHA256SUMS.txt</c> の電子署名をアプリ内蔵の公開鍵で検証し、記載された
///    バージョン（<c># tag:</c>）がリリースのタグと一致することを確認
/// 3. サイズと SHA-256 を照合（破損の検出）。MZ ヘッダーも形式チェックとして確認
/// 4. サイレント更新引数つきでインストーラーを起動し、このアプリを終了
/// 5. 更新後の再起動時に <c>updates\</c> 内のインストーラーを自動削除
///
/// 失敗しても現在のアプリはそのまま使い続けられます。
/// </summary>
public static class UpdateDownloader
{
    public const string SilentInstallArguments =
        "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /AUTOLAUNCH=1";

    private const string InstallerPrefix = "ImageToPDF-Setup-";
    private const string TagHeader = "# tag:";

    /// <summary>チェックサム／署名ファイルの上限（大きすぎる応答でメモリを消費しない）。</summary>
    private const int MaxChecksumsBytes = 64 * 1024;
    private const int MaxSignatureBytes = 1024;

    /// <summary>このアプリの更新ファイルを置くフォルダー。</summary>
    public static string UpdatesDirectory => Path.Combine(AppLog.DataDirectory, "updates");

    /// <summary>配布ファイルがインストーラー（ImageToPDF-Setup-*.exe）かどうかを判定します。</summary>
    public static bool IsInstaller(string path) =>
        Path.GetFileName(path).StartsWith(InstallerPrefix, StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// 新しいインストーラーを取得して検証します。戻り値は検証済みEXEのフルパスです。
    /// </summary>
    public static async Task<string> PrepareAsync(
        UpdateRelease release,
        IProgress<UpdateDownloadProgress>? progress,
        CancellationToken cancellationToken)
    {
        if (!ReleaseSignature.IsConfigured)
        {
            // 鍵が未設定のビルドでは、署名を検証できない更新を実行しません。
            throw new InvalidOperationException(
                "署名検証用の公開鍵が設定されていません。リリースページから手動で更新してください。");
        }

        var assetName = release.AssetName;
        var downloadUrl = release.DownloadUrl;
        var checksumsUrl = release.ChecksumsUrl;
        var signatureUrl = release.SignatureUrl;
        if (string.IsNullOrEmpty(downloadUrl)
            || string.IsNullOrEmpty(assetName)
            || !IsInstaller(assetName))
        {
            throw new InvalidOperationException(
                "署名済みのインストーラーが見つかりません。リリースページから手動で更新してください。");
        }

        if (string.IsNullOrEmpty(checksumsUrl) || string.IsNullOrEmpty(signatureUrl))
        {
            // 署名を検証できない配布物は起動しない方針です。
            throw new InvalidOperationException(
                "署名付きチェックサムが公開されていないため、安全のため更新を中止しました。");
        }

        // update-cache.json はユーザーが書き換えられるので、ここでも URL を検査します。
        RequireTrustedUrl(downloadUrl, release.TagName, assetName);
        RequireTrustedUrl(checksumsUrl, release.TagName, "SHA256SUMS.txt");
        RequireTrustedUrl(signatureUrl, release.TagName, ReleaseSignature.SignatureAssetName);

        var directory = Path.Combine(UpdatesDirectory, SafeDirectoryName(release.TagName));
        Directory.CreateDirectory(directory);
        var target = Path.Combine(directory, assetName);

        AppLog.Info($"アップデートを取得します: {release.TagName} ({assetName})");
        await DownloadAsync(downloadUrl, target, release.DownloadSize, progress, cancellationToken);

        try
        {
            var checksums = await DownloadBytesAsync(
                checksumsUrl, MaxChecksumsBytes, "チェックサム", cancellationToken);
            var signature = await DownloadBytesAsync(
                signatureUrl, MaxSignatureBytes, "署名", cancellationToken);
            Verify(target, assetName, checksums, signature, release.TagName);
        }
        catch
        {
            // 署名・ハッシュの検証に失敗したファイルを残しません。
            DeleteDownloaded(release.TagName);
            throw;
        }

        AppLog.Info($"アップデートの署名と検証が完了しました: {target}");
        return target;
    }

    /// <summary>
    /// 検証済みのインストーラーを起動します。単体 EXE 版（v2.3.0.x）の起動経路は廃止しました。
    /// </summary>
    public static void Launch(string executablePath)
    {
        if (!IsInstaller(executablePath))
        {
            throw new InvalidOperationException(
                "更新はインストーラーでのみ実行できます。リリースページから手動で更新してください。");
        }

        var startInfo = new ProcessStartInfo(executablePath)
        {
            Arguments = SilentInstallArguments,
            UseShellExecute = true,
            WorkingDirectory = Path.GetDirectoryName(executablePath) ?? AppContext.BaseDirectory,
        };
        Process.Start(startInfo);
        AppLog.Info($"更新インストーラーを起動しました: {executablePath} {SilentInstallArguments}");
    }

    /// <summary>更新ファイルの保存先に使うディレクトリ名（タグ名を安全な文字だけにします）。</summary>
    public static string SafeDirectoryName(string tagName)
    {
        var builder = new StringBuilder(tagName.Length);
        foreach (var character in tagName)
        {
            builder.Append(char.IsAsciiLetterOrDigit(character) || character is '.' or '-' or '_'
                ? character
                : '_');
        }

        var name = builder.ToString().Trim('.');
        return name.Length == 0 ? "latest" : name;
    }

    /// <summary>古い版のダウンロードを残さないよう、今回の保存先以外を削除します。</summary>
    public static void CleanUpPreviousDownloads(string keepDirectory)
    {
        CleanUpCompletedDownloads(runningDirectory: keepDirectory, updatesRoot: UpdatesDirectory);
    }

    /// <summary>
    /// インストール先から起動しているとき、更新用の一時フォルダー（updates\）に残った
    /// インストーラー等を削除します。updates\ 内から直接起動している場合だけ、そのフォルダーを残します。
    /// </summary>
    public static void CleanUpCompletedDownloads(
        string? runningDirectory = null,
        string? updatesRoot = null)
    {
        try
        {
            var root = Path.GetFullPath(updatesRoot ?? UpdatesDirectory);
            if (!Directory.Exists(root))
            {
                return;
            }

            var current = Path.GetFullPath(runningDirectory ?? AppContext.BaseDirectory)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            foreach (var directory in Directory.EnumerateDirectories(root))
            {
                var full = Path.GetFullPath(directory)
                    .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                if (string.Equals(current, full, StringComparison.OrdinalIgnoreCase)
                    || current.StartsWith(
                        full + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                Directory.Delete(directory, recursive: true);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // インストーラー終了直後でロックされている場合は次回起動時に削除します。
        }
    }

    private static void RequireTrustedUrl(string? url, string tagName, string assetName)
    {
        if (!UpdateChecker.IsTrustedAssetUrl(url, tagName, assetName))
        {
            AppLog.Warning("アップデートを中止しました: 配布ファイルの URL が信頼できません");
            throw new InvalidOperationException(
                "配布ファイルの取得先が正しくありません。リリースページから手動で更新してください。");
        }
    }

    private static async Task DownloadAsync(
        string url,
        string path,
        long expectedSize,
        IProgress<UpdateDownloadProgress>? progress,
        CancellationToken cancellationToken)
    {
        var partial = path + ".part";
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        try
        {
            // ヘッダー待ちと本体の無通信は別々に計測します。CancelAfter は ReadAsync の
            // たびに呼び直すため、低速な回線でも途中で切れません。
            timeout.CancelAfter(UpdateHttp.HeaderTimeout);
            using var response = await UpdateHttp.GetAssetAsync(
                url, HttpCompletionOption.ResponseHeadersRead, timeout.Token);
            if (!response.IsSuccessStatusCode)
            {
                throw new InvalidOperationException(
                    $"配布ファイルを取得できませんでした（HTTP {(int)response.StatusCode}）。");
            }

            var total = response.Content.Headers.ContentLength ?? expectedSize;
            progress?.Report(new UpdateDownloadProgress(0, total));

            using var input = await response.Content.ReadAsStreamAsync(timeout.Token);
            using (var output = new FileStream(
                       partial, FileMode.Create, FileAccess.Write, FileShare.None, 81920, useAsync: true))
            {
                var buffer = new byte[81920];
                long received = 0;
                while (true)
                {
                    timeout.CancelAfter(UpdateHttp.InactivityTimeout);
                    var read = await input.ReadAsync(buffer.AsMemory(), timeout.Token);
                    if (read == 0)
                    {
                        break;
                    }

                    await output.WriteAsync(buffer.AsMemory(0, read), timeout.Token);
                    received += read;
                    progress?.Report(new UpdateDownloadProgress(received, total));
                }
            }

            if (expectedSize > 0 && new FileInfo(partial).Length != expectedSize)
            {
                throw new InvalidOperationException("配布ファイルのサイズが公開情報と一致しません。");
            }

            File.Move(partial, path, overwrite: true);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            DeleteQuietly(partial);
            throw new InvalidOperationException("ダウンロードがタイムアウトしました。", null);
        }
        catch (OperationCanceledException)
        {
            DeleteQuietly(partial);
            throw;
        }
        catch (Exception exception) when (exception is HttpRequestException or IOException)
        {
            DeleteQuietly(partial);
            throw new InvalidOperationException("配布ファイルを取得できませんでした。", exception);
        }
        catch
        {
            DeleteQuietly(partial);
            throw;
        }
    }

    private static async Task<byte[]> DownloadBytesAsync(
        string url,
        int maxBytes,
        string label,
        CancellationToken cancellationToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(UpdateHttp.MetadataTimeout);
        try
        {
            using var response = await UpdateHttp.GetAssetAsync(
                url, HttpCompletionOption.ResponseContentRead, timeout.Token);
            if (!response.IsSuccessStatusCode)
            {
                throw new InvalidOperationException(
                    $"{label}を取得できませんでした（HTTP {(int)response.StatusCode}）。");
            }

            if (response.Content.Headers.ContentLength > maxBytes)
            {
                throw new InvalidOperationException($"{label}のサイズが大きすぎます。");
            }

            var bytes = await response.Content.ReadAsByteArrayAsync(timeout.Token);
            if (bytes.Length == 0 || bytes.Length > maxBytes)
            {
                throw new InvalidOperationException($"{label}のサイズが正しくありません。");
            }

            return bytes;
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new InvalidOperationException($"{label}の取得がタイムアウトしました。", null);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception) when (exception is HttpRequestException or IOException)
        {
            throw new InvalidOperationException($"{label}を取得できませんでした。", exception);
        }
    }

    /// <summary>
    /// 署名 → タグ → サイズ・SHA-256 → MZ 形式を確認します。1つでも合わなければ
    /// ファイルを削除して例外にします。
    /// </summary>
    public static void Verify(
        string path,
        string assetName,
        byte[] checksums,
        byte[] signature,
        string tagName) =>
        Verify(path, assetName, checksums, signature, tagName,
            ReleaseSignature.SubjectPublicKeyInfoBase64);

    /// <summary>
    /// 自己診断用の overload。公開鍵を差し替えて検証できます（通常の更新では使いません）。
    /// </summary>
    internal static void Verify(
        string path,
        string assetName,
        byte[] checksums,
        byte[] signature,
        string tagName,
        string publicKeyBase64)
    {
        try
        {
            // ハッシュ照合より先に、チェックサムファイル自体の真正性を確認します。
            ReleaseSignature.Verify(checksums, signature, publicKeyBase64);
            var checksumsText = Encoding.UTF8.GetString(checksums);
            VerifyChecksumsTag(checksumsText, tagName);
            VerifyChecksum(path, assetName, checksumsText);
            VerifyPeHeader(path);
        }
        catch
        {
            DeleteQuietly(path);
            throw;
        }
    }

    /// <summary>
    /// 署名済みチェックサムに書かれたタグと、Release のタグを照合します。
    /// これにより、正規の古い Assets を使ったダウングレードを防ぎます。
    /// </summary>
    private static void VerifyChecksumsTag(string checksumsText, string tagName)
    {
        foreach (var rawLine in checksumsText.Split('\n'))
        {
            var line = rawLine.Trim().TrimStart('\uFEFF').TrimEnd('\r');
            if (!line.StartsWith(TagHeader, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var declared = line[TagHeader.Length..].Trim();
            if (!string.Equals(declared, tagName, StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "チェックサムに記載されたバージョンが一致しません。更新を中止しました。");
            }

            return;
        }

        throw new InvalidOperationException(
            "チェックサムにバージョンの記載がないため、更新を中止しました。");
    }

    private static void VerifyChecksum(string path, string assetName, string checksumsText)
    {
        var info = new FileInfo(path);
        if (!info.Exists || info.Length == 0)
        {
            throw new InvalidOperationException("配布ファイルを保存できませんでした。");
        }

        var expected = FindChecksum(checksumsText, assetName);
        if (expected is null)
        {
            throw new InvalidOperationException(
                "チェックサムに配布ファイルの記載がないため、更新を中止しました。");
        }

        string actual;
        using (var stream = File.OpenRead(path))
        {
            actual = Convert.ToHexString(SHA256.HashData(stream));
        }

        if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
        {
            AppLog.Warning($"アップデートの検証に失敗しました: 期待 {expected} / 実際 {actual}");
            throw new InvalidOperationException(
                "ダウンロードしたファイルの検証に失敗しました。更新を中止しました。");
        }
    }

    /// <summary>
    /// MZ ヘッダーの確認は形式チェック（破損の早期検出）です。SHA-256 が一致した後では
    /// セキュリティ上の意味はなく、真正性は署名検証が担います。
    /// </summary>
    private static void VerifyPeHeader(string path)
    {
        Span<byte> signature = stackalloc byte[2];
        using (var stream = File.OpenRead(path))
        {
            if (stream.Read(signature) != signature.Length)
            {
                throw new InvalidOperationException("配布ファイルが壊れています。更新を中止しました。");
            }
        }

        if (signature[0] != (byte)'M' || signature[1] != (byte)'Z')
        {
            throw new InvalidOperationException(
                "配布ファイルが実行ファイルではありません。更新を中止しました。");
        }
    }

    /// <summary>
    /// <c>SHA256SUMS.txt</c>（<c>&lt;hex&gt;  &lt;file&gt;</c>、sha256sum形式）から
    /// 指定ファイルのハッシュを取り出します。<c>#</c> で始まる行は無視します。
    /// </summary>
    public static string? FindChecksum(string checksumsText, string assetName)
    {
        foreach (var rawLine in checksumsText.Split('\n'))
        {
            var line = rawLine.Trim().TrimStart('\uFEFF');
            if (line.Length == 0 || line.StartsWith('#'))
            {
                continue;
            }

            var separator = line.IndexOfAny(new[] { ' ', '\t' });
            if (separator <= 0)
            {
                continue;
            }

            var hash = line[..separator];
            var name = line[(separator + 1)..].TrimStart();
            if (name.StartsWith('*'))
            {
                // sha256sum のバイナリモード表記（"<hash> *<file>"）。
                name = name[1..];
            }

            if (!string.Equals(name, assetName, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            return hash.Length == 64 && hash.All(Uri.IsHexDigit)
                ? hash.ToUpperInvariant()
                : null;
        }

        return null;
    }

    /// <summary>ダウンロード済みの更新ファイルを削除します（中止時・後片付け用）。</summary>
    public static void DeleteDownloaded(string tagName)
    {
        try
        {
            var directory = Path.Combine(UpdatesDirectory, SafeDirectoryName(tagName));
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // 削除できなくても次回の更新で上書きされます。
        }
    }

    private static void DeleteQuietly(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // 消せない一時ファイルは次回の更新で上書きされます。
        }
    }
}
