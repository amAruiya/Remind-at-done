"""Isolated visual fixture and short animation capture. Never writes production history."""
import argparse
import ctypes
from ctypes import wintypes
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from PIL import ImageGrab
from capture_native import artwork

parser=argparse.ArgumentParser()
parser.add_argument('--app',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--codex',required=True)
parser.add_argument('--keep',action='store_true')
parser.add_argument('--edge',choices=['left','right'],default='right')
parser.add_argument('--top',action='store_true')
parser.add_argument('--x',type=int)
parser.add_argument('--y',type=int)
parser.add_argument('--label',default='')
args=parser.parse_args();args.app=args.app.resolve();args.out=args.out.resolve()
suffix='' if args.edge=='right' and not args.top else '-'+args.edge+('-top' if args.top else '')
if args.label:suffix='-'+args.label
args.out.mkdir(parents=True,exist_ok=True);(args.out/'info').mkdir(exist_ok=True)
data=Path(tempfile.mkdtemp(prefix='rad-visual-'));env=dict(os.environ,RAD_DATA_DIR=str(data))
rad=args.app/'rad.exe';exe=args.app/'RemindAtDone.exe'
user=ctypes.windll.user32;ctypes.windll.shcore.SetProcessDpiAwareness(2)
user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
user.GetForegroundWindow.restype=wintypes.HWND
user.WindowFromPoint.argtypes=[wintypes.POINT];user.WindowFromPoint.restype=wintypes.HWND

def run(*command):
    p=subprocess.run([str(rad),*command],env=env,capture_output=True,encoding='utf-8-sig',timeout=10,creationflags=0x08000000)
    if p.returncode:raise RuntimeError(p.stdout)
    return json.loads(p.stdout)

def windows(pid,include_hidden=False):
    result=[]
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def each(hwnd,_):
        found=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(found))
        if found.value==pid and (include_hidden or user.IsWindowVisible(hwnd)):
            title=ctypes.create_unicode_buffer(256);user.GetWindowTextW(hwnd,title,256)
            rect=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect))
            result.append((hwnd,title.value,(rect.left,rect.top,rect.right,rect.bottom)))
        return True
    user.EnumWindows(each,0);return result

run('register','--home',env.get('CODEX_HOME',str(Path.home()/'.codex')),'--codex',args.codex)
settings=json.loads((data/'settings.json').read_text(encoding='utf-8'));settings.update(theme='dark',left=12 if args.edge=='left' else user.GetSystemMetrics(0)-68,top=12 if args.top else user.GetSystemMetrics(1)-180,reduce_motion=False,selected_tab='active')
if args.x is not None:settings['left']=args.x
if args.y is not None:settings['top']=args.y
(data/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
app=subprocess.Popen([str(exe),'--panel'],env=env,creationflags=0x08000000)
try:
    launcher=None
    for attempt in range(30):
        launcher=next((w for w in windows(app.pid,True) if w[1]=='Remind at done'),None)
        if launcher: break
        time.sleep(.1)
    if not launcher:
        raise RuntimeError({'exit':app.poll(),'windows':windows(app.pid),'data':str(data), 'diagnostic':(data/'diagnostic.log').read_text(encoding='utf-8') if (data/'diagnostic.log').exists() else None})
    panel=None
    for attempt in range(30):
        panel=next((w for w in windows(app.pid) if '任务' in w[1]),None)
        if panel:break
        time.sleep(.1)
    if not panel:raise RuntimeError('Preview panel did not open')
    time.sleep(1)
    launcher=next(w for w in windows(app.pid,True) if w[1]=='Remind at done');anchor=launcher[2]
    user.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    user.SetWindowPos(panel[0],None,80,160,0,0,0x15)
    foreground=user.GetForegroundWindow()
    payload={'task_key':'visual-'+str(time.time_ns()),'status':'completed','title':'任务提醒，已融入悬浮入口',
             'summary':'入口保持原位，结果从同一轮廓中展开。完成记录现在只保留最近 3 天、最多 20 项。',
             'verification':'界面预览 · 动画与点击区域检查中','completed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
             'elapsed_seconds':301,'timing_source':'context'}
    report=data/'report.json';report.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    run('notify','--file',str(report))
    ui=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('ui-inspect.ps1')),'-ProcessId',str(app.pid)]
    for filename,action in [('active-panel.png','刷新'),('completed-panel.png','已完成')]:
        subprocess.run(ui+['-Invoke',action],stdout=subprocess.DEVNULL,check=True,timeout=10,creationflags=0x08000000)
        time.sleep(.3)
        visible_panel=next((w for w in windows(app.pid) if '任务' in w[1]),None)
        if visible_panel and not suffix:artwork(visible_panel[0]).save(args.out/filename)
    subprocess.run(ui+['-Invoke','设置'],stdout=subprocess.DEVNULL,check=True,timeout=10,creationflags=0x08000000)
    foreground=user.GetForegroundWindow()
    sender=subprocess.Popen(ui+['-Invoke','预览展开效果'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
    # Capture only the assistant's envelope, never the rest of the user's screen.
    region=(anchor[0]-380 if args.edge=='right' else anchor[0]-8,anchor[1]-205 if not args.top else anchor[1]-8,
            anchor[2]+12 if args.edge=='right' else anchor[0]+440,anchor[3]+12 if not args.top else anchor[1]+270)
    frames=[];begin=time.monotonic()
    while time.monotonic()-begin<1.8:
        frames.append(artwork(launcher[0],region));time.sleep(.025)
    stdout,stderr=sender.communicate(timeout=10)
    if sender.returncode:raise RuntimeError((stdout,stderr))
    current=windows(app.pid)
    expanded=next((w for w in current if w[1]=='Remind at done'),None)
    if not expanded: raise RuntimeError({'exit':app.poll(),'windows':current,'data':str(data),'diagnostic':(data/'diagnostic.log').read_text(encoding='utf-8') if (data/'diagnostic.log').exists() else None})
    evidence={'same_hwnd':expanded[0]==launcher[0],'no_separate_notification_window':not any(w[1]=='任务完成' for w in current),'resting_bounds':anchor,'expanded_bounds':expanded[2],
              'foreground_unchanged':foreground==user.GetForegroundWindow(),'pid':app.pid,'data':str(data)}
    scale=(anchor[2]-anchor[0])/56
    outside=wintypes.POINT(int(expanded[2][2]-8*scale if args.edge=='right' else expanded[2][0]+8*scale),int(expanded[2][1]+12*scale if not args.top else expanded[2][3]-12*scale))
    evidence['transparent_corner_passes_through']=user.WindowFromPoint(outside)!=launcher[0]
    evidence['orb_remains_clickable']=user.WindowFromPoint(wintypes.POINT((anchor[0]+anchor[2])//2,(anchor[1]+anchor[3])//2))==launcher[0]
    artwork(expanded[0]).save(args.out/('expanded-reminder'+suffix+'.png'))
    frames[0].save(args.out/('unfold'+suffix+'.gif'),save_all=True,append_images=frames[1:],duration=45,loop=0)
    time.sleep(8)
    collapsed=next(w for w in windows(app.pid,True) if w[1]=='Remind at done')
    evidence['anchor_restored']=collapsed[2]==anchor
    (args.out/('info/visual'+suffix+'.json')).write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps(evidence),flush=True)
finally:
    if not args.keep and app.poll() is None:app.terminate();app.wait(timeout=5)
