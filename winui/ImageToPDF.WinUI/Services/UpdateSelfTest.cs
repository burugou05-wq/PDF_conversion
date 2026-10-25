using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace ImageToPDF.WinUI.Services;

/// <summary>
/// アップデート機能の自己診断（<c>--selftest-update &lt;ログ&gt;</c>）です。
///
/// ネットワークには接続せず、リリース応答の解析・バージョン比較・SHA-256照合・
/// 更新ダイアログの生成だけを確認します。ビルド検証（build_winui.ps1）から呼ばれます。
/// </summary>
public static class UpdateSelfTest
{
    public const string Flag = "--selftest-update";

    public static int Run(string logPath)
    {
        var lines = new List<string>();
        var passed = 0;
        var failed = 0;

        void Check(string name, Func<bool> test)
        {
            string detail;
            bool ok;
            try
            {
                ok = test();
                detail = string.Empty;
            }
            catch (Exception error)
            {
                ok = false;
                detail = $"例外: {error.GetType().Name}: {error.Message}";
            }

            if (ok)
            {
                passed++;
            }
            else
            {
                failed++;
            }

            lines.Add($"{(ok ? "OK" : "NG")}  {name}{(detail.Length == 0 ? string.Empty : $" — {detail}")}");
        }

        void CheckThrows(string name, Action action)
        {
            Check(name, () =>
            {
                try
                {
                    action();
                    return false;
                }
                catch (InvalidOperationException)
                {
                    return true;
                }
            });
        }

        var current = AppLog.NumericVersion;
        lines.Add($"current version: {current.ToString(4)} (raw={AppLog.ApplicationVersion})");

        // --- リリース応答の解析 -------------------------------------------------
        var newer = UpdateChecker.ParseLatestRelease(
            ReleaseJson("v9.9.9.0", prerelease: false, draft: false), current);
        Check("新しい版を検出する", () => newer is not null && newer.Version.ToString() == "9.9.9.0");
        Check("インストーラーのアセットを選ぶ", () => newer?.AssetName == "ImageToPDF-Setup-v9.9.9.0-Windows-x64.exe");
        Check(
            "インストーラー判定ができる",
            () => UpdateDownloader.IsInstaller("ImageToPDF-Setup-v9.9.9.0-Windows-x64.exe")
                && !UpdateDownloader.IsInstaller("ImageToPDF-v9.9.9.0-Windows-x64.exe"));
        Check(
            "チェックサムのアセットを選ぶ",
            () => newer?.ChecksumsUrl?.EndsWith("SHA256SUMS.txt", StringComparison.Ordinal) == true);
        Check("リリースノートを読む", () => newer?.Notes.Contains("テスト用のリリースノート", StringComparison.Ordinal) == true);
        Check("公開日を読む", () => newer?.PublishedAt is not null);
        Check("配布サイズを読む", () => newer?.DownloadSize == 123456789);
        Check("リリースページを読む", () => newer?.ReleasePageUrl.EndsWith("/v9.9.9.0", StringComparison.Ordinal) == true);
        Check(
            "同じ版は更新なし",
            () => UpdateChecker.ParseLatestRelease(
                ReleaseJson($"v{current.ToString(4)}", prerelease: false, draft: false), current) is null);
        Check(
            "プレリリースは無視する",
            () => UpdateChecker.ParseLatestRelease(
                ReleaseJson("v9.9.9.0", prerelease: true, draft: false), current) is null);
        Check(
            "下書きは無視する",
            () => UpdateChecker.ParseLatestRelease(
                ReleaseJson("v9.9.9.0", prerelease: false, draft: true), current) is null);
        Check(
            "タグが数値でなければ無視する",
            () => UpdateChecker.ParseLatestRelease(
                ReleaseJson("latest", prerelease: false, draft: false), current) is null);

        // --- バージョン比較 -----------------------------------------------------
        Check("タグの数値化 v1.2.3.4", () => UpdateChecker.TryParseVersion("v1.2.3.4", out var v)
            && v.ToString() == "1.2.3.4");
        Check("2要素のタグを4要素にそろえる", () => UpdateChecker.TryParseVersion("2.3", out var v2)
            && v2.ToString() == "2.3.0.0");
        Check("接尾辞つきのタグを数値部分で読む", () => UpdateChecker.TryParseVersion("v1.0-rc1", out var v3)
            && v3.ToString() == "1.0.0.0");
        Check("数値でないタグは失敗させる", () => !UpdateChecker.TryParseVersion("latest", out _));
        Check("空のタグは失敗させる", () => !UpdateChecker.TryParseVersion(null, out _));
        Check("2.3.0 は 2.2.0.0 より新しい",
            () => UpdateChecker.IsNewer(new Version(2, 3, 0), new Version(2, 2, 0, 0)));
        Check("2.2.0 と 2.2.0.0 は同じ",
            () => !UpdateChecker.IsNewer(new Version(2, 2, 0), new Version(2, 2, 0, 0)));
        Check("同じ版は新しくない",
            () => !UpdateChecker.IsNewer(new Version(2, 2, 0, 0), new Version(2, 2, 0, 0)));
        Check("古い版は新しくない",
            () => !UpdateChecker.IsNewer(new Version(2, 1, 1, 0), new Version(2, 2, 0, 0)));

        // --- SHA256SUMS の解析 --------------------------------------------------
        var hash = new string('a', 64);
        Check("sha256sum形式を読む",
            () => UpdateDownloader.FindChecksum($"{hash}  ImageToPDF-v9.9.9.0-Windows-x64.exe\n",
                "ImageToPDF-v9.9.9.0-Windows-x64.exe") == hash.ToUpperInvariant());
        Check("バイナリモード表記(*付き)を読む",
            () => UpdateDownloader.FindChecksum($"{hash} *app.exe\n", "app.exe") == hash.ToUpperInvariant());
        Check("記載のないファイルは null",
            () => UpdateDownloader.FindChecksum($"{hash}  other.exe\n", "app.exe") is null);
        Check("ハッシュ長が違えば null",
            () => UpdateDownloader.FindChecksum($"abc  app.exe\n", "app.exe") is null);

        // --- 実ファイルでの検証 -------------------------------------------------
        var directory = Path.Combine(
            Path.GetTempPath(), "ImageToPDF-UpdateSelfTest-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var assetName = "ImageToPDF-v9.9.9.0-Windows-x64.exe";
            var file = Path.Combine(directory, assetName);
            var payload = new byte[4096];
            payload[0] = (byte)'M';
            payload[1] = (byte)'Z';
            Random.Shared.NextBytes(payload.AsSpan(2));
            File.WriteAllBytes(file, payload);

            string actual;
            using (var stream = File.OpenRead(file))
            {
                actual = Convert.ToHexString(SHA256.HashData(stream));
            }

            var goodChecksums = $"{actual.ToLowerInvariant()}  {assetName}\n";
            Check("正しいハッシュで検証が通る", () =>
            {
                UpdateDownloader.Verify(file, assetName, goodChecksums);
                return File.Exists(file);
            });

            var badChecksums = $"{new string('b', 64)}  {assetName}\n";
            CheckThrows("ハッシュ不一致は中止する", () => UpdateDownloader.Verify(file, assetName, badChecksums));
            Check("検証に失敗したファイルは削除される", () => !File.Exists(file));

            File.WriteAllBytes(file, payload);
            CheckThrows("チェックサムに無いファイルは中止する",
                () => UpdateDownloader.Verify(file, assetName, $"{hash}  other.exe\n"));

            var notExecutable = Path.Combine(directory, "not-an-exe.exe");
            File.WriteAllText(notExecutable, "plain text");
            string notExecutableHash;
            using (var stream = File.OpenRead(notExecutable))
            {
                notExecutableHash = Convert.ToHexString(SHA256.HashData(stream));
            }

            CheckThrows("MZでないファイルは中止する",
                () => UpdateDownloader.Verify(notExecutable, "not-an-exe.exe", $"{notExecutableHash}  not-an-exe.exe\n"));

            var updatesRoot = Path.Combine(directory, "updates");
            var oldTagDir = Path.Combine(updatesRoot, "v2.3.0.1");
            var newTagDir = Path.Combine(updatesRoot, "v2.3.1.0");
            Directory.CreateDirectory(oldTagDir);
            Directory.CreateDirectory(newTagDir);
            File.WriteAllText(Path.Combine(oldTagDir, "dummy.exe"), "x");
            File.WriteAllText(Path.Combine(newTagDir, "dummy.exe"), "x");
            UpdateDownloader.CleanUpCompletedDownloads(runningDirectory: newTagDir, updatesRoot: updatesRoot);
            Check("updates内から起動中は自分のフォルダーを残す",
                () => !Directory.Exists(oldTagDir) && Directory.Exists(newTagDir));
            var installedDir = Path.Combine(directory, "Programs", "ImageToPDF");
            Directory.CreateDirectory(installedDir);
            UpdateDownloader.CleanUpCompletedDownloads(runningDirectory: installedDir, updatesRoot: updatesRoot);
            Check("インストール先から起動したらupdates内をすべて掃除する",
                () => !Directory.Exists(newTagDir));
        }
        finally
        {
            try
            {
                Directory.Delete(directory, recursive: true);
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            {
                // 一時フォルダーの掃除はベストエフォートです。
            }
        }

        Check("保存先のディレクトリ名を安全にする", () =>
        {
            foreach (var candidate in new[] { "v9.9.9.0", "v9.9.9.0/../../x", "..", ".", "", "a b:c" })
            {
                var name = UpdateDownloader.SafeDirectoryName(candidate);
                if (name.Length == 0 || name is "." or ".."
                    || name.Contains('/') || name.Contains('\\'))
                {
                    return false;
                }
            }

            return UpdateDownloader.SafeDirectoryName("v9.9.9.0") == "v9.9.9.0";
        });

        // --- ダイアログの生成（XAMLの読み込み確認） -----------------------------------
        Check("更新ダイアログを生成できる（更新あり）", () =>
        {
            var dialog = new UpdateDialog(new UpdateCheckResult(newer, DateTimeOffset.UtcNow, null));
            return dialog.Title is string title && title == "アップデート";
        });
        Check("更新ダイアログを生成できる（最新・確認失敗）", () =>
        {
            var dialog = new UpdateDialog(new UpdateCheckResult(null, null, "自己診断のため未確認"));
            return dialog.Title is string title && title == "アップデート";
        });

        lines.Add($"{passed} passed, {failed} failed");
        lines.Add(failed == 0 ? "update selftest ok" : "update selftest failed");
        try
        {
            File.WriteAllText(logPath, string.Join(Environment.NewLine, lines) + Environment.NewLine,
                new UTF8Encoding(false));
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // ログを書けなくても終了コードで伝わります。
        }

        return failed == 0 ? 0 : 1;
    }

    /// <summary>GitHub Release API の応答を模したJSONを作ります。</summary>
    internal static string ReleaseJson(string tag, bool prerelease, bool draft) =>
        string.Create(CultureInfo.InvariantCulture, $$"""
        {
          "tag_name": "{{tag}}",
          "name": "{{tag}} — テスト用のリリース",
          "draft": {{(draft ? "true" : "false")}},
          "prerelease": {{(prerelease ? "true" : "false")}},
          "published_at": "2026-10-18T09:54:20Z",
          "html_url": "https://github.com/burugou05-wq/PDF_conversion/releases/tag/{{tag}}",
          "body": "テスト用のリリースノートです。\r\n\r\n### 変更点\r\n\r\n- 箇条書きの1行目\r\n- 箇条書きの2行目 https://github.com/burugou05-wq/PDF_conversion\r\n",
          "assets": [
            {
              "name": "ImageToPDF-Setup-{{tag}}-Windows-x64.exe",
              "size": 123456789,
              "browser_download_url": "https://github.com/burugou05-wq/PDF_conversion/releases/download/{{tag}}/ImageToPDF-Setup-{{tag}}-Windows-x64.exe"
            },
            {
              "name": "SHA256SUMS.txt",
              "size": 103,
              "browser_download_url": "https://github.com/burugou05-wq/PDF_conversion/releases/download/{{tag}}/SHA256SUMS.txt"
            }
          ]
        }
        """);
}
