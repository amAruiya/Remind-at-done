using System.Text;
using System.Text.Json;
using RemindAtDone.Core;

Console.InputEncoding = new UTF8Encoding(false);
Console.OutputEncoding = new UTF8Encoding(false);
try
{
    if (args.Length == 0 || args[0] is "--help" or "help")
    {
        Console.WriteLine("rad notify --stdin | --file <UTF-8.json>\nrad context [--cursor <cursor>] [--turn <turn_id>]\nrad active\nrad register --home <CODEX_HOME> --codex <codex.exe>");
        return 0;
    }
    string? Option(string name) { var i = Array.IndexOf(args, name); return i >= 0 && i + 1 < args.Length ? args[i + 1] : null; }
    var settings = AppPaths.LoadSettings();
    if (args[0] == "start")
    {
        DetachedProcess.Start(Path.Combine(AppContext.BaseDirectory, "RemindAtDone.exe"));
        Output(new { result = "started" });
        return 0;
    }
    if (args[0] == "register")
    {
        var home = Path.TrimEndingDirectorySeparator(Path.GetFullPath(Option("--home") ?? AppPaths.CodexHome));
        var executable = Path.GetFullPath(Option("--codex") ?? throw new InvalidDataException("缺少 --codex。"));
        if (!Directory.Exists(home) || !File.Exists(executable) || !string.Equals(Path.GetExtension(executable),".exe",StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("实例路径不存在，或 Codex 不是 exe。");
        var existing = settings.Instances.SingleOrDefault(x => string.Equals(Path.TrimEndingDirectorySeparator(x.CodexHome), home, StringComparison.OrdinalIgnoreCase));
        var instance = new CodexInstance(existing?.Id ?? Guid.NewGuid().ToString(), home, executable);
        var instances = settings.Instances.Where(x => x.Id != instance.Id).Append(instance).ToList();
        AppPaths.SaveSettings(settings with { Instances = instances });
        Output(instance);
        return 0;
    }
    var current = AppPaths.CurrentInstance(settings);
    using var timeout = new CancellationTokenSource(args[0] == "notify" ? 5000 : 30000);
    if (args[0] == "active")
    {
        await using var client = await CodexClient.ConnectAsync(current, timeout.Token);
        Output(await client.ActiveAsync(current, timeout.Token));
        return 0;
    }
    var threadId = Environment.GetEnvironmentVariable("CODEX_THREAD_ID");
    if (!Guid.TryParseExact(threadId, "D", out var threadGuid)) throw new InvalidDataException("没有可靠的 CODEX_THREAD_ID。");
    threadId = threadGuid.ToString();
    if (args[0] == "context")
    {
        await using var client = await CodexClient.ConnectAsync(current, timeout.Token);
        var thread = await client.ReadThreadAsync(threadId, timeout.Token);
        if (Option("--turn") is string turnId)
        {
            var items = await client.CallAsync("thread/items/list", new { threadId, turnId, cursor = DecodeCursor(Option("--cursor")), limit = 20 }, timeout.Token);
            Output(new { thread_id = threadId, turn_id = turnId,
                user_messages = items.GetProperty("data").EnumerateArray().Where(x => x.GetProperty("item").GetProperty("type").GetString() == "userMessage")
                    .Select(x => new { task_key = "message:" + x.GetProperty("item").GetProperty("id").GetString(), started_at_ms = x.GetProperty("startedAtMs"), excerpt = Excerpt(x.GetProperty("item")) }).ToArray(),
                next_cursor = EncodeCursor(items.GetProperty("nextCursor")) });
            return 0;
        }
        var goal = await client.CallAsync("thread/goal/get", new { threadId }, timeout.Token);
        var turns = await client.CallAsync("thread/turns/list", new { threadId, cursor = DecodeCursor(Option("--cursor")), limit = 20, itemsView = "summary" }, timeout.Token);
        var origins = turns.GetProperty("data").EnumerateArray().Select(t => new
        {
            task_key = "turn:" + t.GetProperty("id").GetString(),
            started_at = t.GetProperty("startedAt"),
            status = t.GetProperty("status"),
            user_messages = t.GetProperty("items").EnumerateArray().Where(i => i.GetProperty("type").GetString() == "userMessage")
                .Select(i => new { id = i.GetProperty("id").GetString(), excerpt = Excerpt(i) }).ToArray()
        }).ToArray();
        Output(new { instance_id = current.Id, thread_id = threadId, cwd = thread.GetProperty("cwd"),
            is_child = CodexClient.IsChild(thread), now = DateTimeOffset.UtcNow, goal = goal.GetProperty("goal"),
            turns = origins, next_cursor = EncodeCursor(turns.GetProperty("nextCursor")) });
        return 0;
    }
    if (args[0] != "notify") throw new InvalidDataException("未知命令。");
    var file = Option("--file");
    if (args.Contains("--stdin") == (file is not null)) throw new InvalidDataException("--stdin 与 --file 必须二选一。");
    await using var input = file is null ? Console.OpenStandardInput() : File.OpenRead(file);
    using var bytes = new MemoryStream();
    var buffer = new byte[4096];
    int count;
    while ((count = await input.ReadAsync(buffer, timeout.Token)) > 0)
    {
        bytes.Write(buffer, 0, count);
        if (bytes.Length > Wire.MaxBytes) throw new InvalidDataException("报告超过 16 KiB。");
    }
    var data = bytes.ToArray();
    var offset = data.AsSpan().StartsWith(new byte[] { 239, 187, 191 }) ? 3 : 0;
    var report = Json.Parse<CompletionReport>(data.AsSpan(offset));
    await using (var client = await CodexClient.ConnectAsync(current, timeout.Token))
    {
        var thread = await client.ReadThreadAsync(threadId, timeout.Token);
        if (CodexClient.IsChild(thread)) throw new InvalidDataException("子代理不得提交主任务完成提醒。");
        var cwd = thread.GetProperty("cwd").GetString()!;
        var eventId = CompletionReport.MakeEventId(current.Id, threadId, report.TaskKey);
        if ((report.InstanceId != "" && report.InstanceId != current.Id) || (report.ThreadId != "" && report.ThreadId != threadId) ||
            (report.EventId != "" && report.EventId != eventId) || (report.Cwd != "" && !string.Equals(report.Cwd, cwd, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException("报告身份与当前执行上下文不一致。");
        report = (report with { InstanceId = current.Id, ThreadId = threadId, Cwd = cwd, EventId = eventId }).Validate();
    }
    var ack = await Wire.DeliverAsync(report, timeout.Token);
    Output(ack);
    return ack.ExitCode;
}
catch (Exception e)
{
    var code = e is InvalidDataException or FileNotFoundException or DirectoryNotFoundException ? "validation" :
        e is OperationCanceledException or IOException or System.Net.WebSockets.WebSocketException or System.ComponentModel.Win32Exception ? "connection" : "validation";
    var ack = new Ack("", "error", ErrorCode: code, Message: e is OperationCanceledException ? "操作超时；没有确认送达。" : e.Message);
    Output(ack);
    return ack.ExitCode;
}

static void Output<T>(T value) => Console.WriteLine(Encoding.UTF8.GetString(Json.Bytes(value)));
// API cursors may be JSON strings. PS 5.1 removes their embedded quotes in native argv.
static string? EncodeCursor(JsonElement cursor) => cursor.GetString() is string value
    ? "rad1:"+Convert.ToBase64String(Encoding.UTF8.GetBytes(value)) : null;
static string? DecodeCursor(string? cursor) => cursor?.StartsWith("rad1:",StringComparison.Ordinal)==true
    ? Encoding.UTF8.GetString(Convert.FromBase64String(cursor[5..])) : cursor;
static string Excerpt(JsonElement item)
{
    if (!item.TryGetProperty("content", out var content)) return "";
    var text = string.Join(" ", content.EnumerateArray().Where(x => x.TryGetProperty("text", out _)).Select(x => x.GetProperty("text").GetString()));
    return text.Length <= 240 ? text : text[..240];
}
