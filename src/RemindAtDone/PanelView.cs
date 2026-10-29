using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using RemindAtDone.Core;

namespace RemindAtDone;

internal sealed class PanelView : UserControl,IDisposable
{
    private readonly App app;
    private readonly DockPanel layout=new();
    private readonly StackPanel rows=new();
    private readonly TextBlock status=View.Text("",11,muted:true);
    private readonly TextBlock paging=View.Text("",11,muted:true);
    private readonly TextBlock heading=View.Text("任务",22,true);
    private readonly Button active,completed,back,forward;
    private readonly Border tabRail;
    private readonly Border alert=new(){CornerRadius=new CornerRadius(10),Padding=new Thickness(12),Margin=new Thickness(0,0,0,12),Visibility=Visibility.Collapsed};
    private readonly ScrollViewer scroller;
    private readonly DockPanel footer=new(){Margin=new Thickness(0,14,0,0)};
    private readonly StackPanel pagination=new(){Orientation=Orientation.Horizontal,HorizontalAlignment=HorizontalAlignment.Right};
    private readonly StackPanel top=new();
    private string tab,screen="list";
    private int page;
    private IReadOnlyList<ActiveTask> snapshot=[];
    private CancellationTokenSource? query;
    private MouseObserver? outsideClicks;
    private bool initialized;

    internal PanelView(App owner,string? selected)
    {
        app=owner;Width=420;
        tab=selected is "active" or "completed" ? selected : app.Settings.SelectedTab;
        if(tab is not("active" or "completed")) tab="active";
        DockPanel.SetDock(top,Dock.Top); layout.Children.Add(top);
        var header=new DockPanel();
        var actions=new StackPanel{Orientation=Orientation.Horizontal}; DockPanel.SetDock(actions,Dock.Right);
        actions.Children.Add(View.IconButton("refresh","刷新",Refresh));
        actions.Children.Add(View.IconButton("settings","设置",ShowSettings));
        actions.Children.Add(View.IconButton("close","关闭面板",Close)); header.Children.Add(actions);
        var brand=new StackPanel(); var wordmark=View.Text("REMIND",10,true,muted:true); wordmark.Margin=new Thickness(0,0,0,3);
        brand.Children.Add(wordmark); brand.Children.Add(heading); header.Children.Add(brand); top.Children.Add(header);
        var tabs=new Grid(); tabs.ColumnDefinitions.Add(new()); tabs.ColumnDefinitions.Add(new());
        active=View.Button("进行中",()=>Select("active")); completed=View.Button("已完成",()=>Select("completed"));
        active.HorizontalContentAlignment=HorizontalAlignment.Center; completed.HorizontalContentAlignment=HorizontalAlignment.Center;
        active.Padding=completed.Padding=new Thickness(12,9,12,9); active.Margin=completed.Margin=new Thickness(0);
        Grid.SetColumn(completed,1); tabs.Children.Add(active); tabs.Children.Add(completed);
        tabRail=new Border{Child=tabs,CornerRadius=new CornerRadius(14),Padding=new Thickness(4),Margin=new Thickness(0,20,0,12)};
        tabRail.SetResourceReference(Border.BackgroundProperty,"Raised"); top.Children.Add(tabRail);
        status.Margin=new Thickness(2,0,0,12); top.Children.Add(status);
        alert.SetResourceReference(Border.BackgroundProperty,"Raised"); top.Children.Add(alert);
        DockPanel.SetDock(footer,Dock.Bottom); layout.Children.Add(footer);
        back=View.IconButton("back","上一页",()=>{page--;Render();}); forward=View.IconButton("chevron","下一页",()=>{page++;Render();});
        paging.VerticalAlignment=VerticalAlignment.Center;paging.Margin=new Thickness(8,0,8,0);
        pagination.Children.Add(back);pagination.Children.Add(paging);pagination.Children.Add(forward);DockPanel.SetDock(pagination,Dock.Right);
        scroller=new ScrollViewer{Content=rows,MaxHeight=360,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,HorizontalScrollBarVisibility=ScrollBarVisibility.Disabled,Padding=new Thickness(0,0,4,0)};
        layout.Children.Add(scroller); Content=new Border{Padding=new Thickness(22),Child=layout};
        KeyboardNavigation.SetTabNavigation(this,KeyboardNavigationMode.Cycle);
        Loaded+=(_,_)=>
        {
            outsideClicks=new MouseObserver((message,point)=>
            {
                if(!IsLoaded || !MouseObserver.IsButtonDown(message) || Native.PointsTo(app.Launcher,point))return;
                Dispatcher.BeginInvoke(()=>{if(IsLoaded)Close();});
            });
            if(!initialized){initialized=true;if(screen=="list" && tab=="active")Refresh();}
        };
        Unloaded+=(_,_)=>Suspend();
        if(selected=="settings")ShowSettings();
        else {status.Text=tab=="active"?"正在读取任务状态…":"最近 3 天 · 最多 20 项";Render();}
    }
    private void Close()=>app.ClosePanel();
    internal void FocusFirst(){if(screen=="list")Keyboard.Focus(tab=="active"?active:completed);else MoveFocus(new TraversalRequest(FocusNavigationDirection.First));}
    internal void Suspend(){outsideClicks?.Dispose();outsideClicks=null;query?.Cancel();}
    public void Dispose(){Suspend();query?.Dispose();query=null;}

    private void Select(string value)
    {
        query?.Cancel(); tab=value; page=0; screen="list"; alert.Visibility=Visibility.Collapsed;
        app.UpdateSettings(app.Settings with{SelectedTab=tab}); Refresh();
    }
    internal void Refresh()
    {
        if(screen!="list") { screen="list"; Render(); }
        if(tab=="active") _=Query();
        else { status.Text="最近 3 天 · 最多 20 项"; Render(); }
    }
    internal void RefreshHistory()
    {
        if(screen=="list" && tab=="completed") Render(); else UpdateTabs();
    }
    private async Task Query()
    {
        query?.Cancel();query?.Dispose();query=new CancellationTokenSource(TimeSpan.FromSeconds(30));var current=query;
        status.Text="正在读取任务状态…"; Render();
        try
        {
            if(app.Settings.Instances.Count==0) throw new InvalidOperationException("请先登记本机 Codex 实例。");
            var tasks=new List<ActiveTask>();var incomplete=0;
            foreach(var instance in app.Settings.Instances)
            {
                await using var client=await CodexClient.ConnectAsync(instance,current.Token);
                var response=await client.ActiveAsync(instance,current.Token);tasks.AddRange(response.Tasks);incomplete+=response.FailedReads;
            }
            if(current!=query || current.IsCancellationRequested) return;
            if(incomplete>0 && tasks.Count==0 && snapshot.Count>0)
            {
                status.Text="未更新 · 线程读取失败，上次列表已保留";
                if(screen=="list")Render();return;
            }
            snapshot=tasks.OrderByDescending(x=>x.Waiting).ToArray();
            status.Text=$"更新于 {DateTime.Now:HH:mm:ss}"+(incomplete>0?$" · {incomplete} 项暂未读取":" · 按需刷新");
            if(screen=="list") Render();
        }
        catch(Exception error)
        {
            if(current!=query || !IsLoaded || tab!="active" || screen!="list") return;
            status.Text="未更新 · 上次列表已保留"; AppPaths.Log("active: "+error.GetType().Name);
            if(screen=="list") { Render();ShowError("暂时无法读取任务","请确认 Codex 已运行，再点击右上角刷新。"); }
        }
    }
    private void UpdateTabs()
    {
        static StackPanel Caption(string label,int count,bool selected)
        {
            var content=new StackPanel{Orientation=Orientation.Horizontal};var text=View.Text(label,13,true);text.SetResourceReference(TextBlock.ForegroundProperty,selected?"Accent":"Muted");content.Children.Add(text);
            var number=View.Text(count.ToString(),11,muted:true);number.Margin=new Thickness(8,3,0,0);content.Children.Add(number);return content;
        }
        active.Content=Caption("进行中",snapshot.Count,tab=="active");completed.Content=Caption("已完成",app.Store.Snapshot().Count,tab=="completed");
        System.Windows.Automation.AutomationProperties.SetName(active,"进行中"); System.Windows.Automation.AutomationProperties.SetName(completed,"已完成");
        foreach(var (button,selected) in new[]{(active,tab=="active"),(completed,tab=="completed")})
        {
            if(selected)button.SetResourceReference(Button.BackgroundProperty,"Hover");else button.Background=Brushes.Transparent;
            button.SetResourceReference(Button.ForegroundProperty,selected?"Accent":"Muted"); button.FontWeight=selected?FontWeights.SemiBold:FontWeights.Normal;
        }
    }
    private void Render()
    {
        rows.Children.Clear();footer.Children.Clear();tabRail.Visibility=Visibility.Visible;status.Visibility=Visibility.Visible;
        heading.Text="任务"; UpdateTabs();
        var history=app.Store.Snapshot();var count=tab=="completed"?history.Count:snapshot.Count;
        var pages=Math.Max(1,(count+9)/10);page=Math.Clamp(page,0,pages-1);
        if(count==0)
        {
            var empty=new StackPanel{Margin=new Thickness(12,54,12,36),HorizontalAlignment=HorizontalAlignment.Center};
            var illustration=new Border{Child=View.Icon(tab=="active"?"active":"check",28,"Accent"),Width=64,Height=64,CornerRadius=new CornerRadius(22),Padding=new Thickness(18),Margin=new Thickness(0,0,0,18)};
            illustration.SetResourceReference(Border.BackgroundProperty,"Raised");
            empty.Children.Add(illustration);
            empty.Children.Add(View.Text(tab=="completed"?"还没有完成提醒":status.Text.StartsWith("正在")?"正在读取任务…":status.Text.StartsWith("未更新")||status.Text.Contains("暂未读取")?"任务状态暂不可用":"当前没有进行中的任务",14,true));
            empty.Children.Add(View.Text(tab=="completed"?"完成的长任务会在这里留下结果。":"点击刷新，查看最新任务状态。",12,muted:true)); rows.Children.Add(empty);
        }
        if(tab=="completed")
        {
            string? previousDay=null;
            foreach(var receipt in history.Skip(page*10).Take(10))
            {
                var day=DateTimeOffset.Parse(receipt.Report.CompletedAt).ToLocalTime();
                var group=day.Date==DateTime.Today?"今天":day.Date==DateTime.Today.AddDays(-1)?"昨天":day.ToString("M 月 d 日");
                if(group!=previousDay){var label=View.Text(group,11,true,muted:true);label.Margin=new Thickness(2,7,0,9);rows.Children.Add(label);previousDay=group;}
                rows.Children.Add(TaskRow(receipt.Report.Title,new DirectoryInfo(receipt.Report.Cwd).Name,day.ToString("HH:mm"),receipt.Report.Summary,
                    "check",!receipt.IsRead,()=>ShowDetail(receipt)));
            }
        }
        else foreach(var task in snapshot.Skip(page*10).Take(10))
            rows.Children.Add(TaskRow(task.Title,new DirectoryInfo(task.Cwd).Name,task.Status,null,"active",task.Waiting,
                async()=>await app.OpenTask(task.InstanceId,task.ThreadId)));
        var note=View.Text(tab=="completed"?$"保留 {count} 项结果":$"{count} 项主任务",11,muted:true);note.VerticalAlignment=VerticalAlignment.Center;footer.Children.Add(note);
        paging.Text=$"{page+1} / {pages}";footer.Children.Add(pagination);back.IsEnabled=page>0;forward.IsEnabled=page+1<pages;
    }
    private static Button TaskRow(string title,string project,string trailing,string? summary,string icon,bool marked,Action action)
    {
        var row=new Grid();row.ColumnDefinitions.Add(new(){Width=new GridLength(34)});row.ColumnDefinitions.Add(new(){Width=new GridLength(1,GridUnitType.Star)});row.ColumnDefinitions.Add(new(){Width=new GridLength(15)});
        var marker=new Border{Width=25,Height=25,CornerRadius=new CornerRadius(8),Padding=new Thickness(6),VerticalAlignment=VerticalAlignment.Top,Margin=new Thickness(0,2,9,0),Child=View.Icon(icon,13,marked?"Accent":"Muted")};
        marker.SetResourceReference(Border.BackgroundProperty,marked?"Hover":"Surface");row.Children.Add(marker);
        var words=new StackPanel();Grid.SetColumn(words,1);row.Children.Add(words);
        var name=View.Text(title,14,true);name.MaxHeight=42;name.TextTrimming=TextTrimming.CharacterEllipsis;words.Children.Add(name);
        var metadata=new DockPanel{Margin=new Thickness(0,5,0,0)};
        var state=View.Text(trailing,10.5,muted:true);DockPanel.SetDock(state,Dock.Right);metadata.Children.Add(state);
        var folder=View.Text(project,11,muted:true);folder.MaxHeight=18;folder.Margin=new Thickness(0,2,10,2);folder.TextTrimming=TextTrimming.CharacterEllipsis;metadata.Children.Add(folder);words.Children.Add(metadata);
        if(summary is not null){var description=View.Text(summary,12,muted:true);description.MaxHeight=36;description.TextTrimming=TextTrimming.CharacterEllipsis;description.Margin=new Thickness(0,7,0,0);words.Children.Add(description);}
        var chevron=View.Icon("chevron",12);Grid.SetColumn(chevron,2);row.Children.Add(chevron);
        var button=new Button{Content=row,Padding=new Thickness(13),Margin=new Thickness(0,0,0,8),HorizontalContentAlignment=HorizontalAlignment.Stretch};
        button.SetResourceReference(Button.BackgroundProperty,"Raised");
        System.Windows.Automation.AutomationProperties.SetName(button,title+(summary is null?"，"+trailing+"，打开任务":"，查看详情"));button.Click+=(_,_)=>action();return button;
    }
    private void InnerPage(string title)
    {
        query?.Cancel(); screen="inner";rows.Children.Clear();footer.Children.Clear();tabRail.Visibility=Visibility.Collapsed;status.Visibility=Visibility.Collapsed;alert.Visibility=Visibility.Collapsed;heading.Text=title;
        var backLink=View.Button("‹  返回任务列表",()=>{screen="list";Refresh();});backLink.SetResourceReference(Button.ForegroundProperty,"Muted");backLink.Padding=new Thickness(0,13,0,16);rows.Children.Add(backLink);
    }
    private void ShowDetail(Receipt receipt)
    {
        InnerPage("完成结果");var value=receipt.Report;
        rows.Children.Add(View.Text("✓  已完成",11,true,muted:true));rows.Children.Add(View.Text(value.Title,21,true));
        rows.Children.Add(View.Text(new DirectoryInfo(value.Cwd).Name+" · "+DateTimeOffset.Parse(value.CompletedAt).ToLocalTime().ToString("M/d HH:mm"),11,muted:true));
        var summary=View.Text(value.Summary,14);summary.Margin=new Thickness(0,22,0,18);rows.Children.Add(summary);
        if(value.Verification is not null)
        {
            var box=new StackPanel();box.Children.Add(View.Text("验证记录",11,true,muted:true));box.Children.Add(View.Text(value.Verification,13));
            var verification=new Border{Child=box,CornerRadius=new CornerRadius(12),Padding=new Thickness(14)};
            verification.SetResourceReference(Border.BackgroundProperty,"Raised");rows.Children.Add(verification);
        }
        rows.Children.Add(View.Text($"实际经过 {value.ElapsedSeconds/60:F1} 分钟",11,muted:true));
        var open=View.Button("返回 Codex 任务  ↗",async()=>await app.OpenTask(value.InstanceId,value.ThreadId,value.EventId));
        open.Tag="primary";open.SetResourceReference(Button.BackgroundProperty,"Accent");open.SetResourceReference(Button.ForegroundProperty,"AccentInk");open.HorizontalContentAlignment=HorizontalAlignment.Center;open.Padding=new Thickness(16,12,16,12);footer.Children.Add(open);
        rows.Children.Add(View.Button("复制任务标识",()=>Clipboard.SetText(value.ThreadId)));app.MarkRead(value.EventId);
    }
    internal void ShowError(string title,string message,string? threadId=null)
    {
        var text=new StackPanel();text.Children.Add(View.Text(title,12,true));text.Children.Add(View.Text(message,11,muted:true));
        if(threadId is not null)text.Children.Add(View.Button("复制任务标识",()=>Clipboard.SetText(threadId)));
        alert.Child=text;alert.Visibility=Visibility.Visible;
    }
    private void ShowSettings()
    {
        InnerPage("偏好设置");var options=app.Settings;
        CheckBox Toggle(string label,bool value){var control=new CheckBox{Content=label,IsChecked=value,Margin=new Thickness(0,9,0,9)};rows.Children.Add(control);return control;}
        var dnd=Toggle("免打扰 · 只接收结果",options.DoNotDisturb);var reduce=Toggle("减少动画",options.ReduceMotion);
        var hide=Toggle("隐藏悬浮入口",options.HideLauncher);var startup=Toggle("登录时启动",options.LoginStartup);
        rows.Children.Add(View.Text("显示时长",11,true,muted:true));
        var durations=new StackPanel{Orientation=Orientation.Horizontal,Margin=new Thickness(0,6,0,18)};
        var seconds=options.CardSeconds;var durationButtons=new List<(Button Button,int Value)>();
        foreach(var value in new[]{5,8,10})
        {
            var button=View.Button(value+" 秒",()=>{seconds=value;foreach(var choice in durationButtons)choice.Button.SetResourceReference(Button.BackgroundProperty,choice.Value==seconds?"Hover":"Raised");});
            button.SetResourceReference(Button.BackgroundProperty,value==seconds?"Hover":"Raised");button.Margin=new Thickness(0,0,6,0);durationButtons.Add((button,value));durations.Children.Add(button);
        }
        rows.Children.Add(durations);rows.Children.Add(View.Text("外观",11,true,muted:true));
        var themes=new StackPanel{Orientation=Orientation.Horizontal,Margin=new Thickness(0,6,0,16)};var theme=options.Theme;var themeButtons=new List<(Button Button,string Value)>();
        foreach(var (value,label) in new[]{("dark","深色"),("light","浅色"),("system","跟随系统")})
        {
            var button=View.Button(label,()=>{theme=value;foreach(var choice in themeButtons)choice.Button.SetResourceReference(Button.BackgroundProperty,choice.Value==theme?"Hover":"Raised");});
            button.SetResourceReference(Button.BackgroundProperty,value==theme?"Hover":"Raised");button.Margin=new Thickness(0,0,6,0);themeButtons.Add((button,value));themes.Children.Add(button);
        }
        rows.Children.Add(themes);rows.Children.Add(View.Text("已完成结果仅保留最近 3 天，最多 20 项。",11,muted:true));
        rows.Children.Add(View.Button("预览展开效果",app.PreviewNotification));
        var save=View.Button("保存设置",()=>
        {
            try{app.UpdateSettings(options with{DoNotDisturb=dnd.IsChecked==true,ReduceMotion=reduce.IsChecked==true,HideLauncher=hide.IsChecked==true,LoginStartup=startup.IsChecked==true,CardSeconds=seconds,Theme=theme});screen="list";Refresh();}
            catch(Exception error){ShowError("设置未保存",error.Message);}
        });save.Tag="primary";save.SetResourceReference(Button.BackgroundProperty,"Accent");save.SetResourceReference(Button.ForegroundProperty,"AccentInk");save.HorizontalContentAlignment=HorizontalAlignment.Center;save.Padding=new Thickness(16,12,16,12);footer.Children.Add(save);
    }
}
