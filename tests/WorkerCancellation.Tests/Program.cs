using ImageToPDF.WinUI.Services;

// No test-framework packages: exercise the production request lifetime on .NET 8.
await CancellationWaitsForWorker();
await CancellationDuringSendFollowsRequest();
await PreCancelledRequestIsNotSent();
await CompletedSaveWinsLateCancellation();
await WorkerExitStillReleasesWaiter();
await SuccessfulRequestUnregistersCancellation();
Console.WriteLine("Worker cancellation regression tests: 6 passed.");

static TaskCompletionSource<WorkerMessage> Response() =>
    new(TaskCreationOptions.RunContinuationsAsynchronously);

static void Check(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

static async Task ExpectCancellation(Task<WorkerMessage> task)
{
    try
    {
        await task.WaitAsync(TimeSpan.FromSeconds(5));
        throw new InvalidOperationException("Expected the worker's cancellation result.");
    }
    catch (OperationCanceledException)
    {
    }
}

static async Task CancellationWaitsForWorker()
{
    using var token = new CancellationTokenSource();
    var response = Response();
    var cancelCount = 0;
    var task = WorkerRequestLifetime.SendAndWaitAsync(
        response.Task, () => { }, () => cancelCount++, token.Token);
    token.Cancel();
    Check(cancelCount == 1, "Cancellation must reach the worker exactly once.");
    Check(!task.IsCompleted, "The UI must remain busy until worker cleanup finishes.");
    response.SetException(new OperationCanceledException("worker cleanup finished"));
    await ExpectCancellation(task);
}

static async Task CancellationDuringSendFollowsRequest()
{
    using var token = new CancellationTokenSource();
    var response = Response();
    var events = new List<string>();
    var task = WorkerRequestLifetime.SendAndWaitAsync(response.Task,
        () => { token.Cancel(); events.Add("request"); },
        () => events.Add("cancel"), token.Token);
    Check(events.SequenceEqual(new[] { "request", "cancel" }),
        "An early cancel must not reach the worker before its request exists.");
    Check(!task.IsCompleted, "Cancellation during send must still await acknowledgement.");
    response.SetCanceled();
    await ExpectCancellation(task);
}

static async Task PreCancelledRequestIsNotSent()
{
    using var token = new CancellationTokenSource();
    token.Cancel();
    var sent = false;
    var task = WorkerRequestLifetime.SendAndWaitAsync(Response().Task,
        () => sent = true, () => throw new InvalidOperationException("Nothing was sent."), token.Token);
    await ExpectCancellation(task);
    Check(!sent, "A pre-cancelled request must never be submitted.");
}

static async Task CompletedSaveWinsLateCancellation()
{
    using var token = new CancellationTokenSource();
    var response = Response();
    var task = WorkerRequestLifetime.SendAndWaitAsync(response.Task, () => { }, () => { }, token.Token);
    token.Cancel();
    // Publication may already have happened when the worker receives cancel.
    var completed = new WorkerMessage { Type = "completed", PageCount = 1, OutputPath = "saved.pdf" };
    response.SetResult(completed);
    Check(ReferenceEquals(await task.WaitAsync(TimeSpan.FromSeconds(5)), completed),
        "A saved PDF must be reported as completed, even after a late cancel.");
}

static async Task WorkerExitStillReleasesWaiter()
{
    using var token = new CancellationTokenSource();
    var response = Response();
    var task = WorkerRequestLifetime.SendAndWaitAsync(response.Task, () => { }, () => { }, token.Token);
    token.Cancel();
    Check(!task.IsCompleted, "Cancellation must not hide a later worker exit.");
    var failure = new IOException("worker exited");
    response.SetException(failure);
    try
    {
        await task.WaitAsync(TimeSpan.FromSeconds(5));
        throw new InvalidOperationException("Expected the worker exit error.");
    }
    catch (IOException error)
    {
        Check(ReferenceEquals(error, failure), "Preserve the worker exit error.");
    }
}

static async Task SuccessfulRequestUnregistersCancellation()
{
    using var token = new CancellationTokenSource();
    var response = Response();
    var cancelCount = 0;
    var task = WorkerRequestLifetime.SendAndWaitAsync(response.Task, () => { }, () => cancelCount++, token.Token);
    response.SetResult(new WorkerMessage { Type = "completed" });
    await task.WaitAsync(TimeSpan.FromSeconds(5));
    token.Cancel();
    Check(cancelCount == 0, "Finished requests must not keep cancellation callbacks registered.");
}
