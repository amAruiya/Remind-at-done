using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using RemindAtDone;
using RemindAtDone.Core;

internal static class ThemeProbe
{
    private const BindingFlags Hidden = BindingFlags.Instance | BindingFlags.NonPublic;
    private static readonly Dictionary<string, bool> Checks = [];
    [DllImport("user32.dll")] private static extern nint GetForegroundWindow();
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(nint hwnd);

    [STAThread]
    private static int Main(string[] args)
    {
        if(args.Length!=1)throw new ArgumentException("Pass the result JSON path.");
        var output=Path.GetFullPath(args[0]);Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var root=Path.Combine(Path.GetTempPath(),"rad-theme-live-"+Guid.NewGuid().ToString("N"));
        Environment.SetEnvironmentVariable("RAD_DATA_DIR",root);
        AppPaths.SaveSettings(new Settings{Theme="dark",ReduceMotion=true,HideLauncher=true,SelectedTab="completed",Left=3000,Top=1200});
        var foreground=GetForegroundWindow();var app=new App();app.InitializeComponent();var exit=1;string? failure=null;
        app.Startup+=(_,_)=>app.Dispatcher.BeginInvoke(new Action(async()=>
        {
            try
            {
                await Exercise(app);exit=Checks.Values.All(value=>value)?0:1;
            }
            catch(Exception error){failure=error.ToString();Console.Error.WriteLine(error);}
            finally
            {
                File.WriteAllText(output,JsonSerializer.Serialize(new{checks=Checks,error=failure,
                    high_contrast_scope="Controlled resource palette; system high-contrast mode was not changed."},new JsonSerializerOptions{WriteIndented=true}));
                app.Shutdown(exit);
            }
        }),DispatcherPriority.ContextIdle);
        try{app.Run();}
        finally{SetForegroundWindow(foreground);Directory.Delete(root,true);}
        return exit;
    }

    private static void Check(string name,bool value){Checks[name]=value;Console.WriteLine((value?"PASS ":"FAIL ")+name);}
    private static object Get(App app,string name)=>typeof(App).GetProperty(name,Hidden)!.GetValue(app)!;
    private static void Call(App app,string name,params object?[] args)=>typeof(App).GetMethod(name,Hidden)!.Invoke(app,args);
    private static Color ColorOf(Brush? brush)=>((SolidColorBrush)(brush??throw new InvalidOperationException("Missing brush"))).Color;
    private static Color Resource(App app,string key)=>ColorOf((Brush)app.Resources[key]);
    private static UserControl Panel(App app)=>(UserControl)typeof(App).GetField("panel",Hidden)!.GetValue(app)!;
    private static IEnumerable<T> Elements<T>(DependencyObject root) where T:DependencyObject
    {
        for(var i=0;i<VisualTreeHelper.GetChildrenCount(root);i++)
        {
            var child=VisualTreeHelper.GetChild(root,i);
            if(child is T value)yield return value;
            foreach(var descendant in Elements<T>(child))yield return descendant;
        }
    }
    private static Button Button(UserControl panel,string caption)=>Elements<Button>(panel).First(button=>
        AutomationProperties.GetName(button)==caption || button.Content is string text && text==caption);
    private static void Click(Button button)=>button.RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Button.ClickEvent));
    private static async Task Theme(App app,string value)
    {
        var settings=(Settings)Get(app,"Settings");
        typeof(App).GetProperty("Settings",Hidden)!.SetValue(app,settings with{Theme=value});
        // This is the same palette update used on UserPreferenceChanged. It
        // deliberately leaves the existing view and unsaved controls intact.
        Call(app,"ApplyTheme");await Task.Delay(100);
    }
    private static async Task Exercise(App app)
    {
        var store=(ReceiptStore)Get(app,"Store");
        var instance=Guid.NewGuid().ToString();var thread=Guid.NewGuid().ToString();var key="live-theme";
        store.Commit(new CompletionReport{InstanceId=instance,ThreadId=thread,TaskKey=key,EventId=CompletionReport.MakeEventId(instance,thread,key),
            Status="completed",Title="Theme check",Summary="Controlled UI fixture",Verification="No unrelated project tests run",
            CompletedAt=DateTimeOffset.UtcNow.ToString("O"),ElapsedSeconds=301,TimingSource="context",Cwd=AppPaths.Root});
        Call(app,"OpenPanel","completed");await Task.Delay(150);
        var panel=Panel(app);var row=Button(panel,"Theme check，查看详情");var tab=Button(panel,"已完成");
        await Theme(app,"light");
        Check("existing_history_row_follows_palette",ColorOf(row.Background)==Resource(app,"Raised"));
        Check("selected_tab_follows_palette",ColorOf(tab.Background)==Resource(app,"Hover"));
        Check("list_view_is_preserved",ReferenceEquals(panel,Panel(app)) && ReferenceEquals(row,Button(panel,"Theme check，查看详情")));

        Click(row);await Task.Delay(100);
        var open=Button(panel,"返回 Codex 任务  ↗");
        var verification=Elements<Border>(panel).First(border=>border.Child is StackPanel box && Elements<TextBlock>(box).Any(text=>text.Text=="验证记录"));
        await Theme(app,"dark");
        Check("detail_action_follows_palette",ColorOf(open.Background)==Resource(app,"Accent") && ColorOf(open.Foreground)==Resource(app,"AccentInk"));
        Check("detail_box_follows_palette",ColorOf(verification.Background)==Resource(app,"Raised"));
        Check("detail_view_is_preserved",ReferenceEquals(open,Button(panel,"返回 Codex 任务  ↗")));

        Click(Button(panel,"设置"));await Task.Delay(100);
        var reduce=Elements<CheckBox>(panel).Single(box=>Equals(box.Content,"减少动画"));reduce.IsChecked=false;
        var duration=Button(panel,"5 秒");Click(duration);var save=Button(panel,"保存设置");
        await Theme(app,"light");
        Check("settings_action_follows_palette",ColorOf(save.Background)==Resource(app,"Accent") && ColorOf(save.Foreground)==Resource(app,"AccentInk"));
        Check("selected_duration_follows_palette",ColorOf(duration.Background)==Resource(app,"Hover"));
        Check("unselected_duration_follows_palette",ColorOf(Button(panel,"8 秒").Background)==Resource(app,"Raised"));
        Check("unsaved_settings_survive_palette_change",reduce.IsChecked==false && ReferenceEquals(reduce,Elements<CheckBox>(panel).Single(box=>Equals(box.Content,"减少动画"))));

        var highContrast=new Dictionary<string,string>{{"Surface","#000000"},{"Raised","#000000"},{"Hover","#202020"},{"Ink","#FFFFFF"},
            {"Muted","#FFFFFF"},{"Line","#FFFFFF"},{"Accent","#FFFF00"},{"AccentInk","#000000"}};
        foreach(var (name,color) in highContrast)app.Resources[name]=new SolidColorBrush((Color)ColorConverter.ConvertFromString(color));
        await Task.Delay(100);
        Check("high_contrast_action_updates",ColorOf(save.Background)==Resource(app,"Accent") && ColorOf(save.Foreground)==Resource(app,"AccentInk"));
        Check("high_contrast_selection_updates",ColorOf(duration.Background)==Resource(app,"Hover") && ColorOf(Button(panel,"8 秒").Background)==Resource(app,"Raised"));
        Check("high_contrast_keeps_unsaved_settings",reduce.IsChecked==false);
    }
}
