using System.Text;
using RemindAtDone.Core;
using System.IO.Pipes;

if(args.Length==2 && args[0]=="--wire-batch")
{
    var reports=Json.Parse<List<CompletionReport>>(File.ReadAllBytes(args[1]));
    var clock=System.Diagnostics.Stopwatch.StartNew();
    using var deadline=new CancellationTokenSource(5000);
    var replies=await Task.WhenAll(reports.Select(async report=>
    {
        using var pipe=new NamedPipeClientStream(".",Wire.Name,PipeDirection.InOut,PipeOptions.Asynchronous|PipeOptions.CurrentUserOnly);
        await pipe.ConnectAsync(deadline.Token);await Wire.WriteAsync(pipe,Json.Bytes(report),deadline.Token);
        return Json.Parse<Ack>(await Wire.ReadAsync(pipe,deadline.Token));
    }));
    Console.WriteLine(Encoding.UTF8.GetString(Json.Bytes(new{replies,duration_ms=clock.Elapsed.TotalMilliseconds})));
    return replies.All(reply=>reply.ExitCode==0)?0:1;
}

if(args.Length==2 && args[0] is "--wire" or "--wire-no-ack")
{
    using var pipe=new NamedPipeClientStream(".",Wire.Name,PipeDirection.InOut,PipeOptions.Asynchronous|PipeOptions.CurrentUserOnly);
    using var deadline=new CancellationTokenSource(5000);await pipe.ConnectAsync(deadline.Token);
    await Wire.WriteAsync(pipe,File.ReadAllBytes(args[1]),deadline.Token);
    if(args[0]=="--wire-no-ack"){pipe.WaitForPipeDrain();return 0;}
    var ack=Json.Parse<Ack>(await Wire.ReadAsync(pipe,deadline.Token));Console.WriteLine(Encoding.UTF8.GetString(Json.Bytes(ack)));return ack.ExitCode;
}

if (Environment.GetEnvironmentVariable("RAD_ARGV_RECORD") is string capture)
{
    File.WriteAllBytes(capture, Json.Bytes(new { args, codex_home = Environment.GetEnvironmentVariable("CODEX_HOME"), cwd = Environment.CurrentDirectory,
        no_color=Environment.GetEnvironmentVariable("NO_COLOR"),term=Environment.GetEnvironmentVariable("TERM"),colorterm=Environment.GetEnvironmentVariable("COLORTERM") }));
    return 0;
}

var root = Path.Combine(Path.GetTempPath(), "rad-tests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
var passed = 0;
void Check(bool condition, string name)
{
    if (!condition) throw new Exception("FAIL: " + name);
    passed++; Console.WriteLine("PASS: " + name);
}
void Reject(Action action, string name)
{
    try { action(); } catch (InvalidDataException) { Check(true, name); return; }
    throw new Exception("FAIL (accepted invalid input): " + name);
}
CompletionReport Report(string key = "turn:first")
{
    var instance = "00000000-0000-0000-0000-000000000001";
    var thread = "00000000-0000-0000-0000-000000000002";
    return new() { InstanceId = instance, ThreadId = thread, TaskKey = key,
        EventId = CompletionReport.MakeEventId(instance, thread, key), Status = "completed",
        Title = "完成中文路径验证", Summary = "支持\"引号\"、换行\n和空格。", Verification = "未运行完整桌面测试",
        Cwd = @"C:\中文路径\with spaces", CompletedAt = DateTimeOffset.UtcNow.ToString("O"), ElapsedSeconds = 301, TimingSource = "history_metadata" };
}
try
{
    var report = Report().Validate();
    Check(Json.Parse<CompletionReport>(Json.Bytes(report)) == report, "Unicode report roundtrip preserves verification");
    Check(CompletionReport.MakeEventId("ab", "c", "d") != CompletionReport.MakeEventId("a", "bc", "d"), "event hash has unambiguous tuple boundaries");
    Reject(() => (report with { EventId = "fake" }).Validate(), "wrong event identity rejected");
    Reject(() => (report with { Title = new string('好', 25) }).Validate(), "overlong title rejected");
    Check((report with { Title = string.Concat(Enumerable.Repeat("👩‍💻", 24)) }).Validate().Title.Length > 24, "visible character limit uses graphemes");
    Reject(() => (report with { Status = "paused" }).Validate(), "noncompleted report rejected");
    Reject(() => (report with { CompletedAt = "2026-10-29T12:00:00" }).Validate(), "missing timezone rejected");
    Reject(() => (report with { ElapsedSeconds = double.NaN }).Validate(), "nonfinite duration rejected");
    Check((report with { ElapsedSeconds = 299 }).Validate().ElapsedSeconds == 299, "receiver does not take over skill threshold policy");
    var store = new ReceiptStore(root);
    Check(store.Commit(report).Result == "accepted", "first commit durable acceptance");
    Check(new ReceiptStore(root).Snapshot().Single().Report == report, "fresh process state recovers acknowledged report");
    Check(store.Commit(report).Result == "duplicate", "lost ACK retry yields duplicate");
    Check(store.Commit(report with { Summary = "different" }).ErrorCode == "conflict", "different content under same ID conflicts");
    Check(!store.Snapshot().Single().IsRead, "opening history does not mark read");
    store.MarkRead(report.EventId);
    Check(new ReceiptStore(root).Snapshot().Single().IsRead, "read status persists independently");
    Parallel.For(0, 20, n => store.Commit(Report("concurrent:" + n)));
    Check(new ReceiptStore(root).Snapshot().Count == 20 && store.Snapshot().All(x => x.Report.TaskKey.StartsWith("concurrent:")), "20 concurrent deliveries are all persisted within new 20-item limit");
    Parallel.For(0, 20, n => store.Commit(report));
    Check(store.Snapshot().Count == 20, "duplicate retries respect history bound");
    var now = DateTimeOffset.UtcNow;
    Check(store.Snapshot(now.AddDays(3)).Count == 0, "3-day retention expires records by completion time");
    for (var i = 0; i < 25; i++) store.Commit(Report("retention:" + i));
    Check(new ReceiptStore(root).Snapshot().Count == 20, "history capped at 20");
    var retentionRoot=Path.Combine(root,"late-arrivals");var retentionStore=new ReceiptStore(retentionRoot);
    var cutoff=DateTimeOffset.UtcNow;
    var expired=Report("expired") with { CompletedAt=cutoff.AddDays(-3).ToString("O") };
    var rejected=retentionStore.Commit(expired,cutoff);
    Check(rejected.Result=="error" && rejected.ErrorCode=="outside_retention" && rejected.ExitCode==2,"expired incoming report never gets a success ACK");
    Check(!File.Exists(Path.Combine(retentionRoot,"history.json")),"rejected expired report is not written");
    var justInside=Report("inside") with { CompletedAt=cutoff.AddDays(-3).AddMilliseconds(1).ToString("O") };
    Check(retentionStore.Commit(justInside,cutoff).Result=="accepted" && retentionStore.Snapshot(cutoff).Count==1,"report just inside three-day boundary is retained");
    for(var i=0;i<20;i++)retentionStore.Commit(Report("ranked:"+i) with {CompletedAt=cutoff.AddMinutes(-i).ToString("O")},cutoff);
    var saved=File.ReadAllBytes(Path.Combine(retentionRoot,"history.json"));
    var delayed=Report("delayed") with {CompletedAt=cutoff.AddMinutes(-30).ToString("O")};
    Check(retentionStore.Commit(delayed,cutoff).ErrorCode=="outside_retention","late arrival outside newest twenty gets an explicit rejection");
    Check(saved.SequenceEqual(File.ReadAllBytes(Path.Combine(retentionRoot,"history.json"))),"rejected late arrival preserves committed snapshot");
    File.WriteAllText(Path.Combine(root, "history.json"), "broken");
    var recovered = new ReceiptStore(root);
    Check(recovered.RecoveryWarning is not null && recovered.Snapshot().Count == 20, "corrupt primary recovers valid backup with warning");
    File.WriteAllText(Path.Combine(root, "history.json"), "broken");
    File.WriteAllText(Path.Combine(root, "history.backup.json"), "broken");
    try { _ = new ReceiptStore(root); throw new Exception("corruption incorrectly treated as empty"); }
    catch (System.Text.Json.JsonException) { Check(true, "both corrupted never silently reset history"); }
    var failureRoot = Path.Combine(root, "unwritable"); Directory.CreateDirectory(failureRoot);
    var failing = new ReceiptStore(failureRoot);
    Directory.CreateDirectory(Path.Combine(failureRoot, "history.json"));
    try { failing.Commit(report); throw new Exception("false ACK on storage failure"); }
    catch (IOException) { Check(failing.Snapshot().Count == 0, "storage failure has no ACK or in-memory acceptance"); }
    var frame = new MemoryStream();
    await Wire.WriteAsync(frame, Json.Bytes(report), CancellationToken.None); frame.Position = 0;
    Check(Json.Parse<CompletionReport>(await Wire.ReadAsync(frame, CancellationToken.None)) == report, "framed pipe protocol roundtrip");
    var oversized = new MemoryStream(BitConverter.GetBytes(16385));
    try { await Wire.ReadAsync(oversized, CancellationToken.None); throw new Exception("oversized frame accepted"); }
    catch (InvalidDataException) { Check(true, "oversized frame rejected before allocation"); }
    Console.WriteLine($"{passed} checks passed.");
    return 0;
}
finally { Directory.Delete(root, true); }
