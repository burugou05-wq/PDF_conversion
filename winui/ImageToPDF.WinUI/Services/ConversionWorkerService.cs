using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace ImageToPDF.WinUI.Services;

/// <summary>
/// Talks to a resident conversion worker over JSON lines on its stdio.
///
/// The worker process (ConversionWorker server mode) is started once and kept
/// alive, so thumbnails and conversions no longer pay the interpreter or EXE
/// startup cost per request. Requests are multiplexed by id; progress events
/// are dispatched to the originating caller while other requests are in
/// flight. The worker is placed in a Job Object with
/// JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE so it cannot outlive the app even when
/// the app itself crashes.
/// </summary>
public sealed class ConversionWorkerService : IDisposable
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly object _gate = new();
    private readonly object _stdinGate = new();
    private readonly Dictionary<string, PendingRequest> _pending = new();
    private Process? _process;
    private IntPtr _jobHandle;
    private bool _disposed;

    public async Task<WorkerMessage> RunAsync(
        WorkerRequest request,
        IProgress<WorkerMessage>? progress,
        CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        cancellationToken.ThrowIfCancellationRequested();

        var worker = EnsureWorkerRunning();
        var requestId = Guid.NewGuid().ToString("N");
        var completion = new TaskCompletionSource<WorkerMessage>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        lock (_gate)
        {
            _pending[requestId] = new PendingRequest(worker, completion, progress);
        }

        try
        {
            using var cancellationRegistration = cancellationToken.Register(() =>
                TryWriteLine("{\"type\":\"cancel\",\"id\":\"" + requestId + "\"}"));
            TryWriteLine(SerializeRequest(request, requestId));
            return await completion.Task.WaitAsync(cancellationToken);
        }
        finally
        {
            lock (_gate)
            {
                _pending.Remove(requestId);
            }
        }
    }

    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            FailPendingRequests("変換ワーカーを停止しました。");
            ShutdownWorker();
        }

        GC.SuppressFinalize(this);
    }

    private static string SerializeRequest(WorkerRequest request, string requestId)
    {
        var payload = JsonSerializer.SerializeToNode(request, JsonOptions)!.AsObject();
        payload["id"] = requestId;
        return payload.ToJsonString(JsonOptions)!;
    }

    private Process EnsureWorkerRunning()
    {
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_process is not null)
            {
                try
                {
                    if (!_process.HasExited)
                    {
                        return _process;
                    }
                }
                catch (InvalidOperationException)
                {
                    // The process object lost its handle; restart below.
                }
            }

            ShutdownWorker();
            var process = new Process { StartInfo = CreateStartInfo() };
            if (!process.Start())
            {
                process.Dispose();
                throw new InvalidOperationException("変換ワーカーを起動できませんでした。");
            }

            AssignToKillOnCloseJob(process);
            _process = process;
            _ = Task.Run(() => ReadStandardOutputLoop(process));
            _ = Task.Run(async () =>
            {
                try
                {
                    // Drain stderr continuously so the pipe can never fill up
                    // and block the worker.
                    await process.StandardError.ReadToEndAsync();
                }
                catch (Exception)
                {
                    // The worker has exited; nothing left to drain.
                }
            });
            return process;
        }
    }

    private void ReadStandardOutputLoop(Process process)
    {
        try
        {
            while (await process.StandardOutput.ReadLineAsync() is { } line)
            {
                WorkerMessage? message;
                try
                {
                    message = JsonSerializer.Deserialize<WorkerMessage>(line, JsonOptions);
                }
                catch (JsonException)
                {
                    continue;
                }

                if (message?.Id is null)
                {
                    continue;
                }

                PendingRequest? pending;
                lock (_gate)
                {
                    if (_pending.TryGetValue(message.Id, out pending))
                    {
                        _pending.Remove(message.Id);
                    }
                }

                if (pending is null)
                {
                    continue;
                }

                switch (message.Type)
                {
                    case "progress":
                        pending.Progress?.Report(message);
                        break;
                    case "completed" or "thumbnail":
                        pending.Completion.TrySetResult(message);
                        break;
                    case "cancelled":
                        pending.Completion.TrySetCanceled(
                            new OperationCanceledException(message.Message));
                        break;
                    case "error":
                        pending.Completion.TrySetException(
                            new InvalidOperationException(message.Message));
                        break;
                }
            }
        }
        catch (Exception)
        {
            // The loop ends when the worker exits; fail anything still pending.
        }

        FailPendingRequests("変換ワーカーが終了しました。", process);
    }

    private void TryWriteLine(string line)
    {
        try
        {
            Process? process;
            lock (_gate)
            {
                process = _process;
            }

            if (process is null)
            {
                return;
            }

            lock (_stdinGate)
            {
                process.StandardInput.WriteLine(line);
                process.StandardInput.Flush();
            }
        }
        catch (IOException)
        {
            // The worker may have already exited.
        }
        catch (ObjectDisposedException)
        {
            // The worker may have already exited.
        }
        catch (InvalidOperationException)
        {
            // The redirected input stream may be closing during process exit.
        }
    }

    private void FailPendingRequests(string reason, Process? owner = null)
    {
        lock (_gate)
        {
            // When a worker process dies, only the requests it owns are
            // failed; requests already handed to a restarted worker survive.
            var doomed = _pending
                .Where(entry => owner is null || entry.Value.Owner == owner)
                .ToList();
            foreach (var entry in doomed)
            {
                entry.Value.Completion.TrySetException(new InvalidOperationException(reason));
                _pending.Remove(entry.Key);
            }
        }
    }

    private void ShutdownWorker()
    {
        // Caller must hold _gate.
        var process = _process;
        _process = null;
        if (process is not null)
        {
            try
            {
                // Closing stdin lets the worker exit cleanly on its own.
                process.StandardInput.Close();
            }
            catch (Exception)
            {
                // The stream may already be closed.
            }

            try
            {
                if (!process.WaitForExit(2000))
                {
                    process.Kill(entireProcessTree: true);
                }
            }
            catch (Exception)
            {
                // The process already exited.
            }

            process.Dispose();
        }

        if (_jobHandle != IntPtr.Zero)
        {
            // Closing the job handle kills any worker that ignored stdin
            // closing (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE).
            CloseHandle(_jobHandle);
            _jobHandle = IntPtr.Zero;
        }
    }

    private void AssignToKillOnCloseJob(Process process)
    {
        try
        {
            var job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero)
            {
                return;
            }

            var information = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION
            {
                BasicLimitInformation = new JOBOBJECT_BASIC_LIMIT_INFORMATION
                {
                    LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
                },
            };
            if (!SetInformationJobObject(
                    job,
                    JobObjectExtendedLimitInformation,
                    ref information,
                    Marshal.SizeOf<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>()))
            {
                CloseHandle(job);
                return;
            }

            if (!AssignProcessToJobObject(job, process.Handle))
            {
                CloseHandle(job);
                return;
            }

            _jobHandle = job;
        }
        catch (Exception)
        {
            // Lifetime management is best effort; the worker also exits when
            // its stdin pipe closes during orderly shutdown.
        }
    }

    private static ProcessStartInfo CreateStartInfo()
    {
        var baseDirectory = AppContext.BaseDirectory;
        var packagedWorker = Path.Combine(baseDirectory, "ImageToPDFWorker.exe");
        var startInfo = new ProcessStartInfo
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            WorkingDirectory = baseDirectory,
        };

        if (File.Exists(packagedWorker))
        {
            startInfo.FileName = packagedWorker;
        }
        else
        {
            var sourceWorker = FindSourceWorker();
            if (sourceWorker is null)
            {
                throw new FileNotFoundException(
                    "ImageToPDFWorker.exe が見つかりません。winui/README.md の手順でビルドしてください。");
            }

            startInfo.FileName = Environment.GetEnvironmentVariable("PYTHON") ?? "python";
            startInfo.ArgumentList.Add(sourceWorker);
            startInfo.WorkingDirectory = Path.GetDirectoryName(sourceWorker)!;
        }

        return startInfo;
    }

    private static string? FindSourceWorker()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "conversion_worker.py");
            if (File.Exists(candidate))
            {
                return candidate;
            }

            directory = directory.Parent;
        }

        return null;
    }

    private sealed record PendingRequest(
        Process Owner,
        TaskCompletionSource<WorkerMessage> Completion,
        IProgress<WorkerMessage>? Progress);

    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string? lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr hJob,
        int jobObjectInfoClass,
        ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION lpJobObjectInfo,
        int cbJobObjectInfoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr hObject);

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }
}
