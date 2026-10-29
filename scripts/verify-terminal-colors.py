"""Check actual Codex SGR output in a hidden ConPTY; never send Ctrl+C or a prompt."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import runpy
import threading
import time

import psutil
from winpty import PtyProcess,Backend

parser=argparse.ArgumentParser();parser.add_argument('--codex',required=True);parser.add_argument('--helper',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();Proxy=runpy.run_path(str(Path(__file__).with_name('probe-daemon.py')))['Proxy']
thread_id=os.environ['CODEX_THREAD_ID'];home=os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))
proxy=Proxy(args.codex)
try:
    metadata=proxy.call('thread/read',{'threadId':thread_id,'includeTurns':False})['thread']
    before_turn=proxy.call('thread/turns/list',{'threadId':thread_id,'limit':1})['data'][0]['id']
finally:proxy.close()
cwd=metadata['cwd'];env=dict(os.environ,NO_COLOR='1',TERM='dumb',COLORTERM='')
capsule=base64.b64encode(json.dumps({'executable':args.codex,'codex_home':home,'thread_id':thread_id,'cwd':cwd}).encode()).decode()
def capture(command):
    terminal=PtyProcess.spawn(command,cwd=cwd,env=env,dimensions=(32,120),backend=Backend.ConPTY)
    pieces=[]
    def read():
        try:
            while True:pieces.append(terminal.read(32768))
        except (EOFError,OSError):pass
    threading.Thread(target=read,daemon=True).start()
    try:time.sleep(5)
    finally:
        # Terminate only the owned frontend process tree, without an interrupt event
        # that could propagate Ctrl+C to the shared daemon's running task.
        try:
            process=psutil.Process(terminal.pid)
            for child in process.children(recursive=True):
                commandline=child.cmdline()
                if 'resume' in commandline and thread_id in commandline:child.kill()
            if process.is_running():process.kill()
            process.wait(timeout=5)
        except psutil.NoSuchProcess:pass
        time.sleep(.2);terminal.close()
    text=''.join(pieces);codes=re.findall(r'\x1b\[([0-9;:]*)m',text)
    colors=[code for code in codes if any(n in [str(i) for i in range(30,38)]+[str(i) for i in range(90,98)]+['38','48'] for n in re.split('[;:]',code))]
    return {'characters':len(text),'sgr_count':len(codes),'color_sgr_count':len(colors),'color_sequences':sorted(set(colors))[:20]}

results={}
results['inherited_tool_environment']=capture([args.codex,'resume',thread_id,'--cd',cwd])
results['fixed_helper']=capture(['powershell','-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(args.helper.resolve()),'-Capsule',capsule])
proxy=Proxy(args.codex)
try:results['same_turn_after_view_tests']=proxy.call('thread/turns/list',{'threadId':thread_id,'limit':1})['data'][0]['id']==before_turn
finally:proxy.close()
results['passed']=results['fixed_helper']['color_sgr_count']>results['inherited_tool_environment']['color_sgr_count'] and results['same_turn_after_view_tests']
args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(results,indent=2),encoding='utf-8')
print(json.dumps(results),flush=True)
raise SystemExit(0 if results['passed'] else 1)
