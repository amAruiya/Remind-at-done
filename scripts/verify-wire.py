"""Real-process durable receipt tests: lost ACK then termination, and storage failure."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--test-exe',type=Path,required=True);parser.add_argument('--codex',required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();app=args.app.resolve();test=args.test_exe.resolve();checks={}
with tempfile.TemporaryDirectory(prefix='rad-wire-') as directory:
    root=Path(directory);env=dict(os.environ,RAD_DATA_DIR=str(root),DOTNET_ROOT=str(Path(os.environ['LOCALAPPDATA'])/'RemindAtDone.Build/dotnet'))
    def check(name,condition):
        checks[name]=bool(condition);print(('PASS ' if condition else 'FAIL ')+name,flush=True);assert condition,name
    result=subprocess.check_output([str(app/'rad.exe'),'register','--home',env.get('CODEX_HOME',str(Path.home()/'.codex')),'--codex',args.codex],env=env,creationflags=0x08000000)
    instance=json.loads(result);settings=json.loads((root/'settings.json').read_text(encoding='utf-8'));settings.update(do_not_disturb=True,hide_launcher=True)
    (root/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
    thread=env['CODEX_THREAD_ID'];key='wire:lost-ack'
    payload={'schema_version':1,'instance_id':instance['id'],'thread_id':thread,'task_key':key,
             'event_id':hashlib.sha256(json.dumps([instance['id'],thread,key],separators=(',',':')).encode()).hexdigest(),
             'status':'completed','title':'持久收据验证','summary':'ACK 未读取时重启验证。','completed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
             'elapsed_seconds':301,'timing_source':'context','cwd':str(root)}
    file=root/'payload.json';file.write_text(json.dumps(payload),encoding='utf-8')
    def start():
        process=subprocess.Popen([str(app/'RemindAtDone.exe')],env=env,creationflags=0x08000000);time.sleep(.6);return process
    gui=start()
    try:
        subprocess.run([str(test),'--wire-no-ack',str(file)],env=env,check=True,timeout=10,creationflags=0x08000000)
        for _ in range(50):
            if (root/'history.json').exists():break
            time.sleep(.02)
        check('commit_exists_without_client_ack',(root/'history.json').exists())
        gui.kill();gui.wait(timeout=5);gui=start()
        reply=json.loads(subprocess.check_output([str(test),'--wire',str(file)],env=env,timeout=10,creationflags=0x08000000))
        check('lost_ack_kill_retry_is_duplicate',reply['result']=='duplicate')
        check('single_record_after_kill_retry',len(json.loads((root/'history.json').read_text(encoding='utf-8')))==1)
        gui.terminate();gui.wait(timeout=5)
        (root/'history.json').unlink();gui=start();(root/'history.json').mkdir()
        result=subprocess.run([str(test),'--wire',str(file)],env=env,capture_output=True,timeout=10,creationflags=0x08000000)
        reply=json.loads(result.stdout)
        check('storage_failure_returns_4_without_success',result.returncode==4 and reply['result']=='error' and reply['error_code']=='storage')
    finally:
        if gui.poll() is None:gui.terminate();gui.wait(timeout=5)
args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(checks,indent=2),encoding='utf-8')
