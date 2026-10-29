"""Windows real-process checks. Uses isolated data, real read-only daemon, no new prompts."""
import argparse
import concurrent.futures
import ctypes
from ctypes import wintypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

import psutil

parser = argparse.ArgumentParser()
parser.add_argument('--app', required=True, type=Path)
parser.add_argument('--out', required=True, type=Path)
parser.add_argument('--codex', required=True)
parser.add_argument('--idle-seconds', type=int, default=600)
args = parser.parse_args()
args.app = args.app.resolve(); args.out = args.out.resolve()
info = args.out / 'info'; info.mkdir(parents=True, exist_ok=True)
data = Path(tempfile.mkdtemp(prefix='rad-live-'))
env = dict(os.environ, RAD_DATA_DIR=str(data))
rad = args.app / 'rad.exe'
gui = args.app / 'RemindAtDone.exe'
results = {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'checks': {}, 'data': str(data)}
results['binary_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.app.glob('RemindAtDone*.dll')}
user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
ctypes.windll.shcore.SetProcessDpiAwareness(2)

def run(*command, timeout=35):
    result = subprocess.run([str(rad), *command], env=env, capture_output=True, text=True,
                            encoding='utf-8-sig', timeout=timeout, creationflags=0x08000000)
    try:
        return result.returncode, json.loads(result.stdout)
    except Exception:
        raise RuntimeError((command, result.returncode, result.stdout, result.stderr))

def check(name, okay, detail=None):
    results['checks'][name] = {'passed': bool(okay), 'detail': detail}
    save()
    print(('PASS ' if okay else 'FAIL ') + name, flush=True)
    if not okay:
        raise AssertionError((name, detail))

def save():
    (info / 'live-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

def windows(pid):
    found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == pid and user32.IsWindowVisible(hwnd):
            text = ctypes.create_unicode_buffer(256); user32.GetWindowTextW(hwnd, text, 256)
            rect = wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append((hwnd, text.value, (rect.left, rect.top, rect.right, rect.bottom)))
        return True
    user32.EnumWindows(callback, 0)
    return found

def report(key):
    return {'task_key': key, 'status': 'completed', 'title': '完成提醒集成验证',
            'summary': '中文、换行\n与“引号”已保留；点击卡片可回到对应任务。',
            'verification': '自动化验证中；完整人工验收未完成',
            'completed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'elapsed_seconds': 301, 'timing_source': 'context'}

def deliver(payload):
    filename = data / (payload['task_key'].replace(':', '_') + '.json')
    filename.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    begin = time.perf_counter(); result = run('notify', '--file', str(filename), timeout=10)
    return result, (time.perf_counter() - begin) * 1000

process = None
try:
    code, instance = run('register', '--home', env.get('CODEX_HOME', str(Path.home() / '.codex')), '--codex', args.codex)
    check('instance_registration', code == 0)
    settings = json.loads((data / 'settings.json').read_text(encoding='utf-8'))
    settings['do_not_disturb'] = True
    (data / 'settings.json').write_text(json.dumps(settings), encoding='utf-8')
    code, context = run('context')
    check('current_identity_and_start', code == 0 and context['thread_id'] == env['CODEX_THREAD_ID'] and
          not context['is_child'] and any(t['started_at'] for t in context['turns']))
    results['context_evidence'] = {'thread_matches_environment': True, 'turn_count': len(context['turns']),
                                  'goal_created_at': (context.get('goal') or {}).get('createdAt'),
                                  'cwd_matches': Path(context['cwd']).resolve() == Path.cwd().resolve()}
    code, active = run('active')
    check('real_active_snapshot_contains_current_main', code == 0 and any(t['thread_id'] == env['CODEX_THREAD_ID'] for t in active['tasks']), {'count': len(active.get('tasks', [])), 'failed_reads': active.get('failed_reads')})
    before = user32.GetForegroundWindow()
    cold_payloads = [report('cold:1'), report('cold:2')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        cold = list(executor.map(deliver, cold_payloads))
    check('two_simultaneous_cold_deliveries', all(r[0][0] == 0 for r in cold), cold)
    candidates = [p for p in psutil.process_iter(['exe']) if p.info['exe'] and Path(p.info['exe']).resolve() == gui]
    check('single_gui_instance', len(candidates) == 1, len(candidates))
    process = candidates[0]
    time.sleep(.5)
    check('passive_foreground_unchanged', before == user32.GetForegroundWindow())
    check('dnd_does_not_expand_launcher', all(w[2][2]-w[2][0] <= 112 for w in windows(process.pid)))
    check('silent_receipts_stay_unread', all(not r['is_read'] for r in json.loads((data / 'history.json').read_text(encoding='utf-8'))))
    (code, ack), _ = deliver(cold_payloads[0]); check('duplicate_is_receipt_only', code == 0 and ack['result'] == 'duplicate')
    changed = dict(cold_payloads[0], summary='不同内容')
    (code, ack), _ = deliver(changed); check('conflict_exit_code', code == 5 and ack['error_code'] == 'conflict')
    (code, ack), _ = deliver(dict(report('invalid:title'), title='长'*25));check('validation_exit_code',code==2)
    burst = [dict(report(f'burst:{i}'), title=f'并发验证任务 {i}') for i in range(20)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        replies = list(executor.map(deliver, burst))
    check('20_process_concurrent_delivery', all(r[0][0] == 0 for r in replies), [r[0] for r in replies if r[0][0] != 0])
    persisted = json.loads((data / 'history.json').read_text(encoding='utf-8'))
    check('latest_20_receipts_retained', len(persisted) == 20 and all(r['report']['task_key'].startswith('burst:') for r in persisted))
    samples = []
    for i in range(100):
        last_payload = report(f'hot:{i}')
        (code, ack), milliseconds = deliver(last_payload)
        if code: raise AssertionError(ack)
        samples.append(milliseconds)
    results['hot_delivery_ms'] = {'samples': samples, 'p95': sorted(samples)[94], 'median': statistics.median(samples)}
    check('hot_delivery_p95_under_500ms', sorted(samples)[94] <= 500, sorted(samples)[94])
    process.kill(); process.wait(timeout=5)
    launched = subprocess.Popen([str(gui)], env=env, creationflags=0x08000000)
    process = psutil.Process(launched.pid)
    time.sleep(1)
    check('restart_does_not_expand_launcher', all(w[2][2]-w[2][0] <= 112 for w in windows(process.pid)))
    (code, ack), _ = deliver(last_payload); check('retry_after_kill_still_duplicate', code == 0 and ack['result'] == 'duplicate')
    check('restart_retains_20_receipts', len(json.loads((data / 'history.json').read_text(encoding='utf-8'))) == 20)
    results['idle_pid'] = process.pid; results['idle_started_at'] = dt.datetime.now(dt.timezone.utc).isoformat(); save()
    begin_cpu = sum(process.cpu_times()[:2]); begin = time.monotonic(); memory = []
    private_working_set = []
    next_counter = begin
    while time.monotonic() - begin < args.idle_seconds:
        counters = process.memory_info(); memory.append(getattr(counters, 'private', counters.rss))
        if time.monotonic() >= next_counter:
            output = subprocess.check_output(['powershell', '-NoProfile', '-Command', f"Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -Filter 'IDProcess={process.pid}' | Select-Object -ExpandProperty WorkingSetPrivate"],
                                             encoding='utf-8', timeout=15, creationflags=0x08000000).strip()
            private_working_set.append(int(output)); next_counter = time.monotonic() + 60
        time.sleep(min(5, max(.01, args.idle_seconds - (time.monotonic() - begin))))
    cpu_percent = (sum(process.cpu_times()[:2]) - begin_cpu) / (time.monotonic() - begin) / psutil.cpu_count() * 100
    results['idle'] = {'seconds': time.monotonic() - begin, 'whole_machine_cpu_percent': cpu_percent,
                       'private_commit_mib_max': max(memory, default=process.memory_info().private) / 1048576,
                       'private_working_set_mib_samples': [v / 1048576 for v in private_working_set],
                       'note': 'psutil private is private commit; private working set measured separately by performance counter.'}
    check('idle_cpu_budget', cpu_percent <= .2, cpu_percent)
    if private_working_set:
        check('idle_private_working_set_under_80MiB', max(private_working_set) <= 80 * 1048576, max(private_working_set) / 1048576)
    save()
finally:
    if process and process.is_running():
        process.terminate()
    save()
