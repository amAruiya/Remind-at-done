using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using RemindAtDone.Core;
using PathShape = System.Windows.Shapes.Path;

namespace RemindAtDone;

internal sealed class LauncherWindow : Window
{
    private const double EntryScale=1, Diameter=40*EntryScale, Rest=56*EntryScale, Inset=(Rest-Diameter)/2;
    private double openWidth=364+Rest;
    private double openHeight=246;
    private double hostHeight=Rest;
    private double bodyOffset;
    private double bodyTopPadding;
    private readonly App app;
    private readonly Canvas canvas = new();
    private readonly PathShape surface = new() { StrokeThickness = 1 };
    private readonly Grid orb = new() { Width = Rest, Height = Rest };
    private readonly TextBlock badge = new() { FontSize = 10*EntryScale, FontWeight = FontWeights.Bold, Foreground = new SolidColorBrush(Color.FromRgb(16,55,41)), HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
    private readonly Border badgeShell;
    private readonly LinearGradientBrush orbFill=new(Color.FromRgb(45,61,84),Color.FromRgb(19,29,44),100);
    private readonly SolidColorBrush orbLine=new(Color.FromRgb(91,125,142));
    private readonly DispatcherTimer dwell = new();
    private FrameworkElement? body;
    private Button? more;
    private CompletionReport? report;
    private PanelView? taskPanel;
    private Geometry? outline;
    private Native.Rect restingBounds;
    private Native.Point down;
    private bool dragging, pressed, left, up;
    private bool panelAtPress;
    private MouseObserver? dragMouse;
    private bool preview;
    private bool retracting;
    private bool activatePanelOnShown;
    private bool heightAnimating;
    private int heightGeneration;
    private int motionGeneration;
    private double orbX, orbY;
    internal bool Expanded => report is not null || taskPanel is not null;
    internal bool Interactive=>taskPanel is not null;
    internal string? EventId => report?.EventId;
    private static readonly DependencyProperty RevealProperty = DependencyProperty.Register(nameof(Reveal), typeof(double), typeof(LauncherWindow),
        new PropertyMetadata(0d, (d, _) => ((LauncherWindow)d).DrawReveal()));
    private double Reveal { get => (double)GetValue(RevealProperty); set => SetValue(RevealProperty, value); }
    private static readonly DependencyProperty SurfaceHeightProperty=DependencyProperty.Register(nameof(SurfaceHeight),typeof(double),typeof(LauncherWindow),
        new PropertyMetadata(246d,(d,e)=>{var host=(LauncherWindow)d;host.openHeight=(double)e.NewValue;if(host.outline is not null){host.UpdateBounds();host.DrawReveal();}}));
    private double SurfaceHeight{get=>(double)GetValue(SurfaceHeightProperty);set=>SetValue(SurfaceHeightProperty,value);}

    internal LauncherWindow(App owner)
    {
        app = owner; Title = "Remind at done"; View.Setup(this, Rest, true,()=>Interactive); Height = Rest; SizeToContent = SizeToContent.Manual;
        Content = canvas; surface.SetResourceReference(PathShape.FillProperty, "Surface"); surface.SetResourceReference(PathShape.StrokeProperty, "Line"); canvas.Children.Add(surface);
        var disk = new Border { Width = Diameter, Height = Diameter, CornerRadius = new CornerRadius(Diameter/2), BorderThickness = new Thickness(EntryScale),
            Background = orbFill, BorderBrush = orbLine };
        var symbol=View.Icon("spark",21*EntryScale,"Accent");symbol.Stroke=new SolidColorBrush(Color.FromRgb(160,235,203));symbol.StrokeThickness=1.5*EntryScale;
        symbol.HorizontalAlignment=HorizontalAlignment.Center;symbol.VerticalAlignment=VerticalAlignment.Center;
        var trigger = new Button { Content = symbol, Padding = new Thickness(0), BorderThickness = new Thickness(0), Background = Brushes.Transparent,
            HorizontalContentAlignment = HorizontalAlignment.Center,VerticalContentAlignment=VerticalAlignment.Center, ToolTip = "查看任务" };
        System.Windows.Automation.AutomationProperties.SetName(trigger, "查看任务");
        System.Windows.Automation.AutomationProperties.SetAutomationId(trigger, "launcher.open");
        trigger.SizeChanged+=(_,_)=>trigger.Clip=new EllipseGeometry(new Rect(0,0,trigger.ActualWidth,trigger.ActualHeight));
        trigger.Click += (_, _) => {if(app.IsPanelOpen)app.ClosePanel();else app.OpenPanel();}; disk.Child = trigger; orb.Children.Add(disk);
        badgeShell = new Border { Child = badge, CornerRadius = new CornerRadius(8*EntryScale), Background = View.Brush("Accent"), Height = 16*EntryScale, MinWidth = 16*EntryScale,
            Padding = new Thickness(3*EntryScale,0,3*EntryScale,0), HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top, Visibility = Visibility.Collapsed };
        orb.Children.Add(badgeShell); canvas.Children.Add(orb);
        badge.SetResourceReference(TextBlock.ForegroundProperty,"AccentInk");
        badgeShell.SetResourceReference(Border.BackgroundProperty,"Accent");
        System.Windows.Automation.AutomationProperties.SetName(this, "任务提醒入口");
        orb.PreviewMouseLeftButtonDown += (_, e) =>
        {
            CancelDrag();panelAtPress=app.IsPanelOpen;
            Native.GetCursorPos(out down);restingBounds=AnchorBounds();
            pressed=true;dragging=false;dragMouse=new MouseObserver(TrackDrag);e.Handled=true;
        };
        Closed+=(_,_)=>CancelDrag();
        KeyDown+=(_,e)=>{if(e.Key==Key.Escape && app.IsPanelOpen){app.ClosePanel();e.Handled=true;}};
        Deactivated+=(_,_)=>{if(Interactive && app.IsPanelOpen)app.ClosePanel();};
        var menu = new ContextMenu(); var hide = new MenuItem { Header = "隐藏入口（从托盘恢复）" };
        hide.Click += (_, _) => app.UpdateSettings(app.Settings with { HideLauncher = true }); menu.Items.Add(hide); trigger.ContextMenu = menu;
        dwell.Tick += (_, _) => Collapse();
        SourceInitialized += (_, _) => HwndSource.FromHwnd(new WindowInteropHelper(this).Handle).AddHook((nint hwnd, int message, nint wp, nint lp, ref bool handled) =>
        {
            if (message == 0x02E0) Dispatcher.BeginInvoke(() => {app.CloseCard();Native.Clamp(this);});
            return 0;
        });
    }

    private void TrackDrag(uint message,Native.Point point)
    {
        if(!pressed)return;
        if(message==MouseObserver.Move)
        {
            if((Native.GetAsyncKeyState(1)&0x8000)==0){CancelDrag();return;}
            var dx=point.X-down.X;var dy=point.Y-down.Y;
            if(!dragging && Math.Sqrt((double)dx*dx+(double)dy*dy)>6*VisualTreeHelper.GetDpi(this).DpiScaleX){dragging=true;app.CloseCard();}
            if(dragging)Native.Position(this,restingBounds.Left+dx,restingBounds.Top+dy);
        }
        else if(message==MouseObserver.LeftUp)
        {
            var moved=dragging;var wasPanel=panelAtPress;CancelDrag();
            Dispatcher.BeginInvoke(()=>
            {
                if(moved){Native.Clamp(this,snap:true);app.SavePosition();}
                else if(wasPanel)app.ClosePanel();else app.OpenPanel();
            });
        }
    }
    internal void CancelDrag(){pressed=false;dragMouse?.Dispose();dragMouse=null;}

    internal void Unread(int count)
    {
        badge.Text = count.ToString(); badgeShell.Visibility = count > 0 ? Visibility.Visible : Visibility.Collapsed;
        ToolTip = count > 0 ? $"{count} 项未读完成结果" : "Remind · 任务入口";
    }

    internal void Present(CompletionReport value,bool isPreview=false)
    {
        Collapse(true); preview=isPreview; report = value; Native.GetWindowRect(new WindowInteropHelper(this).Handle, out restingBounds);
        body=BuildBody(value);body.Width=304;body.Measure(new Size(304,double.PositiveInfinity));
        body.Height=Math.Clamp(body.DesiredSize.Height,142,198);SurfaceHeight=body.Height+48;
        hostHeight=openHeight;
        openWidth=364+Rest;
        var work = Native.Screen(this).WorkingArea; var scale = VisualTreeHelper.GetDpi(this).DpiScaleX;
        left = restingBounds.Left + (restingBounds.Right - restingBounds.Left) / 2 > work.Left + work.Width / 2;
        up = restingBounds.Top - (openHeight - Rest) * scale >= work.Top;
        AttachBody(24,16);AnimateOpen();
    }

    internal void PresentPanel(PanelView view,bool activate=true)
    {
        Collapse(true);taskPanel=view;body=view;activatePanelOnShown=activate;
        Native.GetWindowRect(new WindowInteropHelper(this).Handle,out restingBounds);
        var work=Native.Screen(this).WorkingArea;var scale=VisualTreeHelper.GetDpi(this).DpiScaleX;
        left=restingBounds.Left+(restingBounds.Right-restingBounds.Left)/2>work.Left+work.Width/2;
        up=restingBounds.Bottom-work.Top>=work.Bottom-restingBounds.Top;
        var room=up?restingBounds.Bottom-work.Top:work.Bottom-restingBounds.Top;
        view.MaxHeight=Math.Max(200,Math.Min(work.Height*.7,room)/scale-16);
        view.Measure(new Size(view.Width,view.MaxHeight));SurfaceHeight=view.DesiredSize.Height+16;openWidth=view.Width+Rest+12;
        // Reserve the height once. Async results may change the visible surface,
        // but must not resize/move the layered HWND during the reveal.
        hostHeight=view.MaxHeight+16;
        Title="Remind · 任务";System.Windows.Automation.AutomationProperties.SetName(this,"任务面板");Native.SetInteractive(this,true);
        AttachBody(0,0);view.SizeChanged+=PanelSizeChanged;
        Show();if(activate)Activate();AnimateOpen();
    }

    private void PanelSizeChanged(object sender,SizeChangedEventArgs e)
    {
        if(taskPanel is null || retracting || Math.Abs(e.NewSize.Height+16-openHeight)<.5)return;
        var target=e.NewSize.Height+16;var current=SurfaceHeight;var generation=++heightGeneration;
        SurfaceHeight=current;BeginAnimation(SurfaceHeightProperty,null);
        heightAnimating=false;
        if(app.MotionReduced){SurfaceHeight=target;return;}
        heightAnimating=true;
        var resize=new DoubleAnimation(current,target,TimeSpan.FromMilliseconds(180)){EasingFunction=new CubicEase{EasingMode=EasingMode.EaseOut}};
        resize.Completed+=(_,_)=>
        {
            if(generation!=heightGeneration)return;
            SurfaceHeight=target;BeginAnimation(SurfaceHeightProperty,null);heightAnimating=false;DrawReveal();
        };
        BeginAnimation(SurfaceHeightProperty,resize);
    }

    private void AttachBody(double horizontalPadding,double verticalPadding)
    {
        retracting=false;bodyTopPadding=verticalPadding;
        body!.Opacity=0;body.IsHitTestVisible=false;
        UpdateBounds();
        Canvas.SetLeft(body,left?8+horizontalPadding:Rest+4+horizontalPadding);Canvas.SetTop(body,bodyOffset+8+verticalPadding);
        canvas.Children.Insert(1,body!);
        DrawReveal();
    }

    private void UpdateBounds()
    {
        var scale=VisualTreeHelper.GetDpi(this).DpiScaleX;
        bodyOffset=up?hostHeight-openHeight:0;
        orbX = left ? openWidth - Rest : 0; orbY = up ? hostHeight - Rest : 0;
        Width = openWidth; Height = hostHeight;
        Canvas.SetLeft(orb, orbX); Canvas.SetTop(orb, orbY);
        if(body is not null)Canvas.SetTop(body,bodyOffset+8+bodyTopPadding);
        var x=restingBounds.Left-(int)Math.Round(orbX*scale);var y=restingBounds.Top-(int)Math.Round(orbY*scale);
        Native.GetWindowRect(new WindowInteropHelper(this).Handle,out var current);
        if(current.Left!=x || current.Top!=y)Native.Position(this,x,y);
        // A tangent-continuous shoulder joins the surface to the endcap's top.
        var cx=openWidth-Rest/2;var cy=openHeight-Rest/2;var radius=Diameter/2;var bottom=cy+radius;
        var right=openWidth-Rest-4;var bend=cx-right;var shoulder=cy-radius;
        var shape=Geometry.Parse(FormattableString.Invariant($"M30,8 L{right-22},8 Q{right},8 {right},30 L{right},{shoulder-bend} C{right},{shoulder-bend*.447715} {cx-bend*.552285},{shoulder} {cx},{shoulder} A{radius},{radius} 0 0 1 {cx},{bottom} L30,{bottom} Q8,{bottom} 8,{bottom-22} L8,30 Q8,8 30,8 Z")).Clone();
        var mirror = new TransformGroup();
        if (!left) mirror.Children.Add(new ScaleTransform(-1,1,openWidth/2,0));
        if (!up) mirror.Children.Add(new ScaleTransform(1,-1,0,openHeight/2));
        if(bodyOffset!=0)mirror.Children.Add(new TranslateTransform(0,bodyOffset));
        shape.Transform = mirror; outline = shape; surface.Data = shape;
    }

    private void AnimateOpen()
    {
        var generation = ++motionGeneration;
        Reveal=0;BeginAnimation(RevealProperty,null);
        DrawReveal(); // A zero-to-zero DP assignment does not invoke its change callback.
        if (app.MotionReduced) { Reveal = 1; Opened(); }
        else
        {
            var reveal = new DoubleAnimation(0,1,TimeSpan.FromMilliseconds(380)) { EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut } };
            reveal.Completed += (_, _) => { if (generation == motionGeneration) { Reveal=1;BeginAnimation(RevealProperty,null);Opened(); } };
            BeginAnimation(RevealProperty, reveal);
        }
    }
    private void Opened(){if(taskPanel is not null){if(activatePanelOnShown)taskPanel.FocusFirst();}else StartDwell();}

    private FrameworkElement BuildBody(CompletionReport value)
    {
        var root = new DockPanel();
        var footer = new DockPanel { LastChildFill = false, Margin = new Thickness(0,10,0,0) }; DockPanel.SetDock(footer,Dock.Bottom); root.Children.Add(footer);
        var open = View.Button(preview?"预览效果":"查看结果  ↗", async () => { var wasPreview=preview;Collapse();if(!wasPreview)await app.OpenTask(value.InstanceId,value.ThreadId,value.EventId); });
        open.SetResourceReference(Button.ForegroundProperty,"Accent"); open.FontWeight = FontWeights.SemiBold; open.Padding = new Thickness(0,4,8,4); footer.Children.Add(open);
        more = View.Button("", () => { Collapse(true); app.OpenPanel("completed"); }); more.FontSize=11; more.Padding=new Thickness(8,4,0,4); more.Visibility=Visibility.Collapsed; footer.Children.Add(more);
        var top = new DockPanel { Margin = new Thickness(0,0,0,7) }; DockPanel.SetDock(top,Dock.Top); root.Children.Add(top);
        var close = View.IconButton("close","收起提醒",() => Collapse()); close.Width=24; close.Height=24; close.Padding=new Thickness(5); DockPanel.SetDock(close,Dock.Right); top.Children.Add(close);
        var label = View.Text("已完成  /  " + new DirectoryInfo(value.Cwd).Name,11,true); label.SetResourceReference(TextBlock.ForegroundProperty,"Accent"); label.MaxWidth=260; label.MaxHeight=20; label.TextTrimming=TextTrimming.CharacterEllipsis; top.Children.Add(label);
        var words = new StackPanel(); var title = View.Text(value.Title,18,true); title.MaxHeight=52; words.Children.Add(title);
        var summary = View.Text(value.Summary,12.5,muted:true); summary.Margin=new Thickness(0,6,0,0); summary.MaxHeight=54; summary.TextTrimming=TextTrimming.CharacterEllipsis; words.Children.Add(summary);
        if (value.Verification is not null) { var verification=View.Text("验证 · "+value.Verification,11,muted:true); verification.MaxHeight=18; verification.TextTrimming=TextTrimming.CharacterEllipsis; verification.Margin=new Thickness(0,8,0,0); words.Children.Add(verification); }
        var content = new Button { Content=words, Padding=new Thickness(0), HorizontalContentAlignment=HorizontalAlignment.Stretch, VerticalContentAlignment=VerticalAlignment.Top };
        System.Windows.Automation.AutomationProperties.SetName(content,value.Title+"，打开任务"); content.Click+=async(_,_)=>{var wasPreview=preview;Collapse();if(!wasPreview)await app.OpenTask(value.InstanceId,value.ThreadId,value.EventId);}; root.Children.Add(content);
        return root;
    }

    private void StartDwell() { dwell.Interval=TimeSpan.FromSeconds(app.Settings.CardSeconds is 5 or 8 or 10 ? app.Settings.CardSeconds : 8); dwell.Start(); }
    internal void Additional(int count) { if (more is not null) { more.Content=$"另有 {count} 项"; more.Visibility=Visibility.Visible; } }
    internal void Collapse(bool immediately = false)
    {
        if (!Expanded) return;
        if(retracting && !immediately)return;
        retracting=true;
        heightGeneration++;SurfaceHeight=openHeight;BeginAnimation(SurfaceHeightProperty,null);heightAnimating=false;
        if(body is not null)body.IsHitTestVisible=false;
        if(taskPanel is not null){Native.SetInteractive(this,false);Native.RestoreFocus(this,app.LastExternalForeground);}
        dwell.Stop(); var generation=++motionGeneration; var current=Reveal;Reveal=current;BeginAnimation(RevealProperty,null);
        if (immediately || app.MotionReduced) { FinishCollapse(); return; }
        var retract=new DoubleAnimation(current,0,TimeSpan.FromMilliseconds(260)) { EasingFunction=new CubicEase { EasingMode=EasingMode.EaseInOut } };
        retract.Completed+=(_,_)=>{ if(generation==motionGeneration) FinishCollapse(); }; BeginAnimation(RevealProperty,retract);
    }
    private void FinishCollapse()
    {
        Reveal=0;BeginAnimation(RevealProperty,null);report=null;surface.Data=null;outline=null;retracting=false;
        if(taskPanel is not null)taskPanel.SizeChanged-=PanelSizeChanged;
        taskPanel=null;Native.SetInteractive(this,false);
        if(body is not null) canvas.Children.Remove(body); body=null; more=null;
        Width=Rest; Height=Rest;hostHeight=Rest;bodyOffset=0;canvas.Clip=null;Canvas.SetLeft(orb,0); Canvas.SetTop(orb,0);
        UpdateLayout();
        Native.SetRegion(this,null); Native.Position(this,restingBounds.Left,restingBounds.Top);
        Title="Remind at done";System.Windows.Automation.AutomationProperties.SetName(this,"任务提醒入口");
        if(preview){preview=false;app.PreviewEnded();}else app.FloatingCollapsed();
    }
    private void DrawReveal()
    {
        if(outline is null) return;
        var p=Math.Clamp(Reveal,0,1); var cx=orbX+Rest/2; var cy=orbY+Rest/2;
        orbFill.Opacity=1-p;orbLine.Opacity=1-p;
        var x0=(orbX+Inset)*(1-p)+8*p; var y0=(orbY+Inset)*(1-p)+(bodyOffset+8)*p;
        var x1=(orbX+Rest-Inset)*(1-p)+(openWidth-8)*p; var y1=(orbY+Rest-Inset)*(1-p)+(bodyOffset+openHeight-8)*p;
        var clip=new Rect(x0,y0,x1-x0,y1-y0);
        var extended=new CombinedGeometry(GeometryCombineMode.Intersect,outline,new RectangleGeometry(clip));
        var visible=new CombinedGeometry(GeometryCombineMode.Union,extended,new EllipseGeometry(new Point(cx,cy),Diameter/2+2,Diameter/2+2));
        if(body is not null) { body.Opacity=Math.Clamp((p-.45)/.55,0,1); body.IsHitTestVisible=p>.95 && !retracting && !heightAnimating; }
        // HRGN is also the input boundary, not just a visual animation mask.
        var withBadge=new CombinedGeometry(GeometryCombineMode.Union,visible,new RectangleGeometry(new Rect(orbX+32*EntryScale,orbY,24*EntryScale,20*EntryScale),8*EntryScale,8*EntryScale));
        canvas.Clip=withBadge;
        Native.SetRegion(this,withBadge);
    }
    internal Native.Rect AnchorBounds()
    {
        if (Expanded) return restingBounds;
        Native.GetWindowRect(new WindowInteropHelper(this).Handle,out var rect); return rect;
    }
    internal bool PointsToEntry(Native.Point point)
    {
        if(!Native.PointsTo(this,point))return false;
        var rect=AnchorBounds();var scale=VisualTreeHelper.GetDpi(this).DpiScaleX;
        var dx=point.X-(rect.Left+Rest*scale/2);var dy=point.Y-(rect.Top+Rest*scale/2);
        var radius=(Diameter/2+1)*scale;return dx*dx+dy*dy<=radius*radius;
    }
}
