"""Real mouse input on an isolated launcher, with an owned outside-click target.
Restores the cursor and foreground window; never clicks other applications.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time

from PIL import ImageGrab

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();args.app=args.app.resolve();args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=True);(args.out/'info').mkdir(exist_ok=True)
ctypes.windll.shcore.SetProcessDpiAwareness(2)
user=ctypes.windll.user32;kernel=ctypes.windll.kernel32
user.GetForegroundWindow.restype=wintypes.HWND
user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
user.SetForegroundWindow.argtypes=[wintypes.HWND]
user.WindowFromPoint.argtypes=[wintypes.POINT];user.WindowFromPoint.restype=wintypes.HWND
user.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
user.ShowWindowAsync.argtypes=[wintypes.HWND,ctypes.c_int]
user.IsWindowVisible.argtypes=[wintypes.HWND]
user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
kernel.GetModuleHandleW.restype=wintypes.HMODULE
user.DefWindowProcW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];user.DefWindowProcW.restype=ctypes.c_ssize_t
user.CreateWindowExW.restype=wintypes.HWND
user.CreateWindowExW.argtypes=[wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.HWND,wintypes.HMENU,wintypes.HINSTANCE,ctypes.c_void_p]
old_cursor=wintypes.POINT();user.GetCursorPos(ctypes.byref(old_cursor));old_foreground=user.GetForegroundWindow()
clicked=threading.Event();ready=queue.Queue();checks={}
def target_window():
    proc_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM)
    @proc_type
    def handler(hwnd,message,wp,lp):
        if message==0x201:clicked.set()
        if message==2:user.PostQuitMessage(0)
        return user.DefWindowProcW(hwnd,message,wp,lp)
    class WNDCLASS(ctypes.Structure):
        _fields_=[('style',wintypes.UINT),('proc',proc_type),('cls_extra',ctypes.c_int),('wnd_extra',ctypes.c_int),('instance',wintypes.HINSTANCE),('icon',wintypes.HICON),('cursor',wintypes.HANDLE),('background',wintypes.HBRUSH),('menu',wintypes.LPCWSTR),('name',wintypes.LPCWSTR)]
    module=kernel.GetModuleHandleW(None);definition=WNDCLASS();definition.proc=handler;definition.instance=module;definition.background=6;definition.name='RadOutsideClickTest'+str(os.getpid())
    user.RegisterClassW(ctypes.byref(definition))
    hwnd=user.CreateWindowExW(0x08000008,definition.name,'Remind interaction test',0x90800000,-1300,720,190,120,None,None,module,None)
    ready.put(hwnd);message=wintypes.MSG()
    while user.GetMessageW(ctypes.byref(message),None,0,0)>0:user.TranslateMessage(ctypes.byref(message));user.DispatchMessageW(ctypes.byref(message))
    user.UnregisterClassW(definition.name,module)

def windows(pid):
    found={}
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def each(hwnd,_):
        owner=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and user.IsWindowVisible(hwnd):
            text=ctypes.create_unicode_buffer(256);user.GetWindowTextW(hwnd,text,256)
            rect=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect));found[text.value]=(hwnd,(rect.left,rect.top,rect.right,rect.bottom))
        return True
    user.EnumWindows(each,0);return found
def wait_for(predicate):
    for _ in range(60):
        value=predicate()
        if value:return value
        time.sleep(.05)
    raise AssertionError('UI did not reach expected state')
def check(name,value):
    checks[name]=bool(value);print(('PASS ' if value else 'FAIL ')+name,flush=True);assert value,name
def click(x,y):
    user.SetCursorPos(int(x),int(y));user.mouse_event(2,0,0,0,0);time.sleep(.06);user.mouse_event(4,0,0,0,0);time.sleep(.2)
def center(bounds):return ((bounds[0]+bounds[2])//2,(bounds[1]+bounds[3])//2)
def move_mouse(x,y):
    left,top=user.GetSystemMetrics(76),user.GetSystemMetrics(77)
    width,height=user.GetSystemMetrics(78),user.GetSystemMetrics(79)
    user.mouse_event(0xC001,int((x-left)*65536/width),int((y-top)*65536/height),0,0)

threading.Thread(target=target_window,daemon=True).start();target=ready.get(timeout=5)
assert target,'Outside-click target creation failed'
gui=None
try:
    with tempfile.TemporaryDirectory(prefix='rad-usability-') as directory:
        data=Path(directory);settings=json.loads((Path(os.environ['LOCALAPPDATA'])/'RemindAtDone/settings.json').read_text(encoding='utf-8'))
        settings.update(left=-1600,top=700,hide_launcher=False,do_not_disturb=True,theme='dark',selected_tab='active')
        (data/'settings.json').write_text(json.dumps(settings),encoding='utf-8');env=dict(os.environ,RAD_DATA_DIR=str(data))
        def launch():
            process=subprocess.Popen([str(args.app/'RemindAtDone.exe')],env=env,creationflags=0x08000000)
            wait_for(lambda:windows(process.pid).get('Remind at done'));time.sleep(.4);return process
        gui=launch();entry=windows(gui.pid)['Remind at done'][1]
        foreground=user.GetForegroundWindow()
        user.ShowWindowAsync(target,0);time.sleep(.1)
        user.SetWindowPos(target,wintypes.HWND(-1),entry[0]-10,entry[1]-10,76,76,0x4050)
        def target_shown():
            rectangle=wintypes.RECT();user.GetWindowRect(target,ctypes.byref(rectangle))
            return user.IsWindowVisible(target) and rectangle.left==entry[0]-10 and rectangle.top==entry[1]-10
        wait_for(target_shown)
        wait_for(lambda:user.WindowFromPoint(wintypes.POINT(*center(entry)))==windows(gui.pid)['Remind at done'][0])
        check('new_topmost_window_cannot_cover_launcher',True)
        check('topmost_reassertion_does_not_take_focus',user.GetForegroundWindow()==foreground)
        user.SetWindowPos(target,wintypes.HWND(-1),-1300,720,190,120,0x4010);time.sleep(.1)
        check('launcher_keeps_original_size',entry[2]-entry[0]==56 and entry[3]-entry[1]==56)
        picture=ImageGrab.grab(bbox=entry,all_screens=True);picture.save(args.out/'launcher.png')
        pixels=picture.convert('RGB');mint=[]
        for y in range(pixels.height):
            for x in range(pixels.width):
                r,g,b=pixels.getpixel((x,y))
                if g>r+35 and g>b+15 and r>90:mint.append((x,y))
        check('glyph_visually_centered',bool(mint) and abs((min(x for x,y in mint)+max(x for x,y in mint))/2-(pixels.width-1)/2)<=1.5 and abs((min(y for x,y in mint)+max(y for x,y in mint))/2-(pixels.height-1)/2)<=1.5)
        x,y=center(entry);user.SetCursorPos(x,y);user.mouse_event(2,0,0,0,0);time.sleep(.1)
        checks['button_down_state']=user.GetAsyncKeyState(1)
        for step in range(1,13):move_mouse(x+step*20,y+step*10);time.sleep(.03)
        moved=windows(gui.pid)['Remind at done'][1]
        checks['drag_bounds']={'before':entry,'during':moved}
        if(data/'diagnostic.log').exists():checks['diagnostic']=(data/'diagnostic.log').read_text(encoding='utf-8')
        check('drag_tracks_pointer_outside_original_bounds',abs(moved[0]-entry[0]-240)<=2 and abs(moved[1]-entry[1]-120)<=2)
        user.mouse_event(4,0,0,0,0);time.sleep(.4)
        entry=windows(gui.pid)['Remind at done'][1]
        check('drag_does_not_open_panel','Remind · 任务' not in windows(gui.pid))
        stored=json.loads((data/'settings.json').read_text(encoding='utf-8'))
        check('drag_position_saved',stored['left']==entry[0] and stored['top']==entry[1])
        click(*center(entry))
        wait_for(lambda:windows(gui.pid).get('Remind · 任务'))
        tree=json.loads(subprocess.check_output(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('ui-inspect.ps1')),'-ProcessId',str(gui.pid)],encoding='utf-8-sig',creationflags=0x08000000))
        title=next(item for item in tree if item['type']=='ControlType.Text' and item['name']=='任务')['bounds']
        click(title[0]+title[2]/2,title[1]+title[3]/2);check('inside_click_keeps_panel_open','Remind · 任务' in windows(gui.pid))
        check('outside_target_hit_area',user.WindowFromPoint(wintypes.POINT(-1220,775))==target)
        click(-1220,775);wait_for(lambda:'Remind · 任务' not in windows(gui.pid))
        check('outside_click_closes_panel',True);check('outside_click_reaches_target',clicked.wait(2))
        wait_for(lambda:windows(gui.pid).get('Remind at done') and windows(gui.pid)['Remind at done'][1]==entry and user.WindowFromPoint(wintypes.POINT(*center(entry)))==windows(gui.pid)['Remind at done'][0])
        click(*center(entry));wait_for(lambda:windows(gui.pid).get('Remind · 任务'))
        click(*center(entry));wait_for(lambda:'Remind · 任务' not in windows(gui.pid))
        check('launcher_click_dismisses_without_reopening',True)
        gui.terminate();gui.wait(timeout=5);gui=launch()
        check('drag_position_survives_restart',windows(gui.pid)['Remind at done'][1]==entry)
        gui.terminate();gui.wait(timeout=5);gui=None
finally:
    user.mouse_event(4,0,0,0,0)
    if gui and gui.poll() is None:gui.terminate();gui.wait(timeout=5)
    user.PostMessageW(target,0x10,0,0);user.SetCursorPos(old_cursor.x,old_cursor.y);user.SetForegroundWindow(old_foreground)
    (args.out/'info/usability-results.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
