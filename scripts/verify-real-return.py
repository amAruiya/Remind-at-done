"""Click real cards/history for two existing owned threads in the same directory.

Does not create prompts or delete threads. Closes only frontends started by this
test, identified by the fixed helper and exact capsule; never closes wt.exe.
"""
import argparse
import base64
import ctypes
from ctypes import wintypes as w
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import time
import psutil

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--codex',required=True);parser.add_argument('--prior',type=Path,required=True);parser.add_argument('--test-exe',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();app=args.app.resolve();scripts=Path(__file__).resolve().parent
prior=json.loads(args.prior.read_text(encoding='utf-8'));assert prior['status']=='passed'
identities=[prior['first_thread'],prior['second_thread']];markers=['Remind-at-done controlled workflow verified.',prior['marker_b']]
workspace=Path(prior['cwd']);assert workspace.parent.name.startswith('rad-e2e-') and workspace.is_dir()
Proxy=runpy.run_path(str(scripts/'probe-daemon.py'))['Proxy'];result={'checks':{},'views':{}};gui=None;frontends=[]
u=ctypes.windll.user32;u.GetForegroundWindow.restype=w.HWND;u.SetForegroundWindow.argtypes=[w.HWND];foreground=u.GetForegroundWindow()
args.out.parent.mkdir(parents=True,exist_ok=True)
def save():args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
def check(name,value):
    result['checks'][name]=bool(value);save();print(('PASS ' if value else 'FAIL ')+name,flush=True);assert value,name
def stop_frontend(process,identity):
    try:
        for child in process.children(recursive=True):
            command=child.cmdline()
            if 'resume' in command and identity in command:child.kill();child.wait(timeout=5)
        process.kill();process.wait(timeout=5)
    except psutil.NoSuchProcess:pass
def frontend_commands():
    for process in psutil.process_iter(['name','cmdline']):
        if process.info['name'] and process.info['name'].lower()=='powershell.exe':
            command=process.info['cmdline'] or []
            if '-Capsule' in command and str(app/'resume-thread.ps1') in command:
                try:yield process,json.loads(base64.b64decode(command[command.index('-Capsule')+1]))
                except (ValueError,IndexError):continue
proxy=Proxy(args.codex)
try:
    starts={identity:proxy.call('thread/turns/list',{'threadId':identity,'limit':1})['data'][0]['id'] for identity in identities}
    threads=[proxy.call('thread/read',{'threadId':identity,'includeTurns':False})['thread'] for identity in identities]
    check('both_owned_threads_are_idle_in_same_cwd',all(Path(thread['cwd'])==workspace and thread['status']['type'] in ['idle','notLoaded'] for thread in threads))
    check('original_terminal_views_are_closed',not any('resume' in (p.info['cmdline'] or []) and any(identity in p.info['cmdline'] for identity in identities) for p in psutil.process_iter(['cmdline'])))
finally:proxy.close()
try:
    with tempfile.TemporaryDirectory(prefix='rad-return-real-') as directory:
        root=Path(directory);settings=json.loads((Path(os.environ['LOCALAPPDATA'])/'RemindAtDone/settings.json').read_text(encoding='utf-8'))
        instance=next(item for item in settings['instances'] if Path(item['executable'])==Path(args.codex))
        settings.update(left=2400,top=1200,do_not_disturb=False,hide_launcher=False,selected_tab='completed',card_seconds=10)
        (root/'settings.json').write_text(json.dumps(settings),encoding='utf-8');env=dict(os.environ,RAD_DATA_DIR=str(root),DOTNET_ROOT=str(Path(os.environ['LOCALAPPDATA'])/'RemindAtDone.Build/dotnet'))
        console=root/'read-console.py'
        console.write_text(r'''
import ctypes,json,sys
from ctypes import wintypes as w
k=ctypes.windll.kernel32
class Coord(ctypes.Structure):_fields_=[('x',w.SHORT),('y',w.SHORT)]
class Rect(ctypes.Structure):_fields_=[('left',w.SHORT),('top',w.SHORT),('right',w.SHORT),('bottom',w.SHORT)]
class Info(ctypes.Structure):_fields_=[('size',Coord),('cursor',Coord),('attributes',w.WORD),('window',Rect),('maximum',Coord)]
k.CreateFileW.restype=w.HANDLE;k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
k.GetConsoleScreenBufferInfo.argtypes=[w.HANDLE,ctypes.POINTER(Info)]
k.ReadConsoleOutputCharacterW.argtypes=[w.HANDLE,w.LPWSTR,w.DWORD,Coord,ctypes.POINTER(w.DWORD)]
k.CloseHandle.argtypes=[w.HANDLE]
k.FreeConsole()
if not k.AttachConsole(int(sys.argv[1])):raise RuntimeError('Cannot attach to owned terminal console')
handle=k.CreateFileW('CONOUT$',0x80000000,3,None,3,0,None)
try:
    info=Info()
    if not k.GetConsoleScreenBufferInfo(handle,ctypes.byref(info)):raise RuntimeError('Cannot read owned console dimensions')
    length=min(info.size.x*info.size.y,2000000);text=ctypes.create_unicode_buffer(length+1);count=w.DWORD()
    if not k.ReadConsoleOutputCharacterW(handle,text,length,Coord(0,0),ctypes.byref(count)):raise RuntimeError('Cannot read owned console')
    print(json.dumps({'expected_context_visible':sys.argv[2] in text.value,'other_marker_absent':not sys.argv[3] or sys.argv[3] not in text.value}))
finally:k.CloseHandle(handle);k.FreeConsole()
''',encoding='utf-8')
        def launch():
            global gui
            gui=subprocess.Popen([str(app/'RemindAtDone.exe')],env=env,creationflags=0x08000000);time.sleep(.7)
        def ui(action=None,open_panel=False):
            command=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(scripts/'ui-inspect.ps1'),'-ProcessId',str(gui.pid)]
            if action:command+=['-Invoke',action]
            if open_panel:command+=['-OpenPanel']
            output=subprocess.check_output(command,encoding='utf-8-sig',timeout=10,creationflags=0x08000000).strip()
            tree=json.loads(output) if output else [];return tree if isinstance(tree,list) else [tree]
        def receive(index):
            identity=identities[index];key=f'real-return:{index}'
            payload=dict(schema_version=1,instance_id=instance['id'],thread_id=identity,task_key=key,
                event_id=hashlib.sha256(json.dumps([instance['id'],identity,key],separators=(',',':')).encode()).hexdigest(),status='completed',
                title=f'同目录任务 {"AB"[index]}',summary='受控返回验收，分别返回原有测试线程。',
                completed_at=dt.datetime.now(dt.timezone.utc).isoformat(),elapsed_seconds=301,timing_source='context',cwd=str(workspace))
            batch=root/'batch.json';batch.write_text(json.dumps([payload]),encoding='utf-8')
            subprocess.run([str(args.test_exe.resolve()),'--wire-batch',str(batch)],env=env,stdout=subprocess.DEVNULL,check=True,timeout=10,creationflags=0x08000000)
        def inspect_return(index,route,action):
            baseline={p.pid for p,_ in frontend_commands()};action()
            found=[]
            for _ in range(80):
                found=[(p,c) for p,c in frontend_commands() if p.pid not in baseline]
                if found:break
                time.sleep(.1)
            check(route+'_starts_one_frontend',len(found)==1)
            process,capsule=found[0];frontends.append((process,identities[index]))
            check(route+'_capsule_matches',capsule['thread_id']==identities[index] and Path(capsule['cwd'])==workspace and Path(capsule['codex_home'])==Path(instance['codex_home']))
            view=None
            for _ in range(12):
                time.sleep(.5)
                read=subprocess.run([sys.executable,str(console),str(process.pid),markers[index],markers[1] if index==0 else ''],capture_output=True,encoding='utf-8',timeout=5,creationflags=0x08000000)
                if read.returncode==0:
                    view=json.loads(read.stdout)
                    if view['expected_context_visible']:break
            if view is None:raise RuntimeError(read.stderr)
            result['views'][route]=view;check(route+'_context_matches',all(view.values()))
            commands=[child.cmdline() for child in process.children(recursive=True)]
            check(route+'_exact_resume_command',any('resume' in c and identities[index] in c and '--cd' in c and str(workspace) in c for c in commands))
            stop_frontend(process,identities[index]);frontends.remove((process,identities[index]));time.sleep(.3)
        # A fresh GUI per card resets only this fixture's cooldown, preserving history.
        for index in range(2):
            launch();receive(index);time.sleep(.5)
            inspect_return(index,f'card_{index}',lambda i=index:ui(f'同目录任务 {"AB"[i]}，打开任务'))
            gui.terminate();gui.wait(timeout=5);gui=None
        launch()
        for index in range(2):
            ui(open_panel=True);ui('已完成');ui(f'同目录任务 {"AB"[index]}，查看详情')
            inspect_return(index,f'history_{index}',lambda:ui('返回 Codex 任务  ↗'))
            # Returning to the terminal may close the panel on deactivation.
            time.sleep(.3)
        proxy=Proxy(args.codex)
        try:check('no_new_turns',all(proxy.call('thread/turns/list',{'threadId':identity,'limit':1})['data'][0]['id']==starts[identity] for identity in identities))
        finally:proxy.close()
        result['status']='passed';save()
finally:
    for process,identity in frontends:stop_frontend(process,identity)
    if gui and gui.poll() is None:gui.terminate();gui.wait(timeout=5)
    u.SetForegroundWindow(foreground);save()
