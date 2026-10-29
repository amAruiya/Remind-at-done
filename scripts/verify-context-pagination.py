"""Pass the actual context cursor through Windows PowerShell 5.1 to a fixture daemon."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();app=args.app.resolve();scripts=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='rad-pagination-') as directory:
    root=Path(directory);shutil.copyfile(scripts/'fixtures/app-server',root/'app-server');(root/'state.json').write_text('{}')
    env=dict(os.environ,CODEX_HOME=str(root),RAD_DATA_DIR=str(root/'data'),CODEX_THREAD_ID='00000000-0000-4000-8000-000000000000')
    subprocess.run([str(app/'rad.exe'),'register','--home',str(root),'--codex',shutil.which('node')],cwd=root,env=env,capture_output=True,check=True,creationflags=0x08000000)
    script=root/'page.ps1'
    script.write_text("$ErrorActionPreference='Stop'\n[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)\n$first=& $args[0] context | ConvertFrom-Json\n$second=& $args[0] context --cursor $first.next_cursor | ConvertFrom-Json\n@{first=$first;second=$second} | ConvertTo-Json -Depth 12 -Compress\n",encoding='utf-8-sig')
    result=json.loads(subprocess.check_output(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),str(app/'rad.exe')],cwd=root,env=env,encoding='utf-8-sig',timeout=20,creationflags=0x08000000))
    first,second=result['first'],result['second']
    requests=[json.loads(line) for line in (root/'requests.jsonl').read_text().splitlines()]
    received=[request['params'].get('cursor') for request in requests if request['method']=='thread/turns/list']
    checks={'first_page_20':len(first['turns'])==20,'next_page_5':len(second['turns'])==5,
            'all_25_distinct':len({turn['task_key'] for turn in first['turns']+second['turns']})==25,
            'oldest_origin_reachable':second['turns'][-1]['started_at']==1793247500,
            'cursor_survives_ps51':json.loads(received[-1])['offset']==20,'last_cursor_null':second['next_cursor'] is None}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(checks));assert all(checks.values())
