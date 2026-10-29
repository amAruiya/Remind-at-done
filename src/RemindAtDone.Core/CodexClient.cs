using System.Diagnostics;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;

namespace RemindAtDone.Core;

// 0.165.0 proxy is a byte tunnel to a WebSocket socket, NOT JSONL stdio.
public sealed class CodexClient : IAsyncDisposable
{
    private readonly Process process;
    private readonly ClientWebSocket socket = new();
    private readonly HttpMessageInvoker transport;
    private int sequence;

    private CodexClient(CodexInstance instance)
    {
        var start = new ProcessStartInfo(instance.Executable)
        {
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            UseShellExecute = false, CreateNoWindow = true
        };
        start.ArgumentList.Add("app-server"); start.ArgumentList.Add("proxy");
        start.Environment["CODEX_HOME"] = instance.CodexHome;
        process = Process.Start(start) ?? throw new IOException("无法启动 Codex proxy。");
        process.ErrorDataReceived += (_, _) => { }; // Drain without logging private daemon diagnostics.
        process.BeginErrorReadLine();
        transport = new HttpMessageInvoker(new SocketsHttpHandler
        {
            UseProxy = false,
            ConnectCallback = (_, _) => ValueTask.FromResult<Stream>(new DuplexStream(
                process.StandardOutput.BaseStream, process.StandardInput.BaseStream))
        });
    }

    public static async Task<CodexClient> ConnectAsync(CodexInstance instance, CancellationToken ct)
    {
        var client = new CodexClient(instance);
        try
        {
            await client.socket.ConnectAsync(new Uri("ws://localhost/"), client.transport, ct);
            await client.CallAsync("initialize", new
            {
                clientInfo = new { name = "remind_at_done", title = "Remind at done", version = "0.1.0" },
                capabilities = new { experimentalApi = true }
            }, ct);
            await client.SendAsync(new { method = "initialized", @params = new { } }, ct);
            return client;
        }
        catch { await client.DisposeAsync(); throw; }
    }

    private Task SendAsync<T>(T message, CancellationToken ct) => socket.SendAsync(
        new ArraySegment<byte>(JsonSerializer.SerializeToUtf8Bytes(message)), WebSocketMessageType.Text, true, ct);

    // Sequential use per connection. This adapter cannot start, resume, cancel or edit tasks.
    public async Task<JsonElement> CallAsync(string method, object parameters, CancellationToken ct)
    {
        if (method is not ("initialize" or "thread/read" or "thread/loaded/list" or "thread/turns/list" or "thread/items/list" or "thread/goal/get"))
            throw new InvalidOperationException("只读适配不允许该方法。");
        var id = ++sequence;
        await SendAsync(new { id, method, @params = parameters }, ct);
        var buffer = new byte[8192];
        while (true)
        {
            using var data = new MemoryStream();
            WebSocketReceiveResult received;
            do
            {
                received = await socket.ReceiveAsync(buffer, ct);
                if (received.MessageType == WebSocketMessageType.Close) throw new IOException("daemon 已断开。");
                data.Write(buffer, 0, received.Count);
                if (data.Length > 8 * 1024 * 1024) throw new InvalidDataException("daemon 响应过大。");
            } while (!received.EndOfMessage);
            using var doc = JsonDocument.Parse(data.ToArray());
            var root = doc.RootElement;
            if (!root.TryGetProperty("id", out var responseId) || responseId.ValueKind != JsonValueKind.Number || responseId.GetInt32() != id) continue;
            if (root.TryGetProperty("error", out var error)) throw new IOException(error.GetProperty("message").GetString());
            return root.GetProperty("result").Clone();
        }
    }

    public async Task<JsonElement> ReadThreadAsync(string id, CancellationToken ct) =>
        (await CallAsync("thread/read", new { threadId = id, includeTurns = false }, ct)).GetProperty("thread");

    public static bool IsChild(JsonElement thread) =>
        (thread.TryGetProperty("parentThreadId", out var parent) && parent.ValueKind == JsonValueKind.String) ||
        (thread.TryGetProperty("source", out var source) && source.ValueKind == JsonValueKind.Object && source.TryGetProperty("subAgent", out _)) ||
        (thread.TryGetProperty("threadSource", out var kind) && kind.ValueKind == JsonValueKind.String && kind.GetString() == "subagent");

    public async Task<ActiveSnapshot> ActiveAsync(CodexInstance instance, CancellationToken ct)
    {
        var ids = new HashSet<string>();
        string? cursor = null;
        do
        {
            var page = await CallAsync("thread/loaded/list", new { cursor, limit = 100 }, ct);
            foreach (var id in page.GetProperty("data").EnumerateArray()) ids.Add(id.GetString()!);
            cursor = page.GetProperty("nextCursor").GetString();
        } while (cursor is not null);
        var rows = new List<ActiveTask>();
        var failed = 0;
        foreach (var id in ids)
        {
            JsonElement thread;
            try { thread = await ReadThreadAsync(id, ct); }
            catch (IOException) { failed++; continue; }
            if (IsChild(thread)) continue;
            var status = thread.GetProperty("status");
            var type = status.GetProperty("type").GetString();
            if (type is "idle" or "notLoaded") continue;
            var flags = status.TryGetProperty("activeFlags", out var f) ? f.EnumerateArray().Select(x => x.GetString()).ToArray() : [];
            var waiting = flags.Any(x => x is "waitingOnApproval" or "waitingOnUserInput");
            var title = thread.GetProperty("name").GetString();
            if (string.IsNullOrWhiteSpace(title))
            {
                title = thread.TryGetProperty("preview", out var preview) ? preview.GetString() : null;
                title = string.IsNullOrWhiteSpace(title) ? "未命名任务" : System.Text.RegularExpressions.Regex.Replace(title, @"\s+", " ").Trim();
                var visible = new System.Globalization.StringInfo(title);
                if (visible.LengthInTextElements > 48) title = visible.SubstringByTextElements(0, 48) + "…";
            }
            rows.Add(new(instance.Id, id, title,
                thread.GetProperty("cwd").GetString()!, waiting ? "等待用户操作" : type == "active" ? "执行中" : type == "systemError" ? "需要处理" : "状态待确认", waiting));
        }
        return new(rows.OrderByDescending(x => x.Waiting).ToArray(), DateTimeOffset.Now, failed);
    }

    public async ValueTask DisposeAsync()
    {
        socket.Abort(); socket.Dispose(); transport.Dispose();
        try
        {
            try { process.StandardInput.Close(); } catch (ObjectDisposedException) { }
            using var stop = new CancellationTokenSource(1000);
            await process.WaitForExitAsync(stop.Token);
        }
        catch (OperationCanceledException) { if (!process.HasExited) process.Kill(); }
        finally { process.Dispose(); }
    }

    private sealed class DuplexStream(Stream read, Stream write) : Stream
    {
        public override bool CanRead => true;
        public override bool CanWrite => true;
        public override bool CanSeek => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override void Flush() => write.Flush();
        public override Task FlushAsync(CancellationToken ct) => write.FlushAsync(ct);
        public override int Read(byte[] b, int o, int c) => read.Read(b, o, c);
        public override ValueTask<int> ReadAsync(Memory<byte> b, CancellationToken ct = default) => read.ReadAsync(b, ct);
        public override Task<int> ReadAsync(byte[] b, int o, int c, CancellationToken ct) => read.ReadAsync(b, o, c, ct);
        public override void Write(byte[] b, int o, int c) => write.Write(b, o, c);
        public override ValueTask WriteAsync(ReadOnlyMemory<byte> b, CancellationToken ct = default) => write.WriteAsync(b, ct);
        public override Task WriteAsync(byte[] b, int o, int c, CancellationToken ct) => write.WriteAsync(b, o, c, ct);
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        protected override void Dispose(bool disposing) { if (disposing) { read.Dispose(); write.Dispose(); } base.Dispose(disposing); }
    }
}

public sealed record ActiveTask(string InstanceId, string ThreadId, string Title, string Cwd, string Status, bool Waiting);
public sealed record ActiveSnapshot(IReadOnlyList<ActiveTask> Tasks, DateTimeOffset UpdatedAt, int FailedReads);
