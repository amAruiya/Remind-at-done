"""Exercise return failures through the actual history/detail UI, without opening terminals."""
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
import uuid

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();app=args.app.resolve();scripts=Path(__file__).resolve().parent;results={}
for case in ['deleted_thread','missing_directory','missing_helper','missing_executable']:
    with tempfile.TemporaryDirectory(prefix='rad-return-') as directory:
        root=Path(directory);data=root/'data';data.mkdir();shutil.copyfile(scripts/'fixtures/app-server',root/'app-server')
        state={'read_fail':True} if case=='deleted_thread' else {'cwd':str(root/'missing')} if case=='missing_directory' else {}
        (root/'state.json').write_text(json.dumps(state),encoding='utf-8')
        instance=str(uuid.uuid4());thread='00000000-0000-4000-8000-000000000100';key='return:'+case
        executable=str(root/'missing.exe') if case=='missing_executable' else shutil.which('node')
        settings={'instances':[{'id':instance,'codex_home':str(root),'executable':executable}],
                  'theme':'dark','selected_tab':'completed','do_not_disturb':True,'left':-68,'top':1300}
        (data/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
        timestamp=dt.datetime.now(dt.timezone.utc).isoformat()
        report={'schema_version':1,'event_id':hashlib.sha256(json.dumps([instance,thread,key],separators=(',',':')).encode()).hexdigest(),
                'instance_id':instance,'thread_id':thread,'task_key':key,'status':'completed','title':'返回失败验收','summary':'保留这条失败返回的摘要。','verification':'未运行其他项目测试',
                'completed_at':timestamp,'elapsed_seconds':301,'timing_source':'context','cwd':str(root)}
        (data/'history.json').write_text(json.dumps([{'report':report,'stored_at':timestamp,'is_read':False}]),encoding='utf-8')
        env=dict(os.environ,CODEX_HOME=str(root),RAD_DATA_DIR=str(data));helper=app/'resume-thread.ps1';backup=root/'helper.ps1'
        if case=='missing_helper':helper.rename(backup)
        gui=subprocess.Popen([str(app/'RemindAtDone.exe'),'--panel'],cwd=root,env=env,creationflags=0x08000000)
        probe=root/'inspect.ps1'
        probe.write_text(r'''
param([int]$ProcessId)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$filter=New-Object System.Windows.Automation.PropertyCondition ([System.Windows.Automation.AutomationElement]::ProcessIdProperty),$ProcessId
function Find-Elements {
    $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,$filter)
    foreach($window in $windows){$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)}
}
function Click-Matching([string]$pattern) {
    for($attempt=0;$attempt -lt 80;$attempt++) {
        foreach($element in (Find-Elements)) {
            if($element.Current.Name -like $pattern -and $element.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button) {
                $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke(); return
            }
        }
        Start-Sleep -Milliseconds 50
    }
    throw "Control was not available: $pattern"
}
Click-Matching '*查看详情'
Start-Sleep -Milliseconds 120
Click-Matching '返回 Codex*'
for($attempt=0;$attempt -lt 100;$attempt++) {
    $names=@(Find-Elements | ForEach-Object {$_.Current.Name})
    if($names -contains '暂时无法返回任务') {$names | ConvertTo-Json -Compress;exit 0}
    Start-Sleep -Milliseconds 50
}
throw 'No return error was rendered'
''',encoding='utf-8-sig')
        try:
            names=json.loads(subprocess.check_output(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(probe),'-ProcessId',str(gui.pid)],encoding='utf-8-sig',timeout=15,creationflags=0x08000000))
            expected={'deleted_thread':'Controlled missing thread','missing_directory':'工作目录已不存在','missing_helper':'缺少任务返回辅助文件','missing_executable':'找不到指定的文件'}[case]
            history=json.loads((data/'history.json').read_text(encoding='utf-8'))
            results[case]={'specific_error_visible':any(expected in name for name in names),'summary_still_visible':'保留这条失败返回的摘要。' in names,
                           'receipt_preserved':len(history)==1 and history[0]['report']==report,'copy_action_available':'复制任务标识' in names}
            print(case+': '+str(results[case]),flush=True);assert all(results[case].values())
        finally:
            if gui.poll() is None:gui.terminate();gui.wait(timeout=5)
            if backup.exists():backup.rename(helper)
            args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(results,indent=2),encoding='utf-8')
