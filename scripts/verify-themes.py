"""Check primary-action hover contrast in real dark/light WPF settings panels."""
import argparse
from collections import Counter
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from PIL import ImageGrab

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();app=args.app.resolve();args.out.mkdir(parents=True,exist_ok=True);(args.out/'info').mkdir(exist_ok=True)
user=ctypes.windll.user32;ctypes.windll.shcore.SetProcessDpiAwareness(2)
cursor=wintypes.POINT();user.GetCursorPos(ctypes.byref(cursor));results={};gui=None
def luminance(rgb):
    channels=[v/255 for v in rgb];linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in channels]
    return sum(a*b for a,b in zip(linear,[.2126,.7152,.0722]))
def ui(pid,action=None):
    command=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('ui-inspect.ps1')),'-ProcessId',str(pid)]
    if action:command+=['-Invoke',action]
    output=subprocess.check_output(command,encoding='utf-8-sig',timeout=10,creationflags=0x08000000).strip()
    result=json.loads(output) if output else []
    return result if isinstance(result,list) else [result]
try:
    for theme,foreground in [('dark',(16,55,41)),('light',(255,255,255))]:
        with tempfile.TemporaryDirectory(prefix='rad-theme-') as directory:
            data=Path(directory);settings=json.loads((Path(os.environ['LOCALAPPDATA'])/'RemindAtDone/settings.json').read_text(encoding='utf-8'))
            settings.update(theme=theme,left=-1800,top=800,selected_tab='active',do_not_disturb=True,hide_launcher=False)
            (data/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
            env=dict(os.environ,RAD_DATA_DIR=str(data));gui=subprocess.Popen([str(app/'RemindAtDone.exe'),'--panel'],env=env,creationflags=0x08000000)
            try:
                for _ in range(15):
                    if any(item['name']=='设置' for item in ui(gui.pid)):break
                    if gui.poll() is not None:
                        diagnostic=data/'diagnostic.log'
                        raise RuntimeError(diagnostic.read_text(encoding='utf-8') if diagnostic.exists() else f'App exited: {gui.returncode}')
                    time.sleep(.1)
                else:raise RuntimeError('Settings entry did not become visible; no theme sample was taken.')
                ui(gui.pid,'设置');tree=ui(gui.pid)
                button=next(e for e in tree if e['type']=='ControlType.Button' and e['name']=='保存设置')
                x,y,width,height=button['bounds'];user.SetCursorPos(round(x+width/2),round(y+height/2));time.sleep(.2)
                shot=ImageGrab.grab(bbox=(int(x),int(y),int(x+width),int(y+height)),all_screens=True).convert('RGB')
                shot.save(args.out/(theme+'-primary-hover.png'))
                background=Counter(shot.getdata()).most_common(1)[0][0]
                # The hover border composites both text and background at 96% opacity.
                surface=(17,25,37) if theme=='dark' else (247,249,252)
                text=tuple(round(a*.96+b*.04) for a,b in zip(foreground,surface))
                light,dark=sorted([luminance(background),luminance(text)],reverse=True);contrast=(light+.05)/(dark+.05)
                results[theme]={'dominant_hover_background':background,'text_contrast':contrast,'passed':contrast>=4.5}
                print(theme+': '+str(results[theme]),flush=True);assert contrast>=4.5
            finally:
                if gui.poll() is None:gui.terminate();gui.wait(timeout=5)
                gui=None
finally:
    if gui and gui.poll() is None:gui.terminate();gui.wait(timeout=5)
    user.SetCursorPos(cursor.x,cursor.y)
    (args.out/'info/themes.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
