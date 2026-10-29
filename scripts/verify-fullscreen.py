"""Exercise suppression/recovery with an owned full-screen window on the primary monitor."""
import argparse
import ctypes
from ctypes import wintypes as w
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--test-exe',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--start-fullscreen',action='store_true')
args=parser.parse_args();app=args.app.resolve();checks={};gui=cover=None
u=ctypes.windll.user32;ctypes.windll.shcore.SetProcessDpiAwareness(2)
u.GetForegroundWindow.restype=w.HWND;u.SetForegroundWindow.argtypes=[w.HWND]
u.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
u.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.WindowFromPoint.argtypes=[w.POINT];u.WindowFromPoint.restype=w.HWND
u.GetAncestor.argtypes=[w.HWND,w.UINT];u.GetAncestor.restype=w.HWND
foreground=u.GetForegroundWindow();cursor=w.POINT();u.GetCursorPos(ctypes.byref(cursor))
def windows(pid):
    found=[]
    @ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    def each(hwnd,_):
        owner=w.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and u.IsWindowVisible(hwnd):
            title=ctypes.create_unicode_buffer(128);u.GetWindowTextW(hwnd,title,128)
            bounds=w.RECT();u.GetWindowRect(hwnd,ctypes.byref(bounds));found.append((hwnd,title.value,bounds))
        return True
    u.EnumWindows(each,0);return found
def wait_for(predicate):
    for _ in range(100):
        value=predicate()
        if value:return value
        time.sleep(.05)
    raise RuntimeError('Expected desktop state did not arrive')
def check(name,value):
    checks[name]=bool(value);print(('PASS ' if value else 'FAIL ')+name,flush=True);assert value,name
try:
    with tempfile.TemporaryDirectory(prefix='rad-fullscreen-') as directory:
        root=Path(directory);settings=json.loads((Path(os.environ['LOCALAPPDATA'])/'RemindAtDone/settings.json').read_text(encoding='utf-8'))
        settings.update(left=2400,top=1200,hide_launcher=False,do_not_disturb=False,card_seconds=10,reduce_motion=False)
        (root/'settings.json').write_text(json.dumps(settings),encoding='utf-8');env=dict(os.environ,RAD_DATA_DIR=str(root),DOTNET_ROOT=str(Path(os.environ['LOCALAPPDATA'])/'RemindAtDone.Build/dotnet'))
        gui=subprocess.Popen([str(app/'RemindAtDone.exe')],env=env,creationflags=0x08000000)
        def expanded():return any(rect.right-rect.left>100 for _,_,rect in windows(gui.pid))
        def send(number):
            instance=settings['instances'][0]['id'];thread='00000000-0000-4000-8000-000000000001';key=f'fullscreen:{number}'
            report=dict(instance_id=instance,thread_id=thread,task_key=key,event_id=hashlib.sha256(json.dumps([instance,thread,key],separators=(',',':')).encode()).hexdigest(),
                status='completed',title='全屏恢复验收',summary='受控提醒数据。',elapsed_seconds=301,timing_source='context',completed_at=dt.datetime.now(dt.timezone.utc).isoformat(),cwd=str(root))
            batch=root/'batch.json';batch.write_text(json.dumps([report]),encoding='utf-8')
            subprocess.run([str(args.test_exe.resolve()),'--wire-batch',str(batch)],env=env,stdout=subprocess.DEVNULL,check=True,timeout=10,creationflags=0x08000000)
        wait_for(lambda:windows(gui.pid));time.sleep(.2);begin=time.monotonic();send(0);wait_for(expanded)
        check('initial_notification_visible',expanded())
        script=root/'fullscreen.ps1';script.write_text('''Add-Type -AssemblyName System.Windows.Forms
$form=New-Object Windows.Forms.Form
$form.Text='Remind fullscreen acceptance';$form.FormBorderStyle='None';$form.StartPosition='Manual'
$form.Bounds=New-Object Drawing.Rectangle(0,0,640,480);$form.TopMost=$true
$form.BackColor=[Drawing.Color]::FromArgb(48,58,72)
$request=Join-Path $PSScriptRoot 'fullscreen.request'
$timer=New-Object Windows.Forms.Timer;$timer.Interval=100
$timer.Add_Tick({if(Test-Path -LiteralPath $request){$timer.Stop();$form.Bounds=[Windows.Forms.Screen]::PrimaryScreen.Bounds}})
$timer.Start()
$form.Add_Shown({$form.Activate()})
[Windows.Forms.Application]::Run($form)
''',encoding='utf-8-sig')
        if args.start_fullscreen:
            script.write_text(script.read_text(encoding='utf-8-sig').replace('New-Object Drawing.Rectangle(0,0,640,480)','[Windows.Forms.Screen]::PrimaryScreen.Bounds'),encoding='utf-8-sig')
        cover=subprocess.Popen(['powershell','-NoProfile','-File',str(script)],creationflags=0x08000000)
        full=wait_for(lambda:next((item for item in windows(cover.pid) if item[1]=='Remind fullscreen acceptance'),None));hwnd,_,bounds=full
        point=w.POINT(200,200)
        wait_for(lambda:u.GetAncestor(u.WindowFromPoint(point),2)==hwnd)
        u.SetCursorPos(point.x,point.y);u.mouse_event(2,0,0,0,0);time.sleep(.05);u.mouse_event(4,0,0,0,0)
        wait_for(lambda:u.GetForegroundWindow()==hwnd)
        if not args.start_fullscreen:
            check('normal_foreground_does_not_retract_summary',expanded())
            (root/'fullscreen.request').write_text('go',encoding='ascii')
        def is_fullscreen():
            bounds=w.RECT();u.GetWindowRect(hwnd,ctypes.byref(bounds))
            return (bounds.left,bounds.top,bounds.right,bounds.bottom)==(0,0,u.GetSystemMetrics(0),u.GetSystemMetrics(1))
        wait_for(is_fullscreen)
        check('fixture_covers_monitor_bounds',is_fullscreen())
        check('fullscreen_did_not_change_foreground',u.GetForegroundWindow()==hwnd)
        wait_for(lambda:not expanded())
        check('entering_fullscreen_retracts_summary',not expanded())
        entry=windows(gui.pid)[0];rect=entry[2];orb=w.POINT((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)
        check('launcher_stays_visible_above_fullscreen',u.GetAncestor(u.WindowFromPoint(orb),2)==entry[0])
        send(1);time.sleep(.3)
        check('fullscreen_suppresses_new_summary',not expanded())
        check('fullscreen_keeps_input_focus',u.GetForegroundWindow()==hwnd)
        rows=json.loads((root/'history.json').read_text(encoding='utf-8'))
        check('both_receipts_saved_and_unread',len(rows)==2 and all(not row['is_read'] for row in rows))
        cover.terminate();cover.wait(timeout=5);cover=None;u.SetForegroundWindow(foreground)
        replayed=False
        while time.monotonic()-begin<31:
            replayed|=expanded();time.sleep(.1)
        check('fullscreen_recovery_does_not_replay',not replayed)
        send(2);wait_for(expanded);check('fresh_event_after_recovery_displays',expanded())
finally:
    for process in (cover,gui):
        if process and process.poll() is None:process.terminate();process.wait(timeout=5)
    u.SetForegroundWindow(foreground);u.SetCursorPos(cursor.x,cursor.y)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(checks,indent=2),encoding='utf-8')
