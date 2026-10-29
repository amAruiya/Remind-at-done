"""Exercise startup opt-in/out through the real settings UI, restoring HKCU afterward."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import winreg

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();app=args.app.resolve();checks={};gui=None
user=ctypes.windll.user32;user.GetForegroundWindow.restype=ctypes.c_void_p;user.SetForegroundWindow.argtypes=[ctypes.c_void_p]
foreground=user.GetForegroundWindow()
run_path=r'Software\Microsoft\Windows\CurrentVersion\Run'
def current():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,run_path) as key:return winreg.QueryValueEx(key,'RemindAtDone')
    except FileNotFoundError:return None
original=current()
def check(name,value):
    checks[name]=bool(value);print(('PASS ' if value else 'FAIL ')+name,flush=True);assert value,name
try:
    with tempfile.TemporaryDirectory(prefix='rad-settings-') as directory:
        root=Path(directory);settings=json.loads((Path(os.environ['LOCALAPPDATA'])/'RemindAtDone/settings.json').read_text(encoding='utf-8'))
        settings.update(left=2400,top=1200,selected_tab='completed',do_not_disturb=False,hide_launcher=False,login_startup=False)
        (root/'settings.json').write_text(json.dumps(settings),encoding='utf-8');env=dict(os.environ,RAD_DATA_DIR=str(root))
        gui=subprocess.Popen([str(app/'RemindAtDone.exe'),'--panel'],env=env,creationflags=0x08000000)
        time.sleep(.8)
        script=root/'controls.ps1'
        script.write_text(r'''
param([int]$ProcessId,[string]$Name,[switch]$Toggle)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$condition=New-Object System.Windows.Automation.PropertyCondition ([System.Windows.Automation.AutomationElement]::ProcessIdProperty),$ProcessId
for($attempt=0;$attempt -lt 40;$attempt++) {
    $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,$condition)
    foreach($window in $windows) {
        $elements=$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
        foreach($element in $elements) {
            if($element.Current.Name -eq $Name) {
                if($Toggle) {$element.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Toggle()}
                else {$element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()}
                exit 0
            }
        }
    }
    Start-Sleep -Milliseconds 50
}
throw 'Owned settings control was not found'
''',encoding='utf-8-sig')
        def action(name,toggle=False):
            command=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-ProcessId',str(gui.pid),'-Name',name]
            if toggle:command+=['-Toggle']
            result=subprocess.run(command,capture_output=True,timeout=10,creationflags=0x08000000)
            if result.returncode:raise RuntimeError(result.stderr.decode('utf-8',errors='replace'))
        check('startup_unchanged_before_opt_in',current()==original)
        action('设置');action('登录时启动',True);action('保存设置')
        registered=current();expected='"'+str(app/'RemindAtDone.exe')+'"'
        check('startup_points_to_quoted_executable',registered==(expected,winreg.REG_SZ))
        check('startup_opt_in_persisted',json.loads((root/'settings.json').read_text(encoding='utf-8'))['login_startup'] is True)
        action('设置');action('登录时启动',True);action('减少动画',True);action('保存设置')
        check('startup_opt_out_removes_entry',current() is None)
        saved=json.loads((root/'settings.json').read_text(encoding='utf-8'))
        check('startup_opt_out_persisted',saved['login_startup'] is False)
        check('reduce_motion_setting_persisted',saved['reduce_motion'] is True)
finally:
    if gui and gui.poll() is None:gui.terminate();gui.wait(timeout=5)
    user.SetForegroundWindow(foreground)
    # Only this tool's single Run value is touched, never other startup entries.
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,run_path) as key:
        if original is None:
            try:winreg.DeleteValue(key,'RemindAtDone')
            except FileNotFoundError:pass
        else:winreg.SetValueEx(key,'RemindAtDone',0,original[1],original[0])
    checks['original_startup_configuration_restored']=current()==original
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(checks,indent=2),encoding='utf-8')
