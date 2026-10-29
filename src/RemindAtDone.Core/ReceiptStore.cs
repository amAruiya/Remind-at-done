namespace RemindAtDone.Core;

public static class AtomicFile
{
    public static void Write(string path, byte[] data, string? backup = null)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                       4096, FileOptions.WriteThrough))
            {
                stream.Write(data);
                stream.Flush(true);
            }
            if (File.Exists(path)) File.Replace(temporary, path, backup);
            else File.Move(temporary, path);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}

public sealed class ReceiptStore
{
    private readonly object gate = new();
    private readonly string path;
    private readonly string backup;
    private List<Receipt> receipts;
    public string? RecoveryWarning { get; }

    public ReceiptStore(string root)
    {
        path = Path.Combine(root, "history.json");
        backup = Path.Combine(root, "history.backup.json");
        try { receipts = File.Exists(path) ? Read(path) : []; }
        catch (Exception e) when (e is IOException or System.Text.Json.JsonException or InvalidDataException)
        {
            // Never replace a corrupt primary with an empty history.
            if (!File.Exists(backup)) throw new InvalidDataException("历史损坏且无有效备份；请保留文件并查看诊断。", e);
            receipts = Read(backup);
            RecoveryWarning = "历史文件损坏，已恢复有效备份。";
            File.Copy(path, path + ".corrupt", true);
            AtomicFile.Write(path, Json.Bytes(receipts));
        }
        var retained=Retain(receipts,DateTimeOffset.UtcNow);
        if(retained.Count!=receipts.Count){AtomicFile.Write(path,Json.Bytes(retained),backup);receipts=retained;}
    }

    private static List<Receipt> Read(string file)
    {
        var result = Json.Parse<List<Receipt>>(File.ReadAllBytes(file));
        foreach (var item in result) item.Report.Validate();
        if (result.Select(x => x.Report.EventId).Distinct().Count() != result.Count)
            throw new InvalidDataException("历史包含重复标识。");
        return result;
    }

    private static List<Receipt> Retain(IEnumerable<Receipt> input, DateTimeOffset now) => input
        .Where(x => DateTimeOffset.Parse(x.Report.CompletedAt) > now.AddDays(-3))
        .OrderByDescending(x => DateTimeOffset.Parse(x.Report.CompletedAt)).Take(20).ToList();

    public IReadOnlyList<Receipt> Snapshot(DateTimeOffset? now = null)
    {
        lock (gate) return Retain(receipts, now ?? DateTimeOffset.UtcNow)
            .OrderByDescending(x => DateTimeOffset.Parse(x.Report.CompletedAt)).ToArray();
    }

    public Ack Commit(CompletionReport report, DateTimeOffset? now = null)
    {
        report.Validate();
        lock (gate)
        {
            var timestamp = now ?? DateTimeOffset.UtcNow;
            var next = Retain(receipts, timestamp);
            var existing = next.SingleOrDefault(x => x.Report.EventId == report.EventId);
            if (existing is not null)
                return existing.Report == report ? new(report.EventId, "duplicate", existing.StoredAt) :
                    new(report.EventId, "error", ErrorCode: "conflict", Message: "同一任务标识已有不同内容。");
            next.Insert(0, new(report, timestamp));
            next = Retain(next, timestamp);
            if(!next.Any(x=>x.Report.EventId==report.EventId))
                return new(report.EventId,"error",ErrorCode:"outside_retention",
                    Message:"这条结果不在最近 3 天的最新 20 项内，未保存。请勿把本次投递视为成功。");
            AtomicFile.Write(path, Json.Bytes(next), backup);
            receipts = next;
            return new(report.EventId, "accepted", timestamp);
        }
    }

    public void MarkRead(string id)
    {
        lock (gate)
        {
            var next = Retain(receipts, DateTimeOffset.UtcNow).Select(x => x.Report.EventId == id ? x with { IsRead = true } : x).ToList();
            AtomicFile.Write(path, Json.Bytes(next), backup);
            receipts = next;
        }
    }
}
