using System.ComponentModel;
using System.Runtime.InteropServices;

namespace RemindAtDone.Core;

public static class DetachedProcess
{
    // Explicitly prohibit ALL inherited handles. GUI lifetime must not keep a caller's
    // redirected stdout/stderr pipe alive, including concurrent cold-start callers.
    public static void Start(string executable)
    {
        var startup = new StartupInfo { Size = Marshal.SizeOf<StartupInfo>(), Flags = 1, ShowWindow = 0 };
        if (!CreateProcess(executable, null, 0, 0, false, 0x08000000, 0,
                AppContext.BaseDirectory, ref startup, out var process)) throw new Win32Exception();
        CloseHandle(process.Thread); CloseHandle(process.Process);
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfo
    {
        public int Size;
        public string? Reserved, Desktop, Title;
        public int X, Y, XSize, YSize, XCountChars, YCountChars, FillAttribute, Flags;
        public short ShowWindow, ReservedSize;
        public nint ReservedPointer, StdInput, StdOutput, StdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInfo { public nint Process, Thread; public int ProcessId, ThreadId; }
    [DllImport("kernel32.dll", EntryPoint = "CreateProcessW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcess(string application, string? commandLine, nint processSecurity,
        nint threadSecurity, [MarshalAs(UnmanagedType.Bool)] bool inheritHandles, uint flags, nint environment,
        string directory, ref StartupInfo startup, out ProcessInfo process);
    [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool CloseHandle(nint handle);
}
