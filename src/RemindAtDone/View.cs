using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PathShape = System.Windows.Shapes.Path;

namespace RemindAtDone;

internal static class View
{
    internal static readonly Uri IconUri=new("pack://application:,,,/Assets/remind-at-done.ico");
    private static readonly BitmapFrame WindowIcon=BitmapDecoder.Create(IconUri,BitmapCreateOptions.PreservePixelFormat,BitmapCacheOption.OnLoad).Frames.OrderByDescending(frame=>frame.PixelWidth).First();
    internal static Brush Brush(string key) => (Brush)Application.Current.Resources[key];
    internal static TextBlock Text(string text, double size = 13, bool bold = false, bool muted = false)
    {
        var block = new TextBlock { Text = text, FontSize = size, FontWeight = bold ? FontWeights.Medium : FontWeights.Normal,
            TextWrapping = TextWrapping.Wrap, LineHeight = size * 1.45, Margin = new Thickness(0, 2, 0, 2) };
        block.SetResourceReference(TextBlock.ForegroundProperty, muted ? "Muted" : "Ink");
        return block;
    }
    internal static Button Button(string text, Action action)
    {
        var button = new Button { Content = text, Margin = new Thickness(0, 2, 0, 2) };
        button.Click += (_, _) => action(); return button;
    }
    internal static Button IconButton(string icon, string label, Action action)
    {
        var button = new Button { Content = Icon(icon, 16), Width = 32, Height = 32, Padding = new Thickness(8), ToolTip = label };
        System.Windows.Automation.AutomationProperties.SetName(button, label);
        button.Click += (_, _) => action(); return button;
    }
    internal static PathShape Icon(string name, double size = 18, string color = "Muted")
    {
        var data = name switch
        {
            "close" => "M5,5 L15,15 M15,5 L5,15",
            "arrow" => "M5,15 L15,5 M5,5 L15,5 L15,15",
            "chevron" => "M7,4 L13,10 L7,16",
            "back" => "M13,4 L7,10 L13,16",
            "check" => "M4,10 L8,14 L16,6",
            "refresh" => "M16,7 A7,7 0 1 0 17,12 M16,2 L16,7 L11,7",
            "active" => "M10,2 A8,8 0 1 1 2,10 M10,6 L10,10 L14,10",
            "settings" => "M3,5 L17,5 M3,10 L17,10 M3,15 L17,15 M7,2 L7,8 M13,7 L13,13 M8,12 L8,18",
            "folder" => "M2,5 L8,5 L10,7 L18,7 L18,16 L2,16 Z",
            _ => "M10,1 C11,7 13,9 19,10 C13,11 11,13 10,19 C9,13 7,11 1,10 C7,9 9,7 10,1 Z"
        };
        var path = new PathShape { Data = Geometry.Parse(data), Width = size, Height = size, Stretch = Stretch.Uniform,
            StrokeThickness = 1.5, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, StrokeLineJoin = PenLineJoin.Round };
        path.SetResourceReference(PathShape.StrokeProperty, color); return path;
    }
    internal static Border Shell(UIElement content)
    {
        var border = new Border { CornerRadius = new CornerRadius(22), Padding = new Thickness(22), BorderThickness = new Thickness(1), Child = content };
        border.SetResourceReference(Border.BackgroundProperty, "Surface"); border.SetResourceReference(Border.BorderBrushProperty, "Line");
        return border;
    }
    internal static void Setup(Window window, double width, bool passive,Func<bool>? interactive=null)
    {
        window.Width = width; window.SizeToContent = SizeToContent.Height; window.WindowStyle = WindowStyle.None;
        window.AllowsTransparency = true; window.Background = Brushes.Transparent; window.ResizeMode = ResizeMode.NoResize;
        window.ShowInTaskbar = false; window.Topmost = true; window.UseLayoutRounding = true;
        window.Icon=WindowIcon;
        TextOptions.SetTextFormattingMode(window,TextFormattingMode.Display);
        TextOptions.SetTextRenderingMode(window,TextRenderingMode.Grayscale);
        if (passive) Native.NonActivating(window,interactive);
    }
}
