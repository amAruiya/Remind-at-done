using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace RemindAtDone.Core;

public static class Json
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
    };
    public static byte[] Bytes<T>(T value) => JsonSerializer.SerializeToUtf8Bytes(value, Options);
    public static T Parse<T>(ReadOnlySpan<byte> bytes) => JsonSerializer.Deserialize<T>(bytes, Options)
        ?? throw new InvalidDataException("JSON 不能为空。");
}

public sealed record CompletionReport
{
    public int SchemaVersion { get; init; } = 1;
    public string EventId { get; init; } = "";
    public string InstanceId { get; init; } = "";
    public string ThreadId { get; init; } = "";
    public string TaskKey { get; init; } = "";
    public string Status { get; init; } = "";
    public string Title { get; init; } = "";
    public string Summary { get; init; } = "";
    public string? Verification { get; init; }
    public string CompletedAt { get; init; } = "";
    [JsonRequired]
    public double ElapsedSeconds { get; init; }
    public string TimingSource { get; init; } = "";
    public string Cwd { get; init; } = "";

    // Identity strings use canonical lower-case UUIDs; task_key is case-sensitive.
    // Hash the compact JSON array (System.Text.Json default escaping), UTF-8, SHA-256.
    public static string MakeEventId(string instance, string thread, string task) =>
        Convert.ToHexStringLower(SHA256.HashData(Json.Bytes(new[] { instance, thread, task })));

    public CompletionReport Validate()
    {
        if (SchemaVersion != 1) throw new InvalidDataException("不支持 schema_version。");
        foreach (var id in new[] { InstanceId, ThreadId })
            if (!Guid.TryParseExact(id, "D", out var guid) || guid.ToString() != id)
                throw new InvalidDataException("实例与线程标识须为小写 UUID。");
        Text(TaskKey, 240, "task_key");
        if (EventId != MakeEventId(InstanceId, ThreadId, TaskKey)) throw new InvalidDataException("event_id 不匹配。");
        if (Status != "completed") throw new InvalidDataException("只接收 completed 报告。");
        Text(Title, 24, "title"); Text(Summary, 120, "summary");
        if (Verification is not null) Text(Verification, 80, "verification");
        if (!TryTimestamp(CompletedAt, out _)) throw new InvalidDataException("completed_at 必须带明确时区。");
        if (!double.IsFinite(ElapsedSeconds) || ElapsedSeconds < 0) throw new InvalidDataException("elapsed_seconds 无效。");
        if (TimingSource is not ("context" or "goal_metadata" or "history_metadata"))
            throw new InvalidDataException("timing_source 无效。");
        if (string.IsNullOrWhiteSpace(Cwd) || !Path.IsPathFullyQualified(Cwd)) throw new InvalidDataException("cwd 必须为绝对路径。");
        if (Json.Bytes(this).Length > Wire.MaxBytes) throw new InvalidDataException("报告超过 16 KiB。");
        return this;
    }

    public static bool TryTimestamp(string value, out DateTimeOffset timestamp)
    {
        timestamp = default;
        return System.Text.RegularExpressions.Regex.IsMatch(value, @"T.*(Z|[+-]\d{2}:\d{2})$")
            && DateTimeOffset.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.None, out timestamp);
    }

    private static void Text(string value, int limit, string field)
    {
        if (string.IsNullOrWhiteSpace(value) || new StringInfo(value).LengthInTextElements > limit ||
            value.Any(c => char.IsControl(c) && c is not ('\n' or '\r' or '\t')))
            throw new InvalidDataException($"{field} 必须为非空纯文本，最多 {limit} 个可见字符。");
    }
}

public sealed record Receipt(CompletionReport Report, DateTimeOffset StoredAt, bool IsRead = false);
public sealed record Ack(string EventId, string Result, DateTimeOffset? StoredAt = null,
    string? ErrorCode = null, string? Message = null)
{
    [JsonIgnore]
    public int ExitCode => Result is "accepted" or "duplicate" ? 0 : ErrorCode switch
    { "connection" => 3, "storage" => 4, "conflict" => 5, _ => 2 };
}

public sealed record CodexInstance(string Id, string CodexHome, string Executable);
public sealed record Settings
{
    public List<CodexInstance> Instances { get; init; } = [];
    public int CardSeconds { get; init; } = 8;
    public bool DoNotDisturb { get; init; }
    public bool ReduceMotion { get; init; }
    public bool HideLauncher { get; init; }
    public bool LoginStartup { get; init; }
    public string Theme { get; init; } = "dark";
    public string SelectedTab { get; init; } = "active";
    public int? Left { get; init; }
    public int? Top { get; init; }
}

public static class AppPaths
{
    public static string Root => Environment.GetEnvironmentVariable("RAD_DATA_DIR") ??
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "RemindAtDone");
    public static string SettingsFile => Path.Combine(Root, "settings.json");
    public static string CodexHome => Path.GetFullPath(Environment.GetEnvironmentVariable("CODEX_HOME") ??
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex"));
    public static Settings LoadSettings() => File.Exists(SettingsFile) ? Json.Parse<Settings>(File.ReadAllBytes(SettingsFile)) : new();
    public static void SaveSettings(Settings value) => AtomicFile.Write(SettingsFile, Json.Bytes(value));
    public static CodexInstance CurrentInstance(Settings settings) => settings.Instances.SingleOrDefault(x =>
        string.Equals(Path.TrimEndingDirectorySeparator(x.CodexHome), Path.TrimEndingDirectorySeparator(CodexHome), StringComparison.OrdinalIgnoreCase))
        ?? throw new InvalidDataException("当前 CODEX_HOME 尚未登记。请运行安装脚本。");
    public static void Log(string message)
    {
        try
        {
            Directory.CreateDirectory(Root);
            var path = Path.Combine(Root, "diagnostic.log");
            if (File.Exists(path) && new FileInfo(path).Length > 256 * 1024) File.Move(path, path + ".old", true);
            File.AppendAllText(path, $"{DateTimeOffset.UtcNow:O} {message}\n");
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
}
