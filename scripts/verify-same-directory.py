"""Two owned real daemon threads in one cwd; close and reopen hidden PowerShell TUI views.
Only context-presence booleans are saved, never full terminal conversation content.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import runpy
import threading
import time
import uuid
import psutil
from winpty import PtyProcess,Backend

parser=argparse.ArgumentParser();parser.add_argument('--codex',required=True);parser.add_argument('--helper',type=Path,required=True);parser.add_argument('--prior',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();Proxy=runpy.run_path(str(Path(__file__).with_name('probe-daemon.py')))['Proxy']
prior=json.loads(args.prior.read_text(encoding='utf-8'));assert prior['status']=='passed'
cwd=Path(prior['workspace']);data=Path(prior['data']);assert cwd.parent.name.startswith('rad-e2e-')
marker_a='Remind-at-done controlled workflow verified.'
assert (cwd/'result.txt').read_text(encoding='utf-8-sig').strip()==marker_a
first_id=prior['thread_id'];marker_b='RAD-SAME-DIRECTORY-B-'+uuid.uuid4().hex[:12]
state={'status':'starting','cwd':str(cwd),'first_thread':first_id,'marker_b':marker_b};args.out.parent.mkdir(parents=True,exist_ok=True)
def save():args.out.write_text(json.dumps(state,indent=2),encoding='utf-8')
proxy=Proxy(args.codex)
try:
    original=proxy.call('thread/read',{'threadId':first_id,'includeTurns':False})['thread']
    assert Path(original['cwd'])==cwd and original['status']['type'] in ['idle','notLoaded']
    original_turn=proxy.call('thread/turns/list',{'threadId':first_id,'limit':1})['data'][0]['id']
    second_id=proxy.call('thread/start',{'cwd':str(cwd),'config':{'shell_environment_policy.set':{'RAD_DATA_DIR':str(data)}}})['thread']['id']
    prompt=f'受控同目录验收 B：读取当前目录 result.txt，再创建 second.txt，内容严格为 {marker_b} 加末尾换行。回读核对后给出简短最终答复，并包含此标识。只操作这两个测试文件，不修改其他文件或全局配置，不使用子代理。'
    second_turn=proxy.call('turn/start',{'threadId':second_id,'input':[{'type':'text','text':prompt}]})['turn']['id']
    state.update(second_thread=second_id,status='running');save()
finally:proxy.close()
print('Created one owned same-directory validation task; original control connection closed.',flush=True)
start=time.monotonic()
while time.monotonic()-start<180:
    proxy=Proxy(args.codex)
    try:
        if proxy.call('thread/read',{'threadId':second_id,'includeTurns':False})['thread']['status']['type']=='idle':break
    finally:proxy.close()
    time.sleep(5)
else:
    state['status']='observation_timeout';save();raise SystemExit('Observation timed out; task was not cancelled.')
assert (cwd/'second.txt').read_text(encoding='utf-8-sig').strip()==marker_b
home=os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))
def read_view(thread_id,expected,forbidden=None):
    capsule=base64.b64encode(json.dumps({'executable':args.codex,'codex_home':home,'thread_id':thread_id,'cwd':str(cwd)}).encode()).decode()
    terminal=PtyProcess.spawn(['powershell','-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(args.helper.resolve()),'-Capsule',capsule],cwd=str(cwd),env=dict(os.environ,NO_COLOR='1',TERM='dumb'),dimensions=(60,140),backend=str(Backend.ConPTY))
    output=[]
    def reader():
        try:
            while True:output.append(terminal.read(32768))
        except (EOFError,OSError):pass
    threading.Thread(target=reader,daemon=True).start()
    try:time.sleep(5)
    finally:
        try:
            process=psutil.Process(terminal.pid)
            for child in process.children(recursive=True):
                command=child.cmdline()
                if 'resume' in command and thread_id in command:child.kill()
            if process.is_running():process.kill()
            process.wait(timeout=5)
        except psutil.NoSuchProcess:pass
        time.sleep(.2);terminal.close()
    text=''.join(output);text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
    return {'expected_context_visible':expected in text,'other_marker_absent':forbidden is None or forbidden not in text}

state['views']={}
for round_number in [1,2]:
    state['views'][f'first_{round_number}']=read_view(first_id,marker_a,marker_b)
    state['views'][f'second_{round_number}']=read_view(second_id,marker_b)
    save();print(f'Closed both PowerShell views after round {round_number}.',flush=True)
proxy=Proxy(args.codex)
try:
    state['same_cwd']=all(Path(proxy.call('thread/read',{'threadId':identity,'includeTurns':False})['thread']['cwd'])==cwd for identity in [first_id,second_id])
    state['no_new_turns']=all(proxy.call('thread/turns/list',{'threadId':identity,'limit':1})['data'][0]['id']==turn for identity,turn in [(first_id,original_turn),(second_id,second_turn)])
finally:proxy.close()
state['status']='passed' if state['same_cwd'] and state['no_new_turns'] and all(all(check.values()) for check in state['views'].values()) else 'incomplete'
save();print(json.dumps(state),flush=True);raise SystemExit(0 if state['status']=='passed' else 1)
