"""Record both real transitions on the same HWND and verify anchor/focus restoration."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from capture_native import artwork

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--reduce-motion',action='store_true')
args=parser.parse_args();app=args.app.resolve();args.out.mkdir(parents=True,exist_ok=True);(args.out/'info').mkdir(exist_ok=True)
ctypes.windll.shcore.SetProcessDpiAwareness(2);user=ctypes.windll.user32;user.GetForegroundWindow.restype=wintypes.HWND
user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
gdi=ctypes.windll.gdi32;gdi.CreateRectRgn.restype=wintypes.HRGN
user.GetWindowRgn.argtypes=[wintypes.HWND,wintypes.HRGN]
gdi.GetRgnBox.argtypes=[wintypes.HRGN,ctypes.POINTER(wintypes.RECT)]
gdi.DeleteObject.argtypes=[wintypes.HGDIOBJ]
results={}
def windows(pid):
    found=[]
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def callback(hwnd,_):
        owner=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and user.IsWindowVisible(hwnd):
            title=ctypes.create_unicode_buffer(256);user.GetWindowTextW(hwnd,title,256)
            rect=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect))
            found.append((hwnd,title.value,(rect.left,rect.top,rect.right,rect.bottom)))
        return True
    user.EnumWindows(callback,0);return found
def check(name,value):
    results[name]=bool(value);print(('PASS ' if value else 'FAIL ')+name,flush=True);assert value,name
with tempfile.TemporaryDirectory(prefix='rad-unified-') as directory:
    root=Path(directory);settings=json.loads((Path(os.environ['LOCALAPPDATA'])/'RemindAtDone/settings.json').read_text(encoding='utf-8'))
    settings.update(left=-68,top=1300,theme='dark',selected_tab='completed' if args.reduce_motion else 'active',do_not_disturb=True,hide_launcher=False,reduce_motion=args.reduce_motion)
    (root/'settings.json').write_text(json.dumps(settings),encoding='utf-8');env=dict(os.environ,RAD_DATA_DIR=str(root))
    gui=subprocess.Popen([str(app/'RemindAtDone.exe')],env=env,creationflags=0x08000000)
    ui=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('ui-inspect.ps1')),'-ProcessId',str(gui.pid)]
    def invoke(action=None,open_panel=False):
        command=ui+(['-OpenPanel'] if open_panel else ['-Invoke',action] if action else [])
        return subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
    def names():
        process=invoke();stdout,stderr=process.communicate(timeout=10)
        if process.returncode:raise RuntimeError(stderr)
        return json.loads(stdout.decode('utf-8-sig')) if stdout.strip() else []
    try:
        for _ in range(60):
            shown=windows(gui.pid)
            if shown:break
            time.sleep(.05)
        time.sleep(.3);entry=windows(gui.pid)[0];hwnd=entry[0];anchor=entry[2];foreground=user.GetForegroundWindow()
        envelope=(-550,560,8,1370)
        def record(name,start_action):
            frames=[artwork(hwnd,envelope)];shapes=set();changes=[];stop=threading.Event()
            def sample_region():
                region=gdi.CreateRectRgn(0,0,0,0)
                try:
                    while not stop.is_set():
                        bounds=wintypes.RECT()
                        if user.GetWindowRgn(hwnd,region) and gdi.GetRgnBox(region,ctypes.byref(bounds)):
                            shape=(bounds.left,bounds.top,bounds.right,bounds.bottom);shapes.add(shape)
                            if not changes or changes[-1][1]!=shape:changes.append((time.monotonic(),shape))
                        time.sleep(.005)
                finally:gdi.DeleteObject(region)
            sampler=threading.Thread(target=sample_region,daemon=True);sampler.start()
            process=start_action();start=time.monotonic()
            while time.monotonic()-start<1.6:frames.append(artwork(hwnd,envelope));time.sleep(.025)
            stop.set();sampler.join(timeout=2)
            _,stderr=process.communicate(timeout=10)
            if process.returncode:raise RuntimeError(stderr)
            frames[0].save(args.out/(name+'.gif'),save_all=True,append_images=frames[1:],duration=45,loop=0)
            results[name+'_distinct_frames']=len({hashlib.sha256(frame.tobytes()).digest() for frame in frames})
            results[name+'_distinct_clip_bounds']=len(shapes)
            if args.reduce_motion:
                # Ignore the time spent launching the UI driver before its action.
                span=changes[-1][0]-changes[1][0] if len(changes)>2 else 0
                results[name+'_transition_span_seconds']=span
                check(name+'_static_transition',1<=len(shapes)<=3 and span<.12)
            else:check(name+'_animated',len(shapes)>=3)
        record('panel-open',lambda:invoke(open_panel=True))
        shown=windows(gui.pid);check('panel_uses_same_single_hwnd',len(shown)==1 and shown[0][0]==hwnd and shown[0][1]=='Remind · 任务')
        artwork(hwnd).save(args.out/'panel.png')
        process=invoke('设置');process.communicate(timeout=10)
        record('completion-open',lambda:invoke('预览展开效果'))
        check('completion_uses_same_single_hwnd',len(windows(gui.pid))==1 and windows(gui.pid)[0][0]==hwnd)
        artwork(hwnd).save(args.out/'completion.png')
        time.sleep(8.5)
        tree=names();check('preview_returns_to_settings',any(item['name']=='保存设置' for item in tree))
        record('panel-close',lambda:invoke('关闭面板'))
        shown=windows(gui.pid);check('collapsed_anchor_restored',len(shown)==1 and shown[0][2]==anchor and shown[0][1]=='Remind at done')
        check('focus_restored_after_panel_close',user.GetForegroundWindow()==foreground)
    finally:
        if gui.poll() is None:gui.terminate();gui.wait(timeout=5)
        (args.out/'info/unified-panel.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
