"""Bounded workday observation of the installed app. No daemon polling or task creation."""
import argparse
import csv
import ctypes
from ctypes import wintypes
import datetime as dt
import json
import math
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--data',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--hours',type=float,default=8);parser.add_argument('--detach',action='store_true');parser.add_argument('--resume',action='store_true');parser.add_argument('--after-pid',type=int)
args=parser.parse_args();args.app=args.app.resolve();args.data=args.data.resolve();args.out=args.out.resolve();args.out.parent.mkdir(parents=True,exist_ok=True)
if not math.isfinite(args.hours) or args.hours<=0:raise SystemExit('--hours must be finite and positive.')
if args.after_pid and not args.resume:raise SystemExit('--after-pid requires --resume.')
if args.detach:
    command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--app',str(args.app),'--data',str(args.data),'--out',str(args.out),'--hours',str(args.hours)]
    if args.resume:command.append('--resume')
    if args.after_pid:command+=['--after-pid',str(args.after_pid)]
    with args.out.with_suffix('.log').open('ab') as log:
        process=subprocess.Popen(command,stdout=log,stderr=log,close_fds=True,creationflags=0x08000000)
    print(json.dumps({'pid':process.pid,'command':command,'hours':args.hours}));raise SystemExit(0)

def matching_monitor(pid):
    try:
        process=psutil.Process(pid);command=process.cmdline()
        if str(Path(__file__).resolve()) not in command:return None
        for option,expected in [('--app',args.app),('--data',args.data),('--out',args.out)]:
            if option not in command or Path(command[command.index(option)+1]).resolve()!=expected:return None
        return process
    except (psutil.NoSuchProcess,IndexError):return None
    except psutil.AccessDenied:raise SystemExit('Cannot verify the prior observer; existing samples were not touched.')

if args.after_pid:
    previous=matching_monitor(args.after_pid)
    if previous is None and psutil.pid_exists(args.after_pid):raise SystemExit('The predecessor PID does not match this observation.')
    if previous:
        print(f'Waiting for existing observer {previous.pid}; no samples or state will be overwritten.',flush=True)
        while True:
            try:previous.wait(timeout=60);break
            except psutil.TimeoutExpired:continue
            except psutil.NoSuchProcess:break

# New observers serialize writes. A predecessor from an older version is only
# resumed once its actual process has exited, even if its state file is stale.
lock=args.out.with_suffix('.lock').open('a+b')
if lock.tell()==0:lock.write(b'0');lock.flush()
lock.seek(0)
try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
except OSError:raise SystemExit('Another observer owns this output.')

class Counters(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
        ('peak_ws','ws','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private_commit','private_ws','shared_commit')]
kernel=ctypes.windll.kernel32;psapi=ctypes.windll.psapi
kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
kernel.CloseHandle.argtypes=[wintypes.HANDLE]
psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
def memory(pid):
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle:raise OSError('Cannot inspect app process')
    try:
        result=Counters();result.cb=ctypes.sizeof(result)
        if not psapi.GetProcessMemoryInfo(handle,ctypes.byref(result),result.cb):raise OSError('Memory counter failed')
        return result.private_ws,result.private_commit
    finally:kernel.CloseHandle(handle)
def find_app():
    for process in psutil.process_iter(['exe']):
        if not process.info['exe'] or Path(process.info['exe']).resolve()!=args.app:continue
        try:
            override=process.environ().get('RAD_DATA_DIR')
            if (Path(override).resolve() if override else Path(os.environ['LOCALAPPDATA'])/'RemindAtDone')==args.data:return process
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    return None

state=json.loads(args.out.read_text(encoding='utf-8')) if args.resume else {'status':'running','monitor_pid':os.getpid(),'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'target_hours':args.hours,
       'scope':'Installed GUI process; no daemon or transcript reads. Mixed-workflow semantics require review.',
       'samples':0,'observed_app_seconds':0,'max_private_working_set_mib':0,'max_private_commit_mib':0,'app_restarts':0}
csv_path=args.out.with_suffix('.csv')
if args.resume:
    if matching_monitor(state['monitor_pid']):raise SystemExit('The prior observer is still running; use --after-pid to wait for it.')
    if not csv_path.is_file():raise SystemExit('Cannot resume without the original sample CSV.')
    if state['target_hours']!=args.hours:raise SystemExit('Resume must retain the original duration target.')
    if state['observed_app_seconds']>=args.hours*3600:
        print('The effective observation duration is already complete.');raise SystemExit(0)
elif args.out.exists() or csv_path.exists():raise SystemExit('Output already exists; use --resume rather than replacing it.')
state.update(status='running',monitor_pid=os.getpid(),target_hours=args.hours)
if args.resume:state['resumed_at']=dt.datetime.now(dt.timezone.utc).isoformat();state['resumptions']=state.get('resumptions',0)+1
state.pop('finished_at',None)
start=time.monotonic();last=start;last_pid=None;last_cpu=None
# Bound missing-app/suspend gaps to one extra hour, and count only intervals
# observed in the same live app process. A wall-clock deadline alone is not a pass.
remaining=max(0,args.hours*3600-state['observed_app_seconds']);deadline=start+remaining+3600
with csv_path.open('a' if args.resume else 'w',newline='',encoding='utf-8') as stream:
    writer=csv.writer(stream)
    if not args.resume:writer.writerow(['timestamp','pid','private_working_set_mib','private_commit_mib','whole_machine_cpu_percent','sample_gap_seconds'])
    stream.flush()
    while time.monotonic()<deadline and state['observed_app_seconds']<args.hours*3600:
        now=time.monotonic();delta=now-last;process=find_app()
        if process:
            try:
                private_ws,private_commit=memory(process.pid);cpu=sum(process.cpu_times()[:2]);percent=0
                if process.pid==last_pid and last_cpu is not None and delta>0:
                    percent=(cpu-last_cpu)/delta/psutil.cpu_count()*100
                    if delta<125:state['observed_app_seconds']+=delta
                elif last_pid is not None:state['app_restarts']+=1
                last_pid,last_cpu=process.pid,cpu
                state['samples']+=1;state['app_pid']=process.pid
                state['max_private_working_set_mib']=max(state['max_private_working_set_mib'],private_ws/1048576)
                state['max_private_commit_mib']=max(state['max_private_commit_mib'],private_commit/1048576)
                writer.writerow([dt.datetime.now(dt.timezone.utc).isoformat(),process.pid,private_ws/1048576,private_commit/1048576,percent,delta]);stream.flush()
            except (psutil.NoSuchProcess,psutil.AccessDenied,OSError) as error:state['last_observation_error']=type(error).__name__
        else:state['app_pid']=None;last_pid=None;last_cpu=None
        observed_at=dt.datetime.now(dt.timezone.utc)
        state['updated_at']=observed_at.isoformat();state['elapsed_seconds']=(observed_at-dt.datetime.fromisoformat(state['started_at'])).total_seconds()
        args.out.write_text(json.dumps(state,indent=2),encoding='utf-8');last=now
        if state['observed_app_seconds']>=args.hours*3600:break
        time.sleep(min(60,max(.1,args.hours*3600-state['observed_app_seconds']),max(.1,deadline-time.monotonic())))
state['status']='duration_observed' if state['observed_app_seconds']>=args.hours*3600 else 'incomplete_observation'
state['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat();args.out.write_text(json.dumps(state,indent=2),encoding='utf-8')
lock.close()
