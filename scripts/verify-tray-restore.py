"""Exercise the real tray menu of an isolated instance, identified by HWND + icon ID."""
import argparse
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();app=args.app.resolve();u=ctypes.windll.user32;s=ctypes.windll.shell32
ctypes.windll.shcore.SetProcessDpiAwareness(2);u.GetForegroundWindow.restype=w.HWND;u.SetForegroundWindow.argtypes=[w.HWND]
class GUID(ctypes.Structure):_fields_=[('a',w.DWORD),('b',w.WORD),('c',w.WORD),('d',w.BYTE*8)]
class Identity(ctypes.Structure):_fields_=[('size',w.DWORD),('hwnd',w.HWND),('uid',w.UINT),('guid',GUID)]
s.Shell_NotifyIconGetRect.argtypes=[ctypes.POINTER(Identity),ctypes.POINTER(w.RECT)]
cursor=w.POINT();u.GetCursorPos(ctypes.byref(cursor));foreground=u.GetForegroundWindow();result={};gui=None
def owned_windows(pid):
    found=[]
    @ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    def callback(hwnd,_):
        owner=w.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid:found.append(hwnd)
        return True
    u.EnumWindows(callback,0);return found
def tray_rect(pid):
    for hwnd in owned_windows(pid):
        for number in range(5):
            identity=Identity();identity.size=ctypes.sizeof(identity);identity.hwnd=hwnd;identity.uid=number;rect=w.RECT()
            if s.Shell_NotifyIconGetRect(ctypes.byref(identity),ctypes.byref(rect))==0 and rect.right>rect.left:return rect
    return None
def launcher_visible(pid):
    for hwnd in owned_windows(pid):
        title=ctypes.create_unicode_buffer(128);u.GetWindowTextW(hwnd,title,128)
        if title.value=='Remind at done' and u.IsWindowVisible(hwnd):return True
    return False
try:
    with tempfile.TemporaryDirectory(prefix='rad-tray-') as directory:
        root=Path(directory);settings=json.loads((Path(os.environ['LOCALAPPDATA'])/'RemindAtDone/settings.json').read_text(encoding='utf-8'))
        settings.update(hide_launcher=True,do_not_disturb=True,left=-68,top=1300,login_startup=False)
        (root/'settings.json').write_text(json.dumps(settings),encoding='utf-8');env=dict(os.environ,RAD_DATA_DIR=str(root))
        gui=subprocess.Popen([str(app/'RemindAtDone.exe')],env=env,creationflags=0x08000000)
        for _ in range(60):
            rect=tray_rect(gui.pid)
            if rect:break
            time.sleep(.05)
        if not rect:raise RuntimeError('Owned tray icon is not currently accessible; no unrelated icon was clicked.')
        result['starts_hidden']=not launcher_visible(gui.pid)
        point_probe=root/'point.ps1';point_probe.write_text(r'''
param([int]$X,[int]$Y)
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
Add-Type -AssemblyName WindowsBase
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$element=[System.Windows.Automation.AutomationElement]::FromPoint((New-Object System.Windows.Point $X,$Y))
$items=@()
for($index=0;$index -lt 5 -and $element;$index++) {
    $items+=@{name=$element.Current.Name;id=$element.Current.AutomationId;class=$element.Current.ClassName}
    $element=[System.Windows.Automation.TreeWalker]::RawViewWalker.GetParent($element)
}
$items | ConvertTo-Json -Compress
''',encoding='utf-8-sig')
        menu=root/'menu.ps1';menu.write_text(r'''
param([int]$ProcessId,[string]$Action)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$condition=New-Object System.Windows.Automation.PropertyCondition ([System.Windows.Automation.AutomationElement]::ProcessIdProperty),$ProcessId
for($attempt=0;$attempt -lt 60;$attempt++) {
    $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,$condition)
    foreach($window in $windows) {
        $elements=$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
        foreach($element in $elements) {
            if($element.Current.Name -eq $Action) {
                $pattern=$null
                if($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){$pattern.Invoke();exit 0}
                if($element.TryGetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern,[ref]$pattern)){$pattern.DoDefaultAction();exit 0}
            }
        }
    }
    Start-Sleep -Milliseconds 50
}
throw 'Owned tray action was not found'
''',encoding='utf-8-sig')
        def action(name,completed):
            rect=tray_rect(gui.pid)
            if rect is None:raise RuntimeError('Tray icon disappeared')
            # Auto-hidden taskbars retain their icon rectangles while not yet visible.
            u.SetCursorPos((rect.left+rect.right)//2,rect.bottom-1);time.sleep(.8)
            rect=tray_rect(gui.pid)
            u.SetCursorPos((rect.left+rect.right)//2,(rect.top+rect.bottom)//2);time.sleep(.2)
            point=json.loads(subprocess.check_output(['powershell','-NoProfile','-File',str(point_probe),'-X',str((rect.left+rect.right)//2),'-Y',str((rect.top+rect.bottom)//2)],encoding='utf-8-sig',creationflags=0x08000000))
            overflow=any('隐藏' in element['name'] or 'Overflow' in element['id'] for element in point)
            # Shell_NotifyIconGetRect reports the overflow chevron for a hidden icon.
            overflow|=bool(point and point[0]['class']=='Shell_TrayWnd' and not any('Remind' in element['name'] for element in point))
            if overflow:
                previous=(rect.left,rect.top,rect.right,rect.bottom)
                u.SetCursorPos((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)
                u.mouse_event(2,0,0,0,0);time.sleep(.05);u.mouse_event(4,0,0,0,0)
                for _ in range(40):
                    time.sleep(.05);rect=tray_rect(gui.pid)
                    if rect and (rect.left,rect.top,rect.right,rect.bottom)!=previous:break
                else:raise RuntimeError('Overflow did not expose the owned icon; no other icon was clicked.')
                time.sleep(.6);rect=tray_rect(gui.pid)
            u.SetCursorPos((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)
            time.sleep(.2)
            u.mouse_event(8,0,0,0,0);time.sleep(.05);u.mouse_event(16,0,0,0,0)
            response=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(menu),'-ProcessId',str(gui.pid),'-Action',name],capture_output=True,timeout=10,creationflags=0x08000000)
            for _ in range(20):
                if completed():return
                time.sleep(.05)
            raise RuntimeError((response.returncode,response.stdout.decode('utf-8',errors='replace'),response.stderr.decode('utf-8',errors='replace')))
        action('恢复悬浮入口',lambda:launcher_visible(gui.pid))
        for _ in range(40):
            if launcher_visible(gui.pid):break
            time.sleep(.05)
        result['tray_restores_launcher']=launcher_visible(gui.pid)
        saved=json.loads((root/'settings.json').read_text(encoding='utf-8'))
        result['restore_setting_persisted']=saved['hide_launcher'] is False
        result['login_startup_stays_off']=saved['login_startup'] is False
        action('退出',lambda:gui.poll() is not None);gui.wait(timeout=5);result['tray_exit_stops_owned_app']=gui.returncode==0
        print(json.dumps(result));assert all(result.values())
finally:
    if gui and gui.poll() is None:gui.terminate();gui.wait(timeout=5)
    u.SetCursorPos(cursor.x,cursor.y);u.SetForegroundWindow(foreground)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
