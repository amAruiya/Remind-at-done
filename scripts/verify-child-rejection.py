"""Use metadata of this thread's existing child; do not start or modify agents."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--codex',required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();app=args.app.resolve();Proxy=runpy.run_path(str(Path(__file__).with_name('probe-daemon.py')))['Proxy']
proxy=Proxy(args.codex)
try:
    children=proxy.call('thread/list',{'parentThreadId':os.environ['CODEX_THREAD_ID'],'limit':5})['data']
    child=next((thread for thread in children if thread.get('parentThreadId')==os.environ['CODEX_THREAD_ID']),None)
    if child is None:raise SystemExit('No existing child metadata available; no agent was created.')
finally:proxy.close()
with tempfile.TemporaryDirectory(prefix='rad-child-') as directory:
    root=Path(directory);env=dict(os.environ,RAD_DATA_DIR=str(root),CODEX_THREAD_ID=child['id'])
    subprocess.run([str(app/'rad.exe'),'register','--home',env.get('CODEX_HOME',str(Path.home()/'.codex')),'--codex',args.codex],env=env,check=True,capture_output=True,creationflags=0x08000000)
    report={'task_key':'child-rejection-test','status':'completed','title':'子代理隔离验证','summary':'本报告应在发送前被拒绝。','completed_at':'2026-10-29T00:00:00Z','elapsed_seconds':600,'timing_source':'context'}
    payload=root/'report.json';payload.write_text(json.dumps(report),encoding='utf-8')
    response=subprocess.run([str(app/'rad.exe'),'notify','--file',str(payload)],env=env,capture_output=True,encoding='utf-8',timeout=10,creationflags=0x08000000)
    ack=json.loads(response.stdout)
    result={'existing_child_parent_matched':True,'exit_code':response.returncode,'rejected_before_delivery':response.returncode==2 and '子代理' in ack.get('message',''),
            'no_receipt_created':not (root/'history.json').exists()}
args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
assert result['rejected_before_delivery'] and result['no_receipt_created']
