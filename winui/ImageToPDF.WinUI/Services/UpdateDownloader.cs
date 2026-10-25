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
/// 新しいインストーラー（またはEXE）の取得と検証、起動までを受け持ちます。
///
/// 更新は次の順で行います。
/// 1. 新しいインストーラーと <c>SHA256SUMS.txt</c> を <c>%LOCALAPPDATA%\ImageToPDF\updates\&lt;tag&gt;\</c> へ保存
/// 2. サイズとSHA-256を照合（一致しなければ削除して中止）
/// 3. PE形式（MZ）を確認してからサイレント更新引数つきでインストーラーを起動し、このアプリを終了
/// 4. 更新後の再起動時に <c>updates\</c> 内のインストーラーを自動削除
///
/// 失敗しても現在のアプリはそのまま使い続けられます。
/// </summary>
public static class UpdateDownloader
{
    public const string SilentInstallArguments =
        "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /AUTOLAUNCH=1";

    private const string InstallerPrefix = "ImageToPDF-Setup-";
    private const string ChecksumsAssetName = "SHA256SUMS.txt";

    /// <summary>このアプリの更新ファイルを置くフォルダー。</summary>
    public static string UpdatesDirectory => Path.Combine(AppLog.DataDirectory, "updates");

    /// <summary>配布ファイルがインストーラー（ImageToPDF-Setup-*.exe）かどうかを判定します。</summary>
    public static bool IsInstaller(string path) =>
        Path.GetFileName(path).StartsWith(InstallerPrefix, StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// 新しいEXEを取得して検証します。戻り値は検証済みEXEのフルパスです。
    /// </summary>
    public static async Task<string> PrepareAsync(
        UpdateRelease release,
        IProgress<UpdateDownloadProgress>? progress,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrEmpty(release.DownloadUrl) || string.IsNullOrEmpty(release.AssetName))
        {
            throw new InvalidOperationException("配布ファイルが見つかりません。リリースページから取得してください。");
        }

        if (string.IsNullOrEmpty(release.ChecksumsUrl))
        {
            // 照合できない配布物は起動しない方針です（Releaseには常に同梱されています）。
            throw new InvalidOperationException(
                "チェックサムが公開されていないため、安全のため更新を中止しました。");
        }

        var directory = Path.Combine(UpdatesDirectory, SafeDirectoryName(release.TagName));
        Directory.CreateDirectory(directory);
        var target = Path.Combine(directory, release.AssetName);

        AppLog.Info($"アップデートを取得します: {release.TagName} ({release.AssetName})");
        await DownloadAsync(release.DownloadUrl, target, release.DownloadSize, progress, cancellationToken);

        var checksums = await DownloadTextAsync(release.ChecksumsUrl, cancellationToken);
        Verify(target, release.AssetName, checksums);
        AppLog.Info($"アップデートの検証が完了しました: {target}");
        return target;
    }

    /// <summary>
    /// 検証済みのインストーラー（またはEXE）を起動します。
    /// インストーラーの場合はサイレント更新＋自動再起動の引数を渡します。
    /// </summary>
    public static void Launch(string executablePath)
    {
        var isInstaller = IsInstaller(executablePath);
        var startInfo = new ProcessStartInfo(executablePath)
        {
            Arguments = isInstaller ? SilentInstallArguments : string.Empty,
            UseShellExecute = true,
            WorkingDirectory = Path.GetDirectoryName(executablePath) ?? AppContext.BaseDirectory,
        };
        Process.Start(startInfo);
        AppLog.Info(
            isInstaller
                ? $"更新インストーラーを起動しました: {executablePath} {SilentInstallArguments}"
                : $"新しいバージョンを起動しました: {executablePath}");
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

    private static async Task DownloadAsync(
        string url,
        string path,
        long expectedSize,
        IProgress<UpdateDownloadProgress>? progress,
        CancellationToken cancellationToken)
    {
        var partial = path + ".part";
        try
        {
            using var response = await UpdateHttp.Client.GetAsync(
                url, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                throw new InvalidOperationException(
                    $"配布ファイルを取得できませんでした（HTTP {(int)response.StatusCode}）。");
            }

            var total = response.Content.Headers.ContentLength ?? expectedSize;
            progress?.Report(new UpdateDownloadProgress(0, total));

            using var input = await response.Content.ReadAsStreamAsync(cancellationToken);
            using (var output = new FileStream(
                       partial, FileMode.Create, FileAccess.Write, FileShare.None, 81920, useAsync: true))
            {
                var buffer = new byte[81920];
                long received = 0;
                int read;
                while ((read = await input.ReadAsync(buffer, cancellationToken)) > 0)
                {
                    await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
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
    }

    private static async Task<string> DownloadTextAsync(string url, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await UpdateHttp.Client.GetAsync(url, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                throw new InvalidOperationException(
                    $"チェックサムを取得できませんでした（HTTP {(int)response.StatusCode}）。");
            }

            return await response.Content.ReadAsStringAsync(cancellationToken);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new InvalidOperationException("チェックサムの取得がタイムアウトしました。", null);
        }
        catch (Exception exception) when (exception is HttpRequestException or IOException)
        {
            throw new InvalidOperationException("チェックサムを取得できませんでした。", exception);
        }
    }

    /// <summary>
    /// サイズ・SHA-256・PE形式を確認します。1つでも合わなければファイルを削除して例外にします。
    /// </summary>
    public static void Verify(string path, string assetName, string checksumsText)
    {
        var info = new FileInfo(path);
        if (!info.Exists || info.Length == 0)
        {
            throw new InvalidOperationException("配布ファイルを保存できませんでした。");
        }

        var expected = FindChecksum(checksumsText, assetName);
        if (expected is null)
        {
            DeleteQuietly(path);
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
            DeleteQuietly(path);
            AppLog.Warning($"アップデートの検証に失敗しました: 期待 {expected} / 実際 {actual}");
            throw new InvalidOperationException(
                "ダウンロードしたファイルの検証に失敗しました。更新を中止しました。");
        }

        Span<byte> signature = stackalloc byte[2];
        using (var stream = File.OpenRead(path))
        {
            if (stream.Read(signature) != signature.Length)
            {
                DeleteQuietly(path);
                throw new InvalidOperationException("配布ファイルが壊れています。更新を中止しました。");
            }
        }

        if (signature[0] != (byte)'M' || signature[1] != (byte)'Z')
        {
            DeleteQuietly(path);
            throw new InvalidOperationException(
                "配布ファイルが実行ファイルではありません。更新を中止しました。");
        }
    }

    /// <summary>
    /// <c>SHA256SUMS.txt</c>（<c>&lt;hex&gt;  &lt;file&gt;</c>、sha256sum形式）から
    /// 指定ファイルのハッシュを取り出します。
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
