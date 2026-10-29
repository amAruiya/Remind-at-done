using System.Buffers.Binary;
using System.Diagnostics;
using System.IO.Pipes;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;

namespace RemindAtDone.Core;

public static class Wire
{
    public const int MaxBytes = 16 * 1024;
    public static string Name => "RemindAtDone-" + Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(
        WindowsIdentity.GetCurrent().User!.Value + "|" + Process.GetCurrentProcess().SessionId + "|" + Path.GetFullPath(AppPaths.Root).ToUpperInvariant())))[..24];

    public static async Task WriteAsync(Stream stream, byte[] message, CancellationToken ct)
    {
        if (message.Length > MaxBytes) throw new InvalidDataException("消息超过 16 KiB。");
        var length = new byte[4];
        BinaryPrimitives.WriteInt32LittleEndian(length, message.Length);
        await stream.WriteAsync(length, ct);
        await stream.WriteAsync(message, ct);
        await stream.FlushAsync(ct);
    }

    public static async Task<byte[]> ReadAsync(Stream stream, CancellationToken ct)
    {
        var header = new byte[4];
        await stream.ReadExactlyAsync(header, ct);
        var length = BinaryPrimitives.ReadInt32LittleEndian(header);
        if (length is <= 0 or > MaxBytes) throw new InvalidDataException("消息长度无效。");
        var message = new byte[length];
        await stream.ReadExactlyAsync(message, ct);
        return message;
    }

    public static async Task<Ack> DeliverAsync(CompletionReport report, CancellationToken ct)
    {
        var started = false;
        while (true)
        {
            using var pipe = new NamedPipeClientStream(".", Name, PipeDirection.InOut, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            try { await pipe.ConnectAsync(100, ct); }
            catch (TimeoutException)
            {
                if (!started)
                {
                    var exe = Path.Combine(AppContext.BaseDirectory, "RemindAtDone.exe");
                    DetachedProcess.Start(exe);
                    started = true;
                }
                await Task.Delay(30, ct);
                continue;
            }
            await WriteAsync(pipe, Json.Bytes(report), ct);
            return Json.Parse<Ack>(await ReadAsync(pipe, ct));
        }
    }

    public static async Task ServeAsync(ReceiptStore store, Func<CompletionReport, Task> accepted,
        Func<string, bool> knownInstance, CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            await using var pipe = new NamedPipeServerStream(Name, PipeDirection.InOut, 1,
                PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            try
            {
                await pipe.WaitForConnectionAsync(ct);
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
                deadline.CancelAfter(TimeSpan.FromSeconds(5));
                CompletionReport? report = null;
                Ack result;
                try
                {
                    report = Json.Parse<CompletionReport>(await ReadAsync(pipe, deadline.Token)).Validate();
                    if (!knownInstance(report.InstanceId)) throw new InvalidDataException("未登记的实例。");
                    result = store.Commit(report);
                }
                catch (Exception e) when (e is InvalidDataException or System.Text.Json.JsonException)
                { result = new(report?.EventId ?? "", "error", ErrorCode: "validation", Message: e.Message); }
                catch (Exception e) when (e is IOException or UnauthorizedAccessException)
                { result = new(report?.EventId ?? "", "error", ErrorCode: "storage", Message: e.Message); }
                await WriteAsync(pipe, Json.Bytes(result), deadline.Token);
                if (result.Result == "accepted") await accepted(report!);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (Exception e) when (e is IOException or OperationCanceledException or InvalidDataException)
            { AppPaths.Log("pipe: " + e.GetType().Name); }
        }
    }
}
