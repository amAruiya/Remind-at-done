"""Capture raw desktop pixels (not the application's clip mask) at 60 fps over a neutral test surface."""
import argparse
import ctypes
from ctypes import wintypes as w
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import struct
import tempfile
import threading
import time
import cv2
import numpy as np

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--label',required=True);parser.add_argument('--cycles',type=int,default=1);parser.add_argument('--notification',action='store_true')
args=parser.parse_args();app=args.app.resolve();args.out.mkdir(parents=True,exist_ok=True);(args.out/'info').mkdir(exist_ok=True)
u=ctypes.windll.user32;g=ctypes.windll.gdi32;k=ctypes.windll.kernel32;ctypes.windll.shcore.SetProcessDpiAwareness(2)
u.GetDC.restype=w.HDC;u.ReleaseDC.argtypes=[w.HWND,w.HDC]
g.CreateCompatibleDC.argtypes=[w.HDC];g.CreateCompatibleDC.restype=w.HDC
g.CreateDIBSection.argtypes=[w.HDC,ctypes.c_void_p,w.UINT,ctypes.POINTER(ctypes.c_void_p),w.HANDLE,w.DWORD];g.CreateDIBSection.restype=w.HBITMAP
g.SelectObject.argtypes=[w.HDC,w.HGDIOBJ];g.SelectObject.restype=w.HGDIOBJ
g.BitBlt.argtypes=[w.HDC,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HDC,ctypes.c_int,ctypes.c_int,w.DWORD]
g.DeleteObject.argtypes=[w.HGDIOBJ];g.DeleteDC.argtypes=[w.HDC]
g.CreateSolidBrush.argtypes=[w.DWORD];g.CreateSolidBrush.restype=w.HBRUSH
k.GetModuleHandleW.restype=w.HMODULE
u.CreateWindowExW.restype=w.HWND;u.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,ctypes.c_void_p]
u.DefWindowProcW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.DefWindowProcW.restype=ctypes.c_ssize_t
u.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
u.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
x,y,width,height=-550,600,550,800;ready=queue.Queue()
def backdrop():
    callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
    @callback_type
    def callback(hwnd,message,wp,lp):
        if message==2:u.PostQuitMessage(0)
        return u.DefWindowProcW(hwnd,message,wp,lp)
    class WNDCLASS(ctypes.Structure):
        _fields_=[('style',w.UINT),('proc',callback_type),('cls_extra',ctypes.c_int),('wnd_extra',ctypes.c_int),('instance',w.HINSTANCE),('icon',w.HICON),('cursor',w.HANDLE),('background',w.HBRUSH),('menu',w.LPCWSTR),('name',w.LPCWSTR)]
    brush=g.CreateSolidBrush(0xB8B8B8);definition=WNDCLASS();definition.proc=callback;definition.instance=k.GetModuleHandleW(None);definition.background=brush;definition.name='RadFlickerBackdrop'+str(os.getpid())
    u.RegisterClassW(ctypes.byref(definition));hwnd=u.CreateWindowExW(0x08000088,definition.name,'Remind capture fixture',0x90000000,x,y,width,height,None,None,definition.instance,None)
    ready.put(hwnd);message=w.MSG()
    while u.GetMessageW(ctypes.byref(message),None,0,0)>0:u.TranslateMessage(ctypes.byref(message));u.DispatchMessageW(ctypes.byref(message))
    g.DeleteObject(brush)
threading.Thread(target=backdrop,daemon=True).start();background=ready.get(timeout=5)
class BitmapInfo(ctypes.Structure):
    _fields_=[('size',w.DWORD),('width',w.LONG),('height',w.LONG),('planes',w.WORD),('bits',w.WORD),('compression',w.DWORD),('image_size',w.DWORD),('xppm',w.LONG),('yppm',w.LONG),('used',w.DWORD),('important',w.DWORD)]
screen=u.GetDC(None);memory=g.CreateCompatibleDC(screen);info=BitmapInfo();info.size=40;info.width=width;info.height=-height;info.planes=1;info.bits=32
pixels=ctypes.c_void_p();bitmap=g.CreateDIBSection(memory,ctypes.byref(info),0,ctypes.byref(pixels),None,0);previous=g.SelectObject(memory,bitmap)
array=np.ctypeslib.as_array((ctypes.c_ubyte*(width*height*4)).from_address(pixels.value)).reshape(height,width,4)
frames=[];gui=None
try:
    with tempfile.TemporaryDirectory(prefix='rad-flicker-') as directory:
        root=Path(directory);data=root/'data';data.mkdir();shutil.copyfile(Path(__file__).with_name('fixtures')/'app-server',root/'app-server')
        (root/'state.json').write_text(json.dumps({'loaded_count':1,'delay_ms':120}),encoding='utf-8')
        settings={'instances':[{'id':'00000000-0000-4000-8000-000000000001','codex_home':str(root),'executable':shutil.which('node')}],
                  'left':-68,'top':1300,'theme':'dark','selected_tab':'active','do_not_disturb':not args.notification}
        (data/'settings.json').write_text(json.dumps(settings),encoding='utf-8');env=dict(os.environ,CODEX_HOME=str(root),RAD_DATA_DIR=str(data))
        gui=subprocess.Popen([str(app/'RemindAtDone.exe')],cwd=root,env=env,creationflags=0x08000000)
        def entry_ready():
            found=[]
            @ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
            def each(hwnd,_):
                pid=w.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                if pid.value==gui.pid and u.IsWindowVisible(hwnd):
                    rect=w.RECT();u.GetWindowRect(hwnd,ctypes.byref(rect))
                    if rect.left==-68 and rect.top==1300 and rect.right-rect.left==56:found.append(hwnd)
                return True
            u.EnumWindows(each,0);return bool(found)
        for _ in range(100):
            if entry_ready():break
            time.sleep(.05)
        if not entry_ready():raise RuntimeError('Launcher was not ready')
        time.sleep(.2)
        command=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('ui-inspect.ps1')),'-ProcessId',str(gui.pid),'-OpenPanel']
        if args.notification:
            sid=next(csv.reader(io.StringIO(subprocess.check_output(['whoami','/user','/fo','csv','/nh'],encoding='utf-8'))))[1]
            session=w.DWORD();k.ProcessIdToSessionId(os.getpid(),ctypes.byref(session))
            pipe=r'\\.\pipe\RemindAtDone-'+hashlib.sha256(f'{sid}|{session.value}|{str(data).upper()}'.encode()).hexdigest()[:24]
            samples=[]
        for cycle in range(args.cycles):
            label=args.label if cycle==0 else f'{args.label}-{cycle+1}';frames=[]
            ack={}
            def send_notification():
                instance=settings['instances'][0]['id'];thread='00000000-0000-4000-8000-000000000002';key=f'visible-latency:{cycle}'
                report=dict(instance_id=instance,thread_id=thread,task_key=key,
                    event_id=hashlib.sha256(json.dumps([instance,thread,key],separators=(',',':')).encode()).hexdigest(),
                    status='completed',title='完成提醒显示延迟',summary='受控动画时延检查。',elapsed_seconds=301,timing_source='context',
                    completed_at=dt.datetime.now(dt.timezone.utc).isoformat(),cwd=str(root))
                try:
                    with open(pipe,'r+b',buffering=0) as channel:
                        payload=json.dumps(report).encode();channel.write(struct.pack('<i',len(payload))+payload)
                        size=struct.unpack('<i',channel.read(4))[0];reply=json.loads(channel.read(size))
                        ack.update(seconds=time.perf_counter(),reply=reply)
                except Exception as error:ack['error']=str(error)
            if args.notification:
                action=threading.Thread(target=send_notification,daemon=True);action.start()
            else:action=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=0x08000000)
            writer=cv2.VideoWriter(str(args.out/(label+'.mp4')),cv2.VideoWriter_fourcc(*'mp4v'),60,(width,height))
            begin=time.perf_counter();deadline=begin
            while time.perf_counter()-begin<2.2:
                g.BitBlt(memory,0,0,width,height,screen,x,y,0x40CC0020)
                image=np.ascontiguousarray(array[:,:,:3]);writer.write(image)
                b,green,r=[image[:,:,channel].astype(np.int16) for channel in (0,1,2)]
                mask=(r<80)&(green<100)&(b<140)&(b-r>8)&(green-r>3)
                frames.append({'seconds':time.perf_counter()-begin,'surface_pixels':int(mask.sum())})
                deadline+=1/60;time.sleep(max(0,deadline-time.perf_counter()))
            writer.release()
            if args.notification:
                action.join(timeout=5)
                if action.is_alive() or 'error' in ack or ack.get('reply',{}).get('result')!='accepted':raise RuntimeError(('Notification ACK missing',ack))
            else:action.communicate(timeout=10)
            areas=[frame['surface_pixels'] for frame in frames]
            first=next((i for i,area in enumerate(areas) if area>3000),None)
            drops=[] if first is None else [i for i in range(first+1,min(len(areas),first+45)) if areas[i-1]>3000 and areas[i]<areas[i-1]*.8]
            output={'frames':frames,'observed_fps':len(frames)/(time.perf_counter()-begin),'opened':max(areas)>(20000 if args.notification else 100000),'large_opening_drops':drops}
            if args.notification and first is not None:
                full=next(i for i,area in enumerate(areas) if area>=max(areas)*.95)
                output['ack_to_first_visible_ms']=(begin+frames[first]['seconds']-ack['seconds'])*1000
                output['ack_to_95pct_surface_ms']=(begin+frames[full]['seconds']-ack['seconds'])*1000
                samples.append({key:output[key] for key in ['ack_to_first_visible_ms','ack_to_95pct_surface_ms','observed_fps']})
                (args.out/'info/notification-latency.json').write_text(json.dumps(samples,indent=2),encoding='utf-8')
            (args.out/'info'/(label+'.json')).write_text(json.dumps(output,indent=2),encoding='utf-8')
            print(json.dumps({'label':label,'frame_count':len(frames),'observed_fps':output['observed_fps'],'large_opening_drops':drops}),flush=True)
            if not output['opened']:raise RuntimeError('Panel did not open; recording is not a valid flicker check')
            if args.notification:
                if output['ack_to_first_visible_ms']>500 or output['ack_to_95pct_surface_ms']>500:raise AssertionError('Notification display exceeded 500 ms after ACK')
                gui.terminate();gui.wait(timeout=5)
                if cycle+1==args.cycles:gui=None;break
                gui=subprocess.Popen([str(app/'RemindAtDone.exe')],cwd=root,env=env,creationflags=0x08000000)
                for _ in range(100):
                    if entry_ready():break
                    time.sleep(.05)
                if not entry_ready():raise RuntimeError('Launcher was not ready for next notification')
                time.sleep(.2);continue
            close=command[:-1]+['-Invoke','关闭面板']
            subprocess.run(close,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=10,check=True,creationflags=0x08000000)
            for _ in range(60):
                if entry_ready():break
                time.sleep(.03)
            if not entry_ready():raise RuntimeError('Launcher did not collapse to its original bounds')
        if gui:gui.terminate();gui.wait(timeout=5);gui=None
finally:
    if gui and gui.poll() is None:gui.terminate();gui.wait(timeout=5)
    g.SelectObject(memory,previous);g.DeleteObject(bitmap);g.DeleteDC(memory);u.ReleaseDC(None,screen);u.PostMessageW(background,0x10,0,0)
