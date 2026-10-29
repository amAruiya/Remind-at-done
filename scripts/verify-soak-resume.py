"""Check observer handoff/continuation against a live app, with temporary observation files."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--data',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();results={};children=[]
monitor=Path(__file__).resolve().with_name('monitor-soak.py')
def check(name,value):
    results[name]=bool(value);print(('PASS ' if value else 'FAIL ')+name,flush=True);assert value,name
def command(path,hours):
    return [sys.executable,'-X','utf8',str(monitor),'--app',str(args.app.resolve()),'--data',str(args.data.resolve()),'--out',str(path),'--hours',str(hours)]
def start(arguments):
    child=subprocess.Popen(arguments,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000);children.append(child);return child
def finish(child):
    stdout,stderr=child.communicate(timeout=30)
    if child.returncode:raise RuntimeError((child.returncode,stdout.decode(),stderr.decode()))
try:
    with tempfile.TemporaryDirectory(prefix='rad-soak-check-') as directory:
        root=Path(directory);first_path=root/'first.json';base=command(first_path,.0025)
        first=start(base)
        for _ in range(80):
            if first_path.exists():break
            if first.poll() is not None:raise RuntimeError(first.communicate())
            time.sleep(.05)
        check('first_observer_is_live',first.poll() is None and first_path.exists())
        rejected=subprocess.run(base+['--resume'],capture_output=True,timeout=5,creationflags=0x08000000)
        check('concurrent_writer_is_refused',rejected.returncode!=0 and first.poll() is None)
        waiter=start(base+['--resume','--after-pid',str(first.pid)])
        time.sleep(.2)
        check('handoff_waits_for_live_predecessor',waiter.poll() is None and json.loads(first_path.read_text())['monitor_pid']==first.pid)
        finish(first);completed=first_path.read_bytes();finish(waiter)
        check('completed_observation_is_not_overwritten',first_path.read_bytes()==completed)
        original=json.loads(completed)
        check('fresh_run_meets_effective_duration',original['status']=='duration_observed' and original['observed_app_seconds']>=9)

        # Treat the measured first segment as a partial segment of an 18-second
        # fixture. The elapsed sample time itself is kept exactly as observed.
        resumed_path=root/'continued.json';partial=dict(original,target_hours=.005,status='incomplete_observation')
        resumed_path.write_text(json.dumps(partial),encoding='utf-8')
        shutil.copyfile(first_path.with_suffix('.csv'),resumed_path.with_suffix('.csv'))
        prefix=resumed_path.with_suffix('.csv').read_bytes()
        resumed=start(command(resumed_path,.005)+['--resume']);finish(resumed)
        final=json.loads(resumed_path.read_text());csv=resumed_path.with_suffix('.csv').read_bytes()
        check('prior_samples_are_preserved',csv.startswith(prefix) and len(csv)>len(prefix))
        check('original_start_is_preserved',final['started_at']==original['started_at'])
        check('resume_adds_effective_time',final['observed_app_seconds']>original['observed_app_seconds'] and final['observed_app_seconds']>=18)
        check('resumed_run_meets_target',final['status']=='duration_observed' and final['resumptions']==1)
        check('csv_header_is_not_duplicated',csv.count(b'timestamp,pid,')==1)
finally:
    for child in children:
        if child.poll() is None:child.terminate();child.wait(timeout=5)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(results,indent=2),encoding='utf-8')
