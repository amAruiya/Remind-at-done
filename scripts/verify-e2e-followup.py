"""A fresh short task in the already-owned long-test thread must not reuse its age."""
import argparse
import json
from pathlib import Path
import runpy
import time

Proxy=runpy.run_path(str(Path(__file__).with_name('probe-daemon.py')))['Proxy']
parser=argparse.ArgumentParser();parser.add_argument('--codex',required=True);parser.add_argument('--long-result',required=True,type=Path);parser.add_argument('--out',required=True,type=Path)
args=parser.parse_args();prior=json.loads(args.long_result.read_text(encoding='utf-8'))
assert prior['status']=='passed'
thread_id=prior['thread_id'];workspace=Path(prior['workspace']);data=Path(prior['data'])
assert workspace.parent.name.startswith('rad-e2e-') and (workspace/'result.txt').exists()
before={r['report']['event_id'] for r in json.loads((data/'history.json').read_text(encoding='utf-8'))}
proxy=Proxy(args.codex)
try:
    thread=proxy.call('thread/read',{'threadId':thread_id,'includeTurns':False})['thread']
    assert Path(thread['cwd'])==workspace and thread['status']['type'] in ('idle','notLoaded')
    proxy.call('thread/resume',{'threadId':thread_id,'config':{'shell_environment_policy.set':{'RAD_DATA_DIR':str(data)}}})
    turn=proxy.call('turn/start',{'threadId':thread_id,'input':[{'type':'text','text':'这是一个新的独立任务：读取当前目录 result.txt，确认内容是否仍为 Remind-at-done controlled workflow verified.（含末尾换行）。只读核对，不修改文件。'}]})['turn']['id']
finally:proxy.close()
result={'thread_id':thread_id,'turn_id':turn,'status':'running'}
def save():args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
save();begin=time.monotonic()
while time.monotonic()-begin<180:
    proxy=Proxy(args.codex)
    try:
        thread=proxy.call('thread/read',{'threadId':thread_id,'includeTurns':False})['thread']
        if thread['status']['type']=='idle':break
    finally:proxy.close()
    time.sleep(5)
else:
    result['status']='observation_timeout';save();raise SystemExit('Observation timeout; task was not cancelled.')
after={r['report']['event_id'] for r in json.loads((data/'history.json').read_text(encoding='utf-8'))}
result['duration_seconds']=round(time.monotonic()-begin,2);result['no_new_receipt']=before==after
proxy=Proxy(args.codex)
try:
    page=proxy.call('thread/items/list',{'threadId':thread_id,'turnId':turn,'limit':100})
    commands=[row['item'].get('command','') for row in page['data'] if row['item']['type']=='commandExecution']
    result['skill_read_command_observed']=any('remind-at-done' in command.lower() and 'skill.md' in command.lower() for command in commands)
    result['file_read_observed']=any('result.txt' in command for command in commands)
finally:proxy.close()
result['status']='passed' if result['duration_seconds']<300 and result['no_new_receipt'] and result['skill_read_command_observed'] and result['file_read_observed'] else 'incomplete'
save();print(json.dumps(result),flush=True);raise SystemExit(0 if result['status']=='passed' else 1)
