namespace ImageToPDF.WinUI.Services;

/// <summary>Keep a sent request alive until the worker reports its actual outcome.</summary>
internal static class WorkerRequestLifetime
{
    public static async Task<WorkerMessage> SendAndWaitAsync(
        Task<WorkerMessage> terminalResponse,
        Action sendRequest,
        Action sendCancellation,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        sendRequest();
        // Register after sending so even a cancellation during the write is
        // delivered AFTER the request. Register invokes the callback immediately
        // if cancellation was already requested while sendRequest was running.
        using var registration = cancellationToken.Register(sendCancellation);
        // Cancellation requests cooperative work stoppage; it must not release
        // the UI while image decoding, PDF writing or cleanup is still running.
        // A late cancellation may race a successful save: preserve the worker's
        // completed result rather than incorrectly reporting that save as cancelled.
        return await terminalResponse.ConfigureAwait(false);
    }
}
