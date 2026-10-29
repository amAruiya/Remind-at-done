"""Controlled protocol/UI failures. These fixtures complement, not replace, real daemon tests."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();app=args.app.resolve();scripts=Path(__file__).resolve().parent
checks={}
with tempfile.TemporaryDirectory(prefix='rad-adapter-') as temporary:
    root=Path(temporary);shutil.copyfile(scripts/'fixtures/app-server',root/'app-server')
    env=dict(os.environ,CODEX_HOME=str(root),RAD_DATA_DIR=str(root/'data'))
    def state(**values):(root/'state.json').write_text(json.dumps(values),encoding='utf-8')
    def run(*command):
        return json.loads(subprocess.check_output([str(app/'rad.exe'),*command],cwd=root,env=env,encoding='utf-8',timeout=35,creationflags=0x08000000))
    def check(name,condition):
        checks[name]=bool(condition);print(('PASS ' if condition else 'FAIL ')+name,flush=True)
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(checks,indent=2),encoding='utf-8')
        assert condition,name
    state();instance=run('register','--home',str(root),'--codex',shutil.which('node'))
    response=run('active');rows=response['tasks']
    check('50_main_tasks_all_pages',len(rows)==50)
    check('children_and_idle_excluded',all(int(row['thread_id'][-12:])<50 for row in rows))
    check('older_active_not_lost',any(row['title']=='Older active task' for row in rows))
    check('waiting_first',rows[0]['waiting'] and rows[0]['status']=='等待用户操作')
    check('unknown_and_error_are_explicit',any(row['status']=='状态待确认' for row in rows) and any(row['status']=='需要处理' for row in rows))
    state(read_fail=True);response=run('active');check('partial_failure_not_fake_empty_success',response['failed_reads']==66 and not response['tasks'])
    history=[];timestamp=dt.datetime.now(dt.timezone.utc).isoformat()
    for index in range(20):
        task_key=f'fixture:{index}';thread_id=rows[0]['thread_id']
        payload={'schema_version':1,'instance_id':instance['id'],'thread_id':thread_id,'task_key':task_key,
                 'event_id':hashlib.sha256(json.dumps([instance['id'],thread_id,task_key],separators=(',',':')).encode()).hexdigest(),
                 'status':'completed','title':f'历史数据样例 {index}','summary':'用于验证 50 项进行中与 20 项历史同时存在时的内存预算。',
                 'completed_at':timestamp,'elapsed_seconds':301,'timing_source':'context','cwd':str(root)}
        history.append({'report':payload,'stored_at':timestamp,'is_read':False})
    (root/'data/history.json').write_text(json.dumps(history),encoding='utf-8')
    state();gui=subprocess.Popen([str(app/'RemindAtDone.exe'),'--panel'],cwd=root,env=env,creationflags=0x08000000)
    def ui(action=None):
        command=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(scripts/'ui-inspect.ps1'),'-ProcessId',str(gui.pid)]
        if action:command+=['-Invoke',action]
        output=subprocess.check_output(command,encoding='utf-8-sig',timeout=10,creationflags=0x08000000).strip()
        parsed=json.loads(output) if output else [];return parsed if isinstance(parsed,list) else [parsed]
    try:
        time.sleep(1);tree=ui();check('five_active_ui_pages',any('1 / 5' in x['name'] for x in tree))
        memory=subprocess.check_output(['powershell','-NoProfile','-Command',f"Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -Filter 'IDProcess={gui.pid}' | Select-Object -ExpandProperty WorkingSetPrivate"],encoding='utf-8',creationflags=0x08000000)
        checks['private_working_set_mib_50_active_20_history']=int(memory.strip())/1048576
        check('50_active_20_history_under_120MiB',int(memory.strip())<=120*1048576)
        count=(root/'requests.jsonl').read_text().count('\n');time.sleep(2)
        check('visible_panel_does_not_poll',count==(root/'requests.jsonl').read_text().count('\n'))
        state(read_fail=True);ui('刷新');time.sleep(.4);tree=ui()
        check('read_failure_retains_old_snapshot',any('1 / 5' in x['name'] for x in tree) and any('未更新' in x['name'] for x in tree))
        state(fail=True);ui('刷新');time.sleep(.3);tree=ui()
        check('connection_failure_retains_old_snapshot',any('1 / 5' in x['name'] for x in tree) and any('未更新' in x['name'] for x in tree))
        state(delay_ms=3000);ui('刷新');ui('已完成');time.sleep(3.2);tree=ui()
        check('cancelled_query_does_not_overwrite_completed_page',any('最近 3 天' in x['name'] for x in tree) and not any('未更新' in x['name'] for x in tree))
    finally:
        if gui.poll() is None:gui.terminate();gui.wait(timeout=5)
