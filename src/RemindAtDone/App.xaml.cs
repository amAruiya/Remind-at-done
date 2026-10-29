using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using Microsoft.Win32;
using RemindAtDone.Core;
using Forms = System.Windows.Forms;

namespace RemindAtDone;

public partial class App : Application
{
    internal Settings Settings { get; private set; } = new();
    internal ReceiptStore Store { get; private set; } = null!;
    internal LauncherWindow Launcher { get; private set; } = null!;
    internal bool MotionReduced => Settings.ReduceMotion || !SystemParameters.ClientAreaAnimation;
    private readonly CancellationTokenSource lifetime = new();
    private readonly ReturnRouter router = new();
    private Mutex? singleton;
    private Forms.NotifyIcon? tray;
    private System.Drawing.Icon? trayArtwork;
    private PanelView? panel;
    private PanelView? previewReturnPanel;
    private MouseObserver? previewClicks;
    private bool locked;
    private bool previewActive;
    internal bool IsPanelOpen=>panel is not null;
    internal void FloatingCollapsed()=>RefreshVisibility();
    internal nint LastExternalForeground{get;private set;}
    private long lastCard = -30000;
    private int additional;
    private Native.WinEvent? foregroundChanged;
    private Native.WinEvent? windowShown;
    private Native.WinEvent? foregroundBoundsChanged;
    private nint foregroundHook;
    private nint shownHook;
    private nint boundsHook;
    private Task? server;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        DispatcherUnhandledException+=(_,error)=>{AppPaths.Log("ui: "+error.Exception);error.Handled=true;Shutdown(1);};
        singleton = new Mutex(true, @"Local\" + Wire.Name, out var first);
        if (!first) { singleton.Dispose(); singleton = null; Shutdown(); return; }
        try
        {
            Settings = AppPaths.LoadSettings(); ApplyTheme(); Store = new ReceiptStore(AppPaths.Root);
            LastExternalForeground=Native.GetForegroundWindow();
            locked = !Native.InputDesktopAvailable();
            Launcher = new LauncherWindow(this);new WindowInteropHelper(Launcher).EnsureHandle();
            var work = Native.Screen(Launcher).WorkingArea;
            Native.Clamp(Launcher, Settings.Left ?? work.Right-(int)Math.Ceiling(Launcher.Width)-12, Settings.Top ?? work.Bottom - 120);
            UpdateUnread();
            using(var stream=GetResourceStream(View.IconUri).Stream)
            using(var artwork=new System.Drawing.Icon(stream,32,32))trayArtwork=(System.Drawing.Icon)artwork.Clone();
            tray = new Forms.NotifyIcon { Icon = trayArtwork, Text = "Remind at done", Visible = true };
            var menu = new Forms.ContextMenuStrip();
            menu.Items.Add("查看任务", null, (_, _) => Dispatcher.Invoke(() => OpenPanel()));
            menu.Items.Add("恢复悬浮入口", null, (_, _) => Dispatcher.Invoke(() => UpdateSettings(Settings with { HideLauncher = false })));
            menu.Items.Add("设置", null, (_, _) => Dispatcher.Invoke(() => OpenPanel("settings")));
            menu.Items.Add("退出", null, (_, _) => Dispatcher.Invoke(Shutdown));
            tray.ContextMenuStrip = menu; tray.DoubleClick += (_, _) => Dispatcher.Invoke(() => OpenPanel());
            SystemEvents.SessionSwitch += SessionChanged; SystemEvents.DisplaySettingsChanged += DisplayChanged;
            SystemEvents.UserPreferenceChanged += PreferenceChanged;
            // Use the event's window: GetForegroundWindow can still return the old
            // window while the activation event is being delivered.
            foregroundChanged = (_, _, hwnd, _, _, _, _) => Dispatcher.BeginInvoke(()=>{if(hwnd!=0)LastExternalForeground=hwnd;RefreshVisibilityAt(hwnd);});
            foregroundHook = Native.SetWinEventHook(3, 3, 0, foregroundChanged, 0, 0, 2);
            windowShown=(_,_,hwnd,obj,child,_,_)=>{if(obj==0 && child==0 && Native.IsVisibleTopLevel(hwnd))Dispatcher.BeginInvoke(RefreshVisibility);};
            shownHook=Native.SetWinEventHook(0x8002,0x8002,0,windowShown,0,0,2);
            // Full-screen transitions can resize the existing foreground window
            // without changing focus, or finish sizing after its activation event.
            foregroundBoundsChanged=(_,_,hwnd,obj,child,_,_)=>{if(obj==0 && child==0 && hwnd==Native.GetForegroundWindow())Dispatcher.BeginInvoke(RefreshVisibility);};
            boundsHook=Native.SetWinEventHook(0x800B,0x800B,0,foregroundBoundsChanged,0,0,2);
            RefreshVisibility();
            if(e.Args.Contains("--panel")) OpenPanel();
            server = Task.Run(() => Wire.ServeAsync(Store, report =>
            {
                Dispatcher.BeginInvoke(() => Received(report)); return Task.CompletedTask;
            }, id => AppPaths.LoadSettings().Instances.Any(x => x.Id == id), lifetime.Token));
            if (Store.RecoveryWarning is not null) { AppPaths.Log(Store.RecoveryWarning); OpenPanel(); panel?.ShowError("历史已恢复",Store.RecoveryWarning); }
        }
        catch (Exception error)
        {
            AppPaths.Log("startup: "+error.Message);
            var window=new Window{Title="Remind · 需要修复"};View.Setup(window,360,true);
            var content=new System.Windows.Controls.StackPanel();content.Children.Add(View.Text("暂时无法启动",20,true));
            content.Children.Add(View.Text(error.Message,13,muted:true));content.Children.Add(View.Button("关闭",()=>Shutdown(4)));window.Content=View.Shell(content);window.Closed+=(_,_)=>Shutdown(4);window.Show();
        }
    }

    private void Received(CompletionReport report)
    {
        UpdateUnread(); panel?.RefreshHistory(); RefreshVisibility();
        if(panel is not null || previewReturnPanel is not null)return;
        if (locked || Settings.DoNotDisturb || Settings.HideLauncher || Native.Fullscreen(Launcher)) return;
        if (Environment.TickCount64 - lastCard < 30000) { Launcher.Additional(++additional); return; }
        lastCard = Environment.TickCount64; additional = 0;
        Launcher.Present(report);
    }

    internal void CloseCard()
    {
        previewClicks?.Dispose();previewClicks=null;
        previewReturnPanel?.Dispose();previewReturnPanel=null;
        ClosePanel(true);Launcher?.Collapse(true);
    }
    internal void ClosePanel(bool immediately=false)
    {
        if(panel is null)return;
        var closing=panel;panel=null;closing.Dispose();Launcher.Collapse(immediately);
    }
    internal void PreviewNotification()
    {
        if(locked)return;
        if(panel is not null){previewReturnPanel=panel;panel.Suspend();panel=null;}
        previewActive=true;Launcher.Collapse(true);Launcher.Show();
        Launcher.Present(new CompletionReport{Title="从这里，接回你的工作",Summary="任务完成时，结果会从悬浮入口展开；片刻后轻轻收回，安静留在最近记录里。",Cwd=Environment.CurrentDirectory},true);
        previewClicks=new MouseObserver((message,point)=>
        {
            if(MouseObserver.IsButtonDown(message) && !Native.PointsTo(Launcher,point))Dispatcher.BeginInvoke(()=>{CloseCard();RefreshVisibility();});
        });
    }
    internal void PreviewEnded()
    {
        previewActive=false;
        previewClicks?.Dispose();previewClicks=null;
        if(previewReturnPanel is not null && !locked)
        {
            panel=previewReturnPanel;previewReturnPanel=null;panel.RefreshHistory();Launcher.PresentPanel(panel,false);
        }
        RefreshVisibility();
    }
    internal void OpenPanel(string? selected = null)
    {
        if (locked) return;
        if(panel is not null && selected is null){Launcher.Activate();return;}
        var restore=selected is null?previewReturnPanel:null;
        if(restore is not null)previewReturnPanel=null;
        CloseCard();panel=restore??new PanelView(this,selected);
        Launcher.PresentPanel(panel);RefreshVisibility();
    }

    internal async Task OpenTask(string instanceId, string threadId, string? eventId = null)
    {
        try
        {
            var instance = Settings.Instances.Single(x => x.Id == instanceId);
            if (eventId is not null) MarkRead(eventId);
            using var timeout = new CancellationTokenSource(15000);
            await router.OpenAsync(instance, threadId, timeout.Token);
        }
        catch (Exception error)
        {
            AppPaths.Log("resume: " + error.GetType().Name);
            OpenPanel(); panel?.ShowError("暂时无法返回任务",error.Message,threadId);
        }
    }
    internal void MarkRead(string id)
    {
        try { Store.MarkRead(id); UpdateUnread(); }
        catch (Exception error) { panel?.ShowError("已读状态未保存",error.Message); }
    }
    private void UpdateUnread() => Launcher.Unread(Store.Snapshot().Count(x => !x.IsRead));
    internal void SavePosition()
    {
        var r=Launcher.AnchorBounds();
        UpdateSettings(Settings with { Left = r.Left, Top = r.Top });
    }
    internal void UpdateSettings(Settings settings)
    {
        // Registration may have changed while the GUI was open; preserve current instances.
        settings = settings with { Instances = AppPaths.LoadSettings().Instances };
        if(settings.LoginStartup!=Settings.LoginStartup)
        {
            using var run = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
            if (settings.LoginStartup) run.SetValue("RemindAtDone", "\"" + Environment.ProcessPath + "\"");
            else run.DeleteValue("RemindAtDone", false);
        }
        AppPaths.SaveSettings(settings); Settings = settings; ApplyTheme(); RefreshVisibility();
        if (Settings.DoNotDisturb) CloseCard();
    }
    private void ApplyTheme()
    {
        using var personalize = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
        var dark = Settings.Theme == "dark" || Settings.Theme == "system" && personalize?.GetValue("AppsUseLightTheme") is int i && i == 0;
        string[] names = ["Surface", "Raised", "Hover", "Ink", "Muted", "Line", "Accent", "AccentInk"];
        string[] values = dark ? ["#111925", "#192435", "#233247", "#EDF3FA", "#9AA9BC", "#304057", "#A0EBCB", "#103729"] : ["#F7F9FC", "#EDF1F6", "#E2EAF2", "#223249", "#65758A", "#D7E0EB", "#26765F", "#FFFFFF"];
        for (var n = 0; n < names.Length; n++) Resources[names[n]] = new SolidColorBrush((Color)ColorConverter.ConvertFromString(values[n]));
        if (SystemParameters.HighContrast)
        {
            Resources["Surface"] = SystemColors.WindowBrush; Resources["Ink"] = SystemColors.WindowTextBrush;
            Resources["Muted"] = SystemColors.WindowTextBrush; Resources["Line"] = SystemColors.WindowTextBrush; Resources["Accent"] = SystemColors.HighlightBrush;
            Resources["Raised"] = SystemColors.WindowBrush; Resources["Hover"] = SystemColors.ControlBrush; Resources["AccentInk"] = SystemColors.HighlightTextBrush;
        }
    }
    private void RefreshVisibility()=>RefreshVisibilityAt(0);
    private void RefreshVisibilityAt(nint foreground)
    {
        if (locked || panel is null && !previewActive && Settings.HideLauncher) { Launcher.Hide(); CloseCard(); }
        else if (!Launcher.IsVisible) Launcher.Show();
        if(panel is null && !Launcher.Interactive && !previewActive && Native.Fullscreen(Launcher,foreground))Launcher.Collapse(true);
        Native.RaiseWithoutActivation(Launcher);
    }
    private void SessionChanged(object sender, SessionSwitchEventArgs e) => Dispatcher.BeginInvoke(() =>
    {
        if (e.Reason is SessionSwitchReason.SessionLock or SessionSwitchReason.RemoteDisconnect or SessionSwitchReason.ConsoleDisconnect) locked = true;
        if (e.Reason is SessionSwitchReason.SessionUnlock or SessionSwitchReason.RemoteConnect or SessionSwitchReason.ConsoleConnect) locked = false;
        if (locked) { Launcher.CancelDrag();CloseCard(); } RefreshVisibility();
    });
    private void DisplayChanged(object? sender, EventArgs e) => Dispatcher.BeginInvoke(() => { CloseCard();Native.Clamp(Launcher);SavePosition(); });
    private void PreferenceChanged(object sender, UserPreferenceChangedEventArgs e) => Dispatcher.BeginInvoke(ApplyTheme);
    protected override void OnExit(ExitEventArgs e)
    {
        lifetime.Cancel();panel?.Dispose();previewReturnPanel?.Dispose();previewClicks?.Dispose();tray?.Dispose();trayArtwork?.Dispose();
        SystemEvents.SessionSwitch -= SessionChanged; SystemEvents.DisplaySettingsChanged -= DisplayChanged; SystemEvents.UserPreferenceChanged -= PreferenceChanged;
        if (foregroundHook != 0) Native.UnhookWinEvent(foregroundHook);
        if(shownHook!=0)Native.UnhookWinEvent(shownHook);
        if(boundsHook!=0)Native.UnhookWinEvent(boundsHook);
        singleton?.ReleaseMutex(); singleton?.Dispose(); lifetime.Dispose(); base.OnExit(e);
    }
}
