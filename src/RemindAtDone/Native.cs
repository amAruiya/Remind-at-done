using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using Forms = System.Windows.Forms;

namespace RemindAtDone;

internal static class Native
{
    [StructLayout(LayoutKind.Sequential)] internal struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] internal struct Point { public int X, Y; }
    internal delegate void WinEvent(nint hook, uint eventId, nint hwnd, int obj, int child, uint thread, uint time);
    [DllImport("user32.dll")] internal static extern nint GetForegroundWindow();
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(nint hwnd);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(nint hwnd);
    [DllImport("user32.dll")] internal static extern bool GetWindowRect(nint hwnd, out Rect rect);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(nint hwnd, System.Text.StringBuilder name, int count);
    [DllImport("user32.dll")] internal static extern bool GetCursorPos(out Point point);
    [DllImport("user32.dll")] private static extern nint WindowFromPoint(Point point);
    [DllImport("user32.dll")] private static extern nint GetAncestor(nint hwnd,uint flags);
    [DllImport("user32.dll")] internal static extern short GetAsyncKeyState(int key);
    internal static bool PointsTo(Window window,Point point)=>
        GetAncestor(WindowFromPoint(point),2)==new WindowInteropHelper(window).Handle;
    [DllImport("user32.dll")] internal static extern bool SetWindowPos(nint hwnd, nint after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern nint GetWindowLongPtr(nint hwnd, int index);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] private static extern nint SetWindowLongPtr(nint hwnd, int index, nint value);
    [DllImport("user32.dll")] internal static extern nint SetWinEventHook(uint min, uint max, nint module, WinEvent callback, uint process, uint thread, uint flags);
    [DllImport("user32.dll")] internal static extern bool UnhookWinEvent(nint hook);
    [DllImport("user32.dll")] private static extern nint OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll")] private static extern bool CloseDesktop(nint desktop);
    [DllImport("gdi32.dll")] private static extern nint CreatePolyPolygonRgn(Point[] points, int[] counts, int polygonCount, int mode);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(nint obj);
    [DllImport("user32.dll")] private static extern int SetWindowRgn(nint hwnd, nint region, bool redraw);

    internal static void SetRegion(Window window, Geometry? geometry)
    {
        var hwnd=new WindowInteropHelper(window).Handle;
        if(hwnd==0) return;
        if(geometry is null) { SetWindowRgn(hwnd,0,true); return; }
        var flat=geometry.GetFlattenedPathGeometry(.4,ToleranceType.Absolute);
        var points=new List<Point>(); var counts=new List<int>(); var dpi=VisualTreeHelper.GetDpi(window);
        foreach(var figure in flat.Figures)
        {
            var polygon=new List<System.Windows.Point>{figure.StartPoint};
            foreach(var segment in figure.Segments)
                if(segment is PolyLineSegment line) polygon.AddRange(line.Points);
                else if(segment is LineSegment single) polygon.Add(single.Point);
            if(polygon.Count<3) continue;
            counts.Add(polygon.Count);
            foreach(var original in polygon) { var p=flat.Transform?.Transform(original)??original; points.Add(new Point{X=(int)Math.Round(p.X*dpi.DpiScaleX),Y=(int)Math.Round(p.Y*dpi.DpiScaleY)}); }
        }
        if(counts.Count==0) return;
        var region=CreatePolyPolygonRgn(points.ToArray(),counts.ToArray(),counts.Count,flat.FillRule==FillRule.Nonzero?2:1);
        if(region!=0 && SetWindowRgn(hwnd,region,true)==0) DeleteObject(region);
    }

    internal static bool InputDesktopAvailable()
    {
        var desktop = OpenInputDesktop(0, false, 0x101);
        if (desktop == 0) return false;
        CloseDesktop(desktop); return true;
    }

    internal static void NonActivating(Window window,Func<bool>? interactive=null)
    {
        window.ShowActivated = false;
        window.SourceInitialized += (_, _) =>
        {
            var handle = new WindowInteropHelper(window).Handle;
            SetWindowLongPtr(handle, -20, GetWindowLongPtr(handle, -20) | 0x08000000 | 0x80);
            HwndSource.FromHwnd(handle).AddHook((nint hwnd, int msg, nint wp, nint lp, ref bool handled) =>
            {
                if (msg == 0x21 && interactive?.Invoke()!=true) { handled = true; return 3; } // MA_NOACTIVATE, clicks still reach controls.
                return 0;
            });
        };
    }
    internal static void SetInteractive(Window window,bool enabled)
    {
        var hwnd=new WindowInteropHelper(window).Handle;
        var style=GetWindowLongPtr(hwnd,-20);
        SetWindowLongPtr(hwnd,-20,enabled?style&~(nint)0x08000000:style|0x08000000);
    }
    internal static void RestoreFocus(Window window,nint previous)
    {
        if(GetForegroundWindow()!=new WindowInteropHelper(window).Handle)return;
        if(previous!=0 && IsWindowVisible(previous) && SetForegroundWindow(previous))return;
        window.Hide();window.Show();
    }

    internal static Forms.Screen Screen(Window window)
    {
        var handle = new WindowInteropHelper(window).Handle;
        return handle != 0 ? Forms.Screen.FromHandle(handle) : Forms.Screen.PrimaryScreen!;
    }

    internal static void Position(Window window, int x, int y)
    {
        var handle = new WindowInteropHelper(window).Handle;
        SetWindowPos(handle, 0, x, y, 0, 0, 0x0015); // no size, no z-order, no activation
    }
    internal static void RaiseWithoutActivation(Window window)
    {
        if(window.IsVisible)SetWindowPos(new WindowInteropHelper(window).Handle,(nint)(-1),0,0,0,0,0x0013);
    }
    internal static bool IsVisibleTopLevel(nint hwnd)=>hwnd!=0 && IsWindowVisible(hwnd) && GetAncestor(hwnd,2)==hwnd;

    internal static void Clamp(Window window, int? x = null, int? y = null, bool snap = false)
    {
        var handle = new WindowInteropHelper(window).Handle;
        GetWindowRect(handle, out var r);
        var desired = new System.Drawing.Point(x ?? r.Left, y ?? r.Top);
        var work = Forms.Screen.FromPoint(desired).WorkingArea;
        var width = Math.Max(1, r.Right - r.Left); var height = Math.Max(1, r.Bottom - r.Top);
        var left = Math.Clamp(desired.X, work.Left, Math.Max(work.Left, work.Right - width));
        var top = Math.Clamp(desired.Y, work.Top, Math.Max(work.Top, work.Bottom - height));
        if (snap) left = left + width / 2 < work.Left + work.Width / 2 ? work.Left + 12 : work.Right - width - 12;
        Position(window, left, top);
    }

    internal static void Beside(Window window, Window anchor)
    {
        var work = Screen(anchor).WorkingArea;
        GetWindowRect(new WindowInteropHelper(anchor).Handle, out var r);
        GetWindowRect(new WindowInteropHelper(window).Handle, out var card);
        var width = card.Right - card.Left; var height = card.Bottom - card.Top;
        var gap = (int)(12 * VisualTreeHelper.GetDpi(anchor).DpiScaleX);
        var left = r.Left - width - gap;
        if (left < work.Left) left = r.Right + gap;
        Position(window, Math.Clamp(left, work.Left, Math.Max(work.Left, work.Right - width)),
            Math.Clamp(r.Bottom - height, work.Top, Math.Max(work.Top, work.Bottom - height)));
    }

    internal static bool Fullscreen(Window anchor,nint foreground=0)
    {
        if(foreground==0)foreground=GetForegroundWindow();
        if (foreground == 0 || foreground == new WindowInteropHelper(anchor).Handle) return false;
        var name = new System.Text.StringBuilder(256); GetClassName(foreground, name, name.Capacity);
        if (name.ToString() is "Progman" or "WorkerW") return false;
        if (!GetWindowRect(foreground, out var rect)) return false;
        var screen = Screen(anchor);
        if (Forms.Screen.FromHandle(foreground).DeviceName != screen.DeviceName) return false;
        var bounds = screen.Bounds;
        return rect.Left <= bounds.Left && rect.Top <= bounds.Top && rect.Right >= bounds.Right && rect.Bottom >= bounds.Bottom;
    }
}
