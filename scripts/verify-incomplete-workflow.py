"""A real >10 minute unfinished task, then pause/failure follow-ups in the same thread.

One owned daemon thread and temporary workspace. No existing task is changed;
the installed finishing instruction supplies the reminder skill automatically.
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

parser=argparse.ArgumentParser();parser.add_argument('--codex',required=True);parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--resume',action='store_true')
args=parser.parse_args();app=args.app.resolve();args.out.parent.mkdir(parents=True,exist_ok=True)
Proxy=runpy.run_path(str(Path(__file__).with_name('probe-daemon.py')))['Proxy']
prior=json.loads(args.out.read_text(encoding='utf-8')) if args.resume else None
if prior and prior.get('status')=='passed':
    print(json.dumps(prior));raise SystemExit(0)
root=Path(prior['workspace']).parent if prior else Path(tempfile.mkdtemp(prefix='rad-incomplete-'))
assert root.name.startswith('rad-incomplete-')
workspace=root/'workspace';workspace.mkdir(exist_ok=True);data=root/'data'
env=dict(os.environ,RAD_DATA_DIR=str(data))
subprocess.run([str(app/'rad.exe'),'register','--home',env.get('CODEX_HOME',str(Path.home()/'.codex')),'--codex',args.codex],env=env,capture_output=True,check=True,creationflags=0x08000000)
settings=json.loads((data/'settings.json').read_text(encoding='utf-8'));settings.update(do_not_disturb=True,hide_launcher=True)
(data/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
(workspace/'await-input.ps1').write_text('''$ErrorActionPreference='Stop'
$begin=[DateTimeOffset]::UtcNow
$begin.ToString('o') | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'waiting-started.txt') -Encoding UTF8
while (([DateTimeOffset]::UtcNow-$begin).TotalSeconds -lt 610) {
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'input.txt')) { exit 0 }
    Start-Sleep -Seconds 1
}
Write-Output 'Input remains missing after 610 seconds. The requested output has not been produced.'
exit 2
''',encoding='utf-8-sig')
state=prior or {'status':'starting','monitor_pid':os.getpid(),'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),
       'workspace':str(workspace),'data':str(data),'cases':{}}
state['monitor_pid']=os.getpid()
def save():args.out.write_text(json.dumps(state,indent=2),encoding='utf-8')
def receipts():return json.loads((data/'history.json').read_text(encoding='utf-8')) if (data/'history.json').exists() else []
def start_turn(prompt):
    proxy=Proxy(args.codex)
    try:return proxy.call('turn/start',{'threadId':state['thread_id'],'input':[{'type':'text','text':prompt}]})['turn']['id']
    finally:proxy.close()
def observe(name,turn,limit):
    begin=time.monotonic();case={'turn_id':turn,'status':'running'};state['cases'][name]=case;save()
    while time.monotonic()-begin<limit:
        proxy=Proxy(args.codex)
        try:thread=proxy.call('thread/read',{'threadId':state['thread_id'],'includeTurns':False})['thread']
        finally:proxy.close()
        case['elapsed_seconds']=time.monotonic()-begin;case['last_thread_status']=thread['status'];case['no_receipt_so_far']=not receipts();save()
        if receipts():raise AssertionError('An unfinished task produced a completion receipt')
        if thread['status']['type']=='idle':break
        time.sleep(10 if limit>300 else 2)
    else:
        case['status']='observation_timeout';state['status']='observation_timeout';save()
        raise SystemExit('Observation timed out; the owned task was not cancelled.')
    proxy=Proxy(args.codex)
    try:
        cursor=None;commands=[]
        while True:
            page=proxy.call('thread/items/list',{'threadId':state['thread_id'],'turnId':turn,'cursor':cursor,'limit':100})
            commands.extend(row['item'].get('command','') for row in page['data'] if row['item']['type']=='commandExecution')
            cursor=page.get('nextCursor')
            if not cursor:break
    finally:proxy.close()
    case['skill_read_command_observed']=any('remind-at-done' in command.lower() and 'skill.md' in command.lower() for command in commands)
    case['no_completion_receipt']=not receipts();case['requested_output_absent']=not (workspace/'result.txt').exists()
    # Pause/failure are follow-ups to the same unfinished goal. A fresh file read
    # is recorded separately; A02 requires no completion report, not rereading a
    # skill that was just loaded for that goal before its waiting response.
    case['skill_already_read_for_same_task']=any(previous.get('skill_read_command_observed') for previous in state['cases'].values())
    case['status']='passed' if case['skill_already_read_for_same_task'] and case['no_completion_receipt'] and case['requested_output_absent'] else 'incomplete'
    save();print(f'{name}: '+case['status'],flush=True)
    if case['status']!='passed':raise AssertionError(case)
save();proxy=Proxy(args.codex)
try:
    if prior:
        thread=proxy.call('thread/read',{'threadId':state['thread_id'],'includeTurns':False})['thread']
        assert Path(thread['cwd'])==workspace and thread['status']['type']=='idle'
        assert state['cases']['waiting_after_ten_minutes']['status']=='passed' and state['actual_wait_seconds']>=600
    else:state['thread_id']=proxy.call('thread/start',{'cwd':str(workspace),'config':{'shell_environment_policy.set':{'RAD_DATA_DIR':str(data)}}})['thread']['id']
finally:proxy.close()
prompt=(f'这是受控文件处理任务。先核对 RAD_DATA_DIR 严格等于 {data}，不要修改这个变量；若不同，立即报告未完成。'
        '目标是把当前目录 input.txt 的文本转成大写写入 result.txt，再核对结果。input.txt 由外部提供，可能需要等候。'
        '环境核对通过后，执行当前目录 await-input.ps1，等待输入出现。脚本最长等待 610 秒；等待期间保持执行，不要使用子代理。'
        '若脚本报告输入仍缺失，不得创建 input.txt 或 result.txt，也不能声称目标已完成；只说明缺少输入并停在等待输入状态。'
        '本任务只允许操作这个测试目录，不能修改全局配置或其他任务。')
if not prior:
    turn=start_turn(prompt);state['status']='running';save();print('Owned unfinished task started; original control connection closed.',flush=True)
    observe('waiting_after_ten_minutes',turn,850)
    start_file=workspace/'waiting-started.txt'
    if not start_file.exists():raise AssertionError('The required wait was not started')
    waiting_start=dt.datetime.fromisoformat(start_file.read_text(encoding='utf-8-sig').strip())
    state['actual_wait_seconds']=(dt.datetime.now(dt.timezone.utc)-waiting_start).total_seconds()
    if state['actual_wait_seconds']<600:raise AssertionError('Incomplete scenario did not cross ten minutes')
if 'paused' not in state['cases']:
    observe('paused',start_turn('同一个文件处理目标现在暂停。不要继续等待，也不要生成或修改结果文件；保留未完成状态。'),180)
else:
    paused=state['cases']['paused']
    assert paused['no_completion_receipt'] and paused['requested_output_absent'] and not receipts()
    paused['skill_already_read_for_same_task']=state['cases']['waiting_after_ten_minutes']['skill_read_command_observed']
    assert paused['skill_already_read_for_same_task'];paused['status']='passed';save()
observe('failed',start_turn('同一个文件处理目标已确认无法完成：输入文件不会提供。请结束这次失败的处理，说明未产生结果；这不是一个新的独立成果任务。'),180)
state['status']='passed';state['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat();save();print(json.dumps(state),flush=True)
