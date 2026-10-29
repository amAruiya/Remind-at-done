"""Measure process-cold delivery through the real read-only daemon and isolated history.

The GUI is absent before each sample; OS file caches are not flushed. Only test
GUI processes matching both executable and RAD_DATA_DIR are stopped.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
import psutil

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--codex',required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--samples',type=int,default=30)
args=parser.parse_args();app=args.app.resolve();rad=app/'rad.exe';gui=app/'RemindAtDone.exe'
if args.samples<20:raise SystemExit('Use at least 20 samples for the p95 measurement.')
result={'scope':'GUI-process cold start; OS file cache warm; real read-only daemon, isolated data','samples_ms':[],
        'binary_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in app.glob('*.dll') if p.name in ['RemindAtDone.dll','RemindAtDone.Core.dll','rad.dll']}}
args.out.parent.mkdir(parents=True,exist_ok=True)
def save():args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
with tempfile.TemporaryDirectory(prefix='rad-cold-') as directory:
    data=Path(directory);env=dict(os.environ,RAD_DATA_DIR=str(data))
    def owned():
        found=[]
        for process in psutil.process_iter(['exe']):
            if process.info['exe'] and Path(process.info['exe']).resolve()==gui:
                try:
                    if process.environ().get('RAD_DATA_DIR')==str(data):found.append(process)
                except psutil.NoSuchProcess:pass
        return found
    def stop():
        for process in owned():process.terminate();process.wait(timeout=5)
    def run(*arguments):
        process=subprocess.run([str(rad),*arguments],env=env,capture_output=True,timeout=7,creationflags=0x08000000)
        if process.returncode:raise RuntimeError((process.returncode,process.stdout.decode('utf-8'),process.stderr.decode('utf-8',errors='replace')))
        return json.loads(process.stdout)
    try:
        run('register','--home',env.get('CODEX_HOME',str(Path.home()/'.codex')),'--codex',args.codex)
        settings=json.loads((data/'settings.json').read_text(encoding='utf-8'));settings.update(do_not_disturb=True,hide_launcher=True)
        (data/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
        for number in range(args.samples):
            if owned():raise AssertionError('A test GUI was already running before the cold sample')
            report={'task_key':f'cold-sample:{number}','status':'completed','title':'冷启动验收',
                    'summary':'隔离测试数据。','completed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'elapsed_seconds':301,'timing_source':'context'}
            payload=data/'report.json';payload.write_text(json.dumps(report),encoding='utf-8')
            begin=time.perf_counter();ack=run('notify','--file',str(payload));elapsed=(time.perf_counter()-begin)*1000
            assert ack['result']=='accepted',ack
            assert len(owned())==1,'Cold delivery did not start exactly one test GUI'
            receipts=json.loads((data/'history.json').read_text(encoding='utf-8'))
            assert any(row['report']['event_id']==ack['event_id'] for row in receipts),'ACK without a saved receipt'
            result['samples_ms'].append(elapsed);save();stop()
            if (number+1)%5==0:print(f'{number+1}/{args.samples} cold deliveries verified',flush=True)
        samples=sorted(result['samples_ms']);p95=samples[math.ceil(.95*len(samples))-1]
        result.update(sample_count=len(samples),median_ms=statistics.median(samples),p95_ms=p95,max_ms=max(samples),
                      all_accepted_and_persisted=True,one_gui_per_sample=True,passed=p95<=3000 and max(samples)<=5000)
        save();print(json.dumps({k:v for k,v in result.items() if k not in ['samples_ms','binary_sha256']}));assert result['passed']
    finally:stop();save()
