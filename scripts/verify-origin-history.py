"""Audit an actual corrected request and continued goal using metadata, not chat exports."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess

parser=argparse.ArgumentParser();parser.add_argument('--rad',type=Path,required=True);parser.add_argument('--turn',required=True);parser.add_argument('--task-key',required=True);parser.add_argument('--prior-live',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();result={};args.out.parent.mkdir(parents=True,exist_ok=True)
def check(name,value):
    result[name]=bool(value);args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(('PASS ' if value else 'FAIL ')+name,flush=True);assert value,name
def context(*options):
    return json.loads(subprocess.check_output([str(args.rad.resolve()),'context',*options],encoding='utf-8',timeout=35,creationflags=0x08000000))
current=context();check('current_main_identity_verified',current['thread_id']==os.environ['CODEX_THREAD_ID'] and not current['is_child'])
page=context('--turn',args.turn);messages=[]
for _ in range(100):
    messages.extend(page['user_messages'])
    if not page['next_cursor']:break
    page=context('--turn',args.turn,'--cursor',page['next_cursor'])
else:raise RuntimeError('History scan bound reached before the request was fully inspected')
origin=next(message for message in messages if message['task_key']==args.task_key)
corrections=[message for message in messages if message['started_at_ms']>origin['started_at_ms'] and '保持原样' in message['excerpt']]
check('later_size_correction_found',bool(corrections))
history=json.loads((Path(os.environ['LOCALAPPDATA'])/'RemindAtDone/history.json').read_text(encoding='utf-8'))
own=[row['report'] for row in history if row['report']['thread_id']==current['thread_id']]
receipt=next(report for report in own if report['task_key']==args.task_key)
completed=dt.datetime.fromisoformat(receipt['completed_at'])
started=dt.datetime.fromtimestamp(origin['started_at_ms']/1000,dt.timezone.utc)
expected=(completed-started).total_seconds();difference=abs(receipt['elapsed_seconds']-expected)
result['origin_started_at_ms']=origin['started_at_ms'];result['correction_started_at_ms']=[message['started_at_ms'] for message in corrections]
result['elapsed_difference_seconds']=difference
check('receipt_uses_original_request_time',difference<.01 and receipt['timing_source']=='history_metadata')
check('correction_did_not_create_extra_completion',not any(report['task_key'] in {message['task_key'] for message in corrections} for report in own))
prior=json.loads(args.prior_live.read_text(encoding='utf-8'))
original_goal=prior['context_evidence']['goal_created_at'];goal=current['goal']
result['goal_created_at']=original_goal
check('goal_start_preserved_across_continuations',goal['createdAt']==original_goal and len([turn for turn in current['turns'] if turn['started_at']>=original_goal])>=2)
check('unfinished_goal_has_no_completion_receipt',goal['status']=='active' and not any(report['task_key']==f'goal:{original_goal}' for report in own))
