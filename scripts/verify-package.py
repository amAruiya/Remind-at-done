"""Extract a release away from the repository, then exercise its bundled CLI/GUI/runtime."""
import argparse
import csv
import ctypes
from ctypes import wintypes as w
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import zipfile
import psutil

parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();checks={};owned=[]
def check(name,value):
    checks[name]=bool(value);print(('PASS ' if value else 'FAIL ')+name,flush=True);assert value,name
with tempfile.TemporaryDirectory(prefix='rad-package-') as directory:
    root=Path(directory);app=root/'RemindAtDone';data=root/'data';data.mkdir();work=root/'unrelated-cwd';work.mkdir()
    with zipfile.ZipFile(args.archive) as archive:
        for item in archive.infolist():
            resolved=(root/item.filename).resolve()
            if not resolved.is_relative_to(app):raise ValueError('Unexpected archive path')
        archive.extractall(root)
    (data/'settings.json').write_text(json.dumps({'hide_launcher':True,'do_not_disturb':True}),encoding='utf-8')
    # Invalid global runtime paths ensure the bundled runtime is used.
    env=dict(os.environ,RAD_DATA_DIR=str(data),DOTNET_ROOT=str(root/'absent-runtime'),DOTNET_ROOT_X64=str(root/'absent-runtime'))
    try:
        help_result=subprocess.run([str(app/'rad.exe'),'--help'],cwd=work,env=env,capture_output=True,timeout=5,creationflags=0x08000000)
        check('standalone_cli_help',help_result.returncode==0 and b'rad notify' in help_result.stdout)
        started=subprocess.run([str(app/'rad.exe'),'start'],cwd=work,env=env,capture_output=True,timeout=5,creationflags=0x08000000)
        check('detached_start_returns',started.returncode==0 and json.loads(started.stdout)['result']=='started')
        for _ in range(100):
            owned=[p for p in psutil.process_iter(['exe']) if p.info['exe'] and Path(p.info['exe'])==app/'RemindAtDone.exe']
            if owned:break
            time.sleep(.05)
        check('one_extracted_gui_process',len(owned)==1)
        sid=next(csv.reader(io.StringIO(subprocess.check_output(['whoami','/user','/fo','csv','/nh'],encoding='utf-8'))))[1]
        session=w.DWORD();ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(),ctypes.byref(session))
        identity=f'{sid}|{session.value}|{str(data).upper()}'
        pipe=r'\\.\pipe\RemindAtDone-'+hashlib.sha256(identity.encode()).hexdigest()[:24]
        kernel=ctypes.windll.kernel32;kernel.WaitNamedPipeW.argtypes=[w.LPCWSTR,w.DWORD]
        for _ in range(100):
            if kernel.WaitNamedPipeW(pipe,100):break
            if not owned[0].is_running():raise RuntimeError('Extracted GUI exited before IPC was ready')
            time.sleep(.05)
        else:raise RuntimeError('Extracted GUI did not expose its IPC endpoint')
        # Invalid input must receive a bounded validation response without storing data.
        with open(pipe,'r+b',buffering=0) as channel:
            channel.write(struct.pack('<i',2)+b'{}')
            size=struct.unpack('<i',channel.read(4))[0]
            if not 0<size<=16384:raise RuntimeError('Invalid response length')
            response=json.loads(channel.read(size))
        check('extracted_gui_serves_ipc',response['result']=='error' and response['error_code']=='validation')
        check('invalid_input_not_stored',not (data/'history.json').exists())
    finally:
        # Only processes from this unique extracted package are eligible for cleanup.
        for process in psutil.process_iter(['exe']):
            if process.info['exe'] and Path(process.info['exe'])==app/'RemindAtDone.exe':
                process.terminate();process.wait(timeout=5)
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(checks,indent=2),encoding='utf-8')
