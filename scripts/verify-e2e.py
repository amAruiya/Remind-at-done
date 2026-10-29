"""Explicit design P0/P1 controlled Codex task; creates one isolated test thread.

The user prompt does not mention the reminder skill. Global installed instructions
must cause the real agent to invoke it. No existing task is modified/interrupted.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import time

Proxy=runpy.run_path(str(Path(__file__).with_name('probe-daemon.py')))['Proxy']
parser=argparse.ArgumentParser();parser.add_argument('--codex',required=True);parser.add_argument('--app',required=True,type=Path);parser.add_argument('--out',required=True,type=Path)
args=parser.parse_args();args.app=args.app.resolve();args.out=args.out.resolve();args.out.parent.mkdir(parents=True,exist_ok=True)
root=Path(tempfile.mkdtemp(prefix='rad-e2e-'));workspace=root/'workspace';workspace.mkdir();data=root/'data'
env=dict(os.environ,RAD_DATA_DIR=str(data))
subprocess.run([str(args.app/'rad.exe'),'register','--home',env.get('CODEX_HOME',str(Path.home()/'.codex')),'--codex',args.codex],env=env,check=True,capture_output=True,creationflags=0x08000000)
settings=json.loads((data/'settings.json').read_text(encoding='utf-8'));settings.update(left=3000,top=1500,theme='dark')
(data/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
state={'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'workspace':str(workspace),'data':str(data),'status':'starting'}
def save():args.out.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
save();proxy=Proxy(args.codex)
try:
    started=proxy.call('thread/start',{'cwd':str(workspace),'config':{'shell_environment_policy.set':{'RAD_DATA_DIR':str(data)}}})
    thread_id=started['thread']['id'];state['thread_id']=thread_id
    # Match the isolated UI instance above; a missing env override must abort before the long wait.
    prompt=(f'这是一个受控的本地文件验收任务，只操作当前目录。先核对环境变量 RAD_DATA_DIR 严格等于 {data}；'
            '不要自行设置或修改该变量，若不匹配就报告验收未完成并结束。'
            '核对通过后，等待当前目录的 ready.txt 出现，测试程序会在约 310 秒后生成它。'
            '等待期间保持任务运行，不要提前答复完成，不要使用子代理，也不要修改全局设置。'
            '出现 ready.txt 后，读取它，将相同内容写入 result.txt（UTF-8），再读取 result.txt 核对内容完全相同。'
            '以上步骤全部完成后，正常给出简短最终答复。')
    turn=proxy.call('turn/start',{'threadId':thread_id,'input':[{'type':'text','text':prompt}]})
    state['turn_id']=turn['turn']['id'];state['status']='running';save()
finally:proxy.close()  # Original controlling client gone; daemon must continue.
print('Started controlled daemon task; original control connection closed.',flush=True)
begin=time.monotonic();ready=False;done=False
while time.monotonic()-begin<600:
    elapsed=time.monotonic()-begin
    if elapsed>=310 and not ready:
        (workspace/'ready.txt').write_text('Remind-at-done controlled workflow verified.\n',encoding='utf-8');ready=True
        state['ready_written_at']=dt.datetime.now(dt.timezone.utc).isoformat();save()
    proxy=Proxy(args.codex)
    try:
        thread=proxy.call('thread/read',{'threadId':thread_id,'includeTurns':False})['thread']
        state['last_thread_status']=thread['status'];state['elapsed_seconds']=round(elapsed,1);save()
        if thread['status']['type']=='idle':
            state['status']='agent_finished';done=True;break
    finally:proxy.close()
    print(f'Controlled task running: {elapsed:.0f}s; ready={ready}',flush=True)
    time.sleep(10)
if not done:
    state['status']='observation_timeout';save();print('Observation deadline reached; task was NOT cancelled.',flush=True);raise SystemExit(2)
history=json.loads((data/'history.json').read_text(encoding='utf-8')) if (data/'history.json').exists() else []
receipt=next((r for r in history if r['report']['thread_id']==thread_id),None)
state['result_file_matches']=ready and (workspace/'result.txt').exists() and (workspace/'result.txt').read_text(encoding='utf-8-sig')==(workspace/'ready.txt').read_text(encoding='utf-8')
state['completion_report_received']=receipt is not None
if receipt:
    report=receipt['report'];state['receipt']={k:report[k] for k in ('event_id','task_key','elapsed_seconds','timing_source','completed_at')}
    state['duration_over_300']=report['elapsed_seconds']>300
proxy=Proxy(args.codex)
try:
    cursor=None;read_skill=False;types=set()
    while True:
        page=proxy.call('thread/items/list',{'threadId':thread_id,'turnId':state['turn_id'],'cursor':cursor,'limit':100})
        for row in page['data']:
            item=row['item'];types.add(item['type'])
            command=item.get('command','')
            if isinstance(command,str) and 'remind-at-done' in command.lower() and 'skill.md' in command.lower():read_skill=True
        cursor=page.get('nextCursor')
        if not cursor:break
    state['skill_read_command_observed']=read_skill;state['item_types']=sorted(types)
finally:proxy.close()
state['status']='passed' if state['result_file_matches'] and receipt and state['duration_over_300'] and state['skill_read_command_observed'] else 'incomplete'
state['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat();save();print(json.dumps(state,ensure_ascii=False),flush=True)
raise SystemExit(0 if state['status']=='passed' else 1)
