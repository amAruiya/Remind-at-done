using System.Diagnostics;

namespace RemindAtDone.Core;

public sealed class ReturnRouter
{
    private readonly Dictionary<string, long> recent = [];
    public async Task OpenAsync(CodexInstance instance, string threadId, CancellationToken ct)
    {
        var key = instance.Id + threadId;
        var now = Environment.TickCount64;
        if (recent.TryGetValue(key, out var previous) && now - previous < 2000) return;
        recent[key] = now;
        if (!Guid.TryParseExact(threadId, "D", out _)) throw new InvalidDataException("线程标识无效。");
        await using var client = await CodexClient.ConnectAsync(instance, ct);
        var thread = await client.ReadThreadAsync(threadId, ct);
        if (thread.GetProperty("id").GetString() != threadId) throw new InvalidDataException("线程身份不匹配。");
        var cwd = thread.GetProperty("cwd").GetString()!;
        if (!Directory.Exists(cwd)) throw new DirectoryNotFoundException("任务工作目录已不存在：" + cwd);
        if (!File.Exists(instance.Executable)) throw new FileNotFoundException("登记的 Codex 程序已不存在。", instance.Executable);
        var helper = Path.Combine(AppContext.BaseDirectory, "resume-thread.ps1");
        if (!File.Exists(helper)) throw new FileNotFoundException("缺少任务返回辅助文件。", helper);
        var powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
        var terminal = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Microsoft", "WindowsApps", "wt.exe");
        var start = new ProcessStartInfo(File.Exists(terminal) ? terminal : powershell) { UseShellExecute = false, WorkingDirectory = cwd };
        if (File.Exists(terminal))
            foreach (var arg in new[] { "-w", "0", "new-tab", powershell }) start.ArgumentList.Add(arg);
        // Base64 JSON is data passed to a fixed script, never executable PowerShell text.
        // Keeps wt's semicolon command separator and PS5 native argument quirks out of paths.
        var capsule = Convert.ToBase64String(Json.Bytes(new { instance.CodexHome, instance.Executable, ThreadId = threadId, Cwd = cwd }));
        foreach (var arg in new[] { "-NoLogo", "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", helper, "-Capsule", capsule }) start.ArgumentList.Add(arg);
        Process.Start(start)?.Dispose();
    }
}
