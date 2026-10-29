"""Exercise real WPF controls through UI Automation, using an isolated history copy."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

import psutil

parser = argparse.ArgumentParser()
parser.add_argument('--app', type=Path, required=True)
parser.add_argument('--data', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--exercise-resume', action='store_true')
args = parser.parse_args()
args.app = args.app.resolve(); args.data = args.data.resolve(); args.out = args.out.resolve()
scripts = Path(__file__).resolve().parent
env = dict(os.environ, RAD_DATA_DIR=str(args.data))
settings = json.loads((args.data / 'settings.json').read_text(encoding='utf-8'))
settings.update(selected_tab='active', do_not_disturb=True, hide_launcher=False,theme='dark')
(args.data / 'settings.json').write_text(json.dumps(settings), encoding='utf-8')
app = subprocess.Popen([str(args.app / 'RemindAtDone.exe'),'--panel'], env=env, creationflags=0x08000000)
checks = {}
owned_frontends = []

def ui(invoke=None, open_panel=False):
    command = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(scripts / 'ui-inspect.ps1'), '-ProcessId', str(app.pid)]
    if invoke:
        command.extend(['-Invoke', invoke])
    if open_panel:
        command.append('-OpenPanel')
    output = subprocess.check_output(command, encoding='utf-8-sig', timeout=12, creationflags=0x08000000).strip()
    value = json.loads(output) if output else []
    return value if isinstance(value, list) else [value]

def check(name, condition):
    checks[name] = bool(condition)
    print(('PASS ' if condition else 'FAIL ') + name, flush=True)
    (args.out / 'info/ui-results.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    if not condition:
        raise AssertionError(name)

def screenshot(name):
    subprocess.run(['python', str(scripts / 'capture-window.py'), '--pid', str(app.pid), '--title', '任务',
                    '--out', str(args.out / name)], check=True, timeout=10, creationflags=0x08000000)

def codex_frontends():
    found = {}
    for process in psutil.process_iter(['name', 'cmdline']):
        command = process.info['cmdline'] or []
        if process.info['name'] == 'codex.exe' and 'resume' in command and env['CODEX_THREAD_ID'] in command:
            found[process.pid] = process
    return found

try:
    time.sleep(.8)
    tree = ui()
    names=[x['name'] for x in tree]
    check('active_tab_first_and_default',names.index('进行中')<names.index('已完成') and any('执行中' in name for name in names))
    ui('已完成');tree=ui()
    (args.out / 'info/ui-tree.json').write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf-8')
    check('history_10_rows_and_2_pages', sum(x['type'] == 'ControlType.Button' and '查看详情' in x['name'] for x in tree) == 10 and any('1 / 2' in x['name'] for x in tree))
    screenshot('completed-panel.png')
    ui('下一页'); tree = ui()
    check('next_page_navigation', any('2 / 2' in x['name'] for x in tree))
    row = next(x['name'] for x in tree if '查看详情' in x['name'])
    ui(row)
    check('detail_marks_only_one_read', sum(r['is_read'] for r in json.loads((args.data / 'history.json').read_text(encoding='utf-8'))) == 1)
    tree=ui();check('details_inside_same_panel',any(x['name']=='验证记录' for x in tree))
    ui(next(x['name'] for x in tree if '返回任务列表' in x['name']))
    ui('进行中'); tree = ui()
    check('active_contains_main_and_timestamp', any('执行中' in x['name'] for x in tree) and any('更新于' in x['name'] for x in tree))
    screenshot('active-panel.png')
    if args.exercise_resume:
        context_before = json.loads(subprocess.check_output([str(args.app / 'rad.exe'), 'context'], env=env, encoding='utf-8'))
        for attempt in range(2):
            before = codex_frontends()
            row = next(x['name'] for x in tree if x['type'] == 'ControlType.Button' and '打开任务' in x['name'])
            ui(row)
            time.sleep(2)
            added = {pid: process for pid, process in codex_frontends().items() if pid not in before}
            owned_frontends.extend(added.values())
            check(f'exact_resume_frontend_{attempt + 1}', len(added) == 1)
            context_after = json.loads(subprocess.check_output([str(args.app / 'rad.exe'), 'context'], env=env, encoding='utf-8'))
            check(f'active_turn_unchanged_{attempt + 1}', context_before['turns'][0]['task_key'] == context_after['turns'][0]['task_key'] and context_after['turns'][0]['status'] == 'inProgress')
            # Close only this test's newly launched TUI and its fixed-script PowerShell.
            for process in added.values():
                parent = process.parent()
                process.kill(); process.wait(timeout=5)
                if parent and parent.name().lower() == 'powershell.exe' and 'resume-thread.ps1' in ' '.join(parent.cmdline()):
                    parent.terminate()
            time.sleep(.3)
        check('closed_view_does_not_end_daemon_task', json.loads(subprocess.check_output([str(args.app / 'rad.exe'), 'context'], env=env, encoding='utf-8'))['turns'][0]['status'] == 'inProgress')
    counter = subprocess.check_output(['powershell', '-NoProfile', '-Command', f"Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -Filter 'IDProcess={app.pid}' | Select-Object WorkingSetPrivate,PercentProcessorTime | ConvertTo-Json -Compress"], encoding='utf-8', timeout=15, creationflags=0x08000000)
    checks['panel_counters'] = json.loads(counter)
    check('panel_private_working_set_under_120MiB', checks['panel_counters']['WorkingSetPrivate'] <= 120 * 1048576)
finally:
    if app.poll() is None:
        app.terminate(); app.wait(timeout=5)
    (args.out / 'info/ui-results.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
