using System.ComponentModel;
using System.Runtime.InteropServices;

namespace RemindAtDone;

// Observe coordinates/buttons only while a panel is open or the launcher is being dragged.
// Always pass the event on: an outside click must still reach the other application.
internal sealed class MouseObserver : IDisposable
{
    internal const uint Move=0x0200, LeftDown=0x0201, LeftUp=0x0202;
    private readonly HookProc callback;
    private nint hook;
    internal MouseObserver(Action<uint,Native.Point> observe)
    {
        callback=(code,message,data)=>
        {
            if(code>=0) observe((uint)message,Marshal.PtrToStructure<MouseData>(data).Position);
            return CallNextHookEx(hook,code,message,data);
        };
        hook=SetWindowsHookEx(14,callback,GetModuleHandle(null),0);
        if(hook==0)throw new Win32Exception();
    }
    internal static bool IsButtonDown(uint message)=>message is LeftDown or 0x0204 or 0x0207 or 0x020B;
    public void Dispose(){if(hook!=0){UnhookWindowsHookEx(hook);hook=0;}}
    private delegate nint HookProc(int code,nint message,nint data);
    [StructLayout(LayoutKind.Sequential)]
    private struct MouseData { public Native.Point Position; public uint Data,Flags,Time; public nuint ExtraInfo; }
    [DllImport("user32.dll",EntryPoint="SetWindowsHookExW",SetLastError=true)] private static extern nint SetWindowsHookEx(int type,HookProc callback,nint module,uint thread);
    [DllImport("user32.dll")] private static extern bool UnhookWindowsHookEx(nint hook);
    [DllImport("user32.dll")] private static extern nint CallNextHookEx(nint hook,int code,nint message,nint data);
    [DllImport("kernel32.dll",EntryPoint="GetModuleHandleW",CharSet=CharSet.Unicode)] private static extern nint GetModuleHandle(string? name);
}
