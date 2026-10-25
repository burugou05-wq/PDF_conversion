using System.Diagnostics;
using System.Globalization;
using System.Text.RegularExpressions;
using ImageToPDF.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;

namespace ImageToPDF.WinUI;

/// <summary>
/// バージョン表示をタップしたときに開く更新ダイアログです。
///
/// 現在のバージョン・更新の確認結果・リリースノートを表示し、新しい版があれば
/// 「更新する」で取得・検証・起動まで行います。開いたときに最新の状態を取り直すため、
/// 起動時の自動確認から時間が経っていても正しい情報が出ます。
/// </summary>
public sealed partial class UpdateDialog : ContentDialog
{
    /// <summary>開いたときに再確認するまでの猶予（これより古い情報は取り直します）。</summary>
    private static readonly TimeSpan FreshnessWindow = TimeSpan.FromMinutes(5);

    private static readonly Regex LinkPattern = new(@"https?://[^\s<>()]+", RegexOptions.Compiled);

    private readonly CancellationTokenSource _lifetime = new();
    private CancellationTokenSource? _download;
    private UpdateCheckResult? _check;
    private bool _busy;

    public UpdateDialog(UpdateCheckResult? initial)
    {
        // ハンドラーは XAML の読み込み前に用意します（x:Bind の初期化に間に合わせるため）。
        Closed += (_, _) => Cancel();
        Loaded += OnLoaded;
        InitializeComponent();

        Apply(initial);
    }

    /// <summary>このダイアログで最後に得られた確認結果です（呼び出し元のバッジ更新に使います）。</summary>
    public UpdateCheckResult? Result => _check;

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        var needsRefresh = _check is null
            || !_check.Succeeded
            || _check.CheckedAt is null
            || DateTimeOffset.UtcNow - _check.CheckedAt > FreshnessWindow;
        if (!needsRefresh || _busy)
        {
            return;
        }

        StatusText.Text = "最新のバージョンを確認しています…";
        try
        {
            var result = await UpdateChecker.FindLatestAsync(
                AppLog.NumericVersion, forceRefresh: true, _lifetime.Token);
            if (_busy)
            {
                // 確認中に「更新する」が押されていたら、表示は変えません。
                return;
            }

            _check = result;
            Apply(result);
        }
        catch (OperationCanceledException)
        {
            // ダイアログが閉じられました。
        }
        catch (Exception error)
        {
            AppLog.Warning($"アップデートの確認に失敗しました: {error.GetType().Name}: {error.Message}");
            StatusText.Text = "バージョンを確認できませんでした。";
        }
    }

    private void Apply(UpdateCheckResult? check)
    {
        _check = check;
        CurrentVersionText.Text = $"現在のバージョン: v{AppLog.ApplicationVersion}";
        StatusText.Text = BuildStatusText(check);
        NotesText.Blocks.Clear();

        if (check?.Release is { DownloadUrl: not null } release)
        {
            VersionSummaryText.Text = $"新しいバージョン v{release.TagName} があります";
            ReleaseInfoText.Text = string.Join(Environment.NewLine, DescribeRelease(release));
            NotesExpander.Visibility = Visibility.Visible;
            NotesExpander.IsExpanded = true;
            NotesExpander.Header = $"更新内容（{release.TagName}）";
            BuildNotes(release.Notes);
            OpenReleasesButton.Visibility = Visibility.Collapsed;
            PrimaryButtonText = "更新する";
            DownloadProgress.Visibility = Visibility.Collapsed;
            return;
        }

        VersionSummaryText.Text = check is { Succeeded: true }
            ? "最新のバージョンを使用しています"
            : "バージョンを確認できませんでした";
        ReleaseInfoText.Text = string.Empty;
        NotesExpander.Visibility = Visibility.Collapsed;
        // 更新があるとき以外は「更新する」を出しません（既定の空文字でボタンが隠れます）。
        PrimaryButtonText = string.Empty;
        OpenReleasesButton.Visibility = Visibility.Visible;
        DownloadProgress.Visibility = Visibility.Collapsed;
    }

    private static string BuildStatusText(UpdateCheckResult? check)
    {
        if (check is null)
        {
            return "GitHubのリリースを確認しています…";
        }

        var checkedAt = check.CheckedAt?.ToLocalTime().ToString(
            "yyyy/MM/dd HH:mm", CultureInfo.InvariantCulture);
        if (!check.Succeeded)
        {
            // 前回の情報が残っている場合は、その時刻を示して更新の有無を伝えます。
            var hint = checkedAt is null
                ? "インターネットに接続できるときに、もう一度お試しください。"
                : $"前回 {checkedAt} に確認した内容を表示しています。";
            return $"最新の状態を確認できませんでした（{check.Error ?? "理由不明"}）。"
                + Environment.NewLine
                + hint;
        }

        return checkedAt is null
            ? "GitHubのリリースを確認しました。"
            : $"GitHubのリリースを確認しました（{checkedAt}）。";
    }

    private static IEnumerable<string> DescribeRelease(UpdateRelease release)
    {
        if (release.PublishedAt is { } published)
        {
            yield return "公開日: "
                + published.ToLocalTime().ToString("yyyy/MM/dd HH:mm", CultureInfo.InvariantCulture);
        }

        if (release.DownloadSize > 0)
        {
            yield return "ダウンロードサイズ: "
                + (release.DownloadSize / (1024d * 1024d)).ToString("0.0", CultureInfo.InvariantCulture)
                + " MB";
        }

        yield return "インストーラーを取得し、SHA-256を照合してから自動で更新・再起動します。";
    }

    /// <summary>リリースノート（Markdown）を、見出しと本文の段落に分けて表示します。</summary>
    private void BuildNotes(string notes)
    {
        var text = string.IsNullOrWhiteSpace(notes) ? "更新内容は公開されていません。" : notes;
        foreach (var line in text.Replace("\r\n", "\n").Replace('\r', '\n').Split('\n'))
        {
            var trimmed = line.TrimStart();
            if (trimmed.StartsWith("```", StringComparison.Ordinal))
            {
                // コードブロックのフェンス自体は表示しません。
                continue;
            }

            if (IsHeading(trimmed))
            {
                var paragraph = new Paragraph();
                var bold = new Bold();
                bold.Inlines.Add(new Run { Text = trimmed.TrimStart('#', ' ') });
                paragraph.Inlines.Add(bold);
                NotesText.Blocks.Add(paragraph);
                continue;
            }

            AddTextBlock(line);
        }

        if (NotesText.Blocks.Count == 0)
        {
            NotesText.Blocks.Add(new Paragraph());
        }
    }

    private static bool IsHeading(string trimmedLine)
    {
        var level = 0;
        while (level < trimmedLine.Length && trimmedLine[level] == '#')
        {
            level++;
        }

        return level is >= 1 and <= 6 && level < trimmedLine.Length && trimmedLine[level] == ' ';
    }

    /// <summary>本文を追加します。段落内の URL はリンクにします。</summary>
    private void AddTextBlock(string text)
    {
        var normalized = text.TrimEnd();
        if (normalized.Length == 0)
        {
            // 空行は段落の区切りとしてのみ扱います。
            return;
        }

        var paragraph = new Paragraph();
        var position = 0;
        foreach (Match match in LinkPattern.Matches(normalized))
        {
            if (match.Index > position)
            {
                paragraph.Inlines.Add(new Run { Text = normalized[position..match.Index] });
            }

            // 文末の句読点は URL の一部ではないため、リンクから外します。
            var url = match.Value.TrimEnd('.', ',', '。', '、');
            var displayed = match.Value;
            if (url.Length < displayed.Length)
            {
                displayed = url;
            }

            var link = new Hyperlink();
            link.Inlines.Add(new Run { Text = displayed });
            link.Click += (_, _) => OpenUrl(url);
            paragraph.Inlines.Add(link);
            position = match.Index + url.Length;
        }

        if (position < normalized.Length)
        {
            paragraph.Inlines.Add(new Run { Text = normalized[position..] });
        }

        if (paragraph.Inlines.Count > 0)
        {
            NotesText.Blocks.Add(paragraph);
        }
    }

    private async void PrimaryButton_Click(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        if (_busy)
        {
            // ダウンロード中の「キャンセル」操作です。中止後も再試行できるよう、
            // ダイアログ自体のトークンではなく、このダウンロード用のトークンだけを止めます。
            args.Cancel = true;
            _download?.Cancel();
            return;
        }

        if (_check?.Release is not { } release)
        {
            return;
        }

        // ダイアログを閉じずに進捗を見せるため、既定のクローズを止めます。
        args.Cancel = true;
        // 中止しても再試行できるよう、ダウンロードごとに新しいトークンを作ります。
        var download = new CancellationTokenSource();
        _download = download;
        SetBusy(true);
        StatusText.Text = "ダウンロードしています…";
        try
        {
            var progress = new Progress<UpdateDownloadProgress>(report =>
            {
                DownloadProgress.Value = report.Fraction * 100;
                StatusText.Text = report.Total > 0
                    ? $"ダウンロード中… {report.Received / (1024d * 1024d):0.0} / "
                        + $"{report.Total / (1024d * 1024d):0.0} MB"
                    : $"ダウンロード中… {report.Received / (1024d * 1024d):0.0} MB";
            });

            var path = await UpdateDownloader.PrepareAsync(release, progress, download.Token);
            var directory = Path.GetDirectoryName(path);
            if (directory is not null)
            {
                UpdateDownloader.CleanUpPreviousDownloads(directory);
            }

            DownloadProgress.Value = 100;
            StatusText.Text = "検証が完了しました。更新して再起動します…";
            AppLog.Info($"アップデートを適用します: {release.TagName}");

            UpdateDownloader.Launch(path);
            // インストーラーが立ち上がってから、上書きできるようこのアプリを終了します。
            await Task.Delay(TimeSpan.FromMilliseconds(300));
            Application.Current.Exit();
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "ダウンロードを中止しました。";
            UpdateDownloader.DeleteDownloaded(release.TagName);
            SetBusy(false);
        }
        catch (Exception error)
        {
            AppLog.Warning($"アップデートに失敗しました: {error.GetType().Name}: {error.Message}");
            StatusText.Text = error.Message;
            SetBusy(false);
        }
        finally
        {
            if (ReferenceEquals(_download, download))
            {
                _download = null;
            }

            download.Dispose();
        }
    }

    private void SetBusy(bool isBusy)
    {
        _busy = isBusy;
        PrimaryButtonText = isBusy ? "キャンセル" : "更新する";
        CloseButtonText = isBusy ? string.Empty : "閉じる";
        IsPrimaryButtonEnabled = true;
        DownloadProgress.Visibility = isBusy ? Visibility.Visible : Visibility.Collapsed;
        DownloadProgress.Value = 0;
        if (!isBusy)
        {
            OpenReleasesButton.Visibility = Visibility.Visible;
        }
    }

    private void OpenReleasesButton_Click(object sender, RoutedEventArgs e)
    {
        OpenUrl(_check?.Release?.ReleasePageUrl ?? UpdateChecker.ReleasesPageUrl);
    }

    private static void OpenUrl(string url)
    {
        try
        {
            var startInfo = new ProcessStartInfo(url) { UseShellExecute = true };
            Process.Start(startInfo);
        }
        catch (Exception error) when (
            error is InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            AppLog.Warning($"ブラウザーを開けませんでした: {error.GetType().Name}");
        }
    }

    private void Cancel()
    {
        try
        {
            _lifetime.Cancel();
            _download?.Cancel();
        }
        catch (ObjectDisposedException)
        {
            // すでに破棄済みの場合は何もしません。
        }
    }
}
