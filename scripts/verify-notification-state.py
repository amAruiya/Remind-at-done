"""A14/A20 real WPF + pipe fixture. No real task edits or terminal launch is needed."""
import argparse
import ctypes
from ctypes import wintypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--test-exe',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();app=args.app.resolve();test=args.test_exe.resolve();scripts=Path(__file__).resolve().parent
args.out.parent.mkdir(parents=True,exist_ok=True);checks={};user=ctypes.windll.user32
ctypes.windll.shcore.SetProcessDpiAwareness(2);user.GetForegroundWindow.restype=wintypes.HWND
user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
user.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD];user.MonitorFromWindow.restype=wintypes.HANDLE
monitors=[]
@ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HANDLE,wintypes.HDC,ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
def monitor_callback(handle,dc,rect,data):
    monitors.append((handle,(rect.contents.left,rect.contents.top,rect.contents.right,rect.contents.bottom)));return True
user.EnumDisplayMonitors(None,None,monitor_callback,0)
foreground=user.GetForegroundWindow();active_monitor=user.MonitorFromWindow(foreground,2)
monitor=next((bounds for handle,bounds in monitors if handle!=active_monitor),None)
if monitor is None:raise SystemExit('This desktop fixture needs a non-foreground monitor.')
def save():args.out.write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
def check(name,condition):
    checks[name]=bool(condition);save();print(('PASS ' if condition else 'FAIL ')+name,flush=True);assert condition,name
def window(pid):
    result=[]
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def callback(hwnd,_):
        owner=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and user.IsWindowVisible(hwnd):
            title=ctypes.create_unicode_buffer(128);user.GetWindowTextW(hwnd,title,128)
            if title.value.startswith('Remind'):
                rect=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect));result.append((hwnd,title.value,rect.right-rect.left,rect.bottom-rect.top))
        return True
    user.EnumWindows(callback,0);return result[0] if result else None
with tempfile.TemporaryDirectory(prefix='rad-burst-') as directory:
    root=Path(directory);shutil.copyfile(scripts/'fixtures/app-server',root/'app-server');(root/'state.json').write_text('{}')
    env=dict(os.environ,CODEX_HOME=str(root),RAD_DATA_DIR=str(root/'data'),DOTNET_ROOT=str(Path(os.environ['LOCALAPPDATA'])/'RemindAtDone.Build/dotnet'))
    instance=json.loads(subprocess.check_output([str(app/'rad.exe'),'register','--home',str(root),'--codex',shutil.which('node')],cwd=root,env=env,creationflags=0x08000000))
    settings=json.loads((root/'data/settings.json').read_text(encoding='utf-8'));settings.update(left=monitor[0]+12,top=monitor[3]-180,card_seconds=8,do_not_disturb=False,hide_launcher=False)
    (root/'data/settings.json').write_text(json.dumps(settings),encoding='utf-8')
    gui=subprocess.Popen([str(app/'RemindAtDone.exe')],cwd=root,env=env,creationflags=0x08000000)
    def payload(number,title):
        thread=f'00000000-0000-4000-8000-{number:012d}';key=f'burst:{number}'
        return {'schema_version':1,'instance_id':instance['id'],'thread_id':thread,'task_key':key,
                'event_id':hashlib.sha256(json.dumps([instance['id'],thread,key],separators=(',',':')).encode()).hexdigest(),
                'status':'completed','title':title,'summary':'受控批量提醒验收数据。','verification':'未运行其他项目测试',
                'completed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'elapsed_seconds':301,'timing_source':'context','cwd':str(root)}
    def send(reports):
        batch=root/'batch.json';batch.write_text(json.dumps(reports),encoding='utf-8')
        return json.loads(subprocess.check_output([str(test),'--wire-batch',str(batch)],env=env,timeout=10,creationflags=0x08000000))
    def ui(action=None):
        command=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(scripts/'ui-inspect.ps1'),'-ProcessId',str(gui.pid)]
        if action:command+=['-Invoke',action]
        text=subprocess.check_output(command,encoding='utf-8-sig',timeout=10,creationflags=0x08000000).strip();result=json.loads(text) if text else []
        return result if isinstance(result,list) else [result]
    try:
        time.sleep(.7);first=payload(0,'第一条固定目标');begin=time.monotonic();send([first]);rest=[payload(i,f'后续任务 {i}') for i in range(1,20)];send(rest)
        history=json.loads((root/'data/history.json').read_text(encoding='utf-8'))
        times=[dt.datetime.fromisoformat(item['stored_at']) for item in history];span=(max(times)-min(times)).total_seconds()
        checks['20_receipt_store_span_seconds']=span
        check('20_reports_saved_within_one_second',len(history)==20 and span<1)
        tree=ui();names=[item['name'] for item in tree]
        check('first_target_stays_fixed',any('第一条固定目标，打开任务'==name for name in names) and not any('后续任务' in name for name in names))
        check('additional_count_is_19',any(name=='另有 19 项' for name in names))
        check('no_separate_notification_window',window(gui.pid)[1]=='Remind at done')
        check('passive_notification_keeps_foreground',user.GetForegroundWindow()==foreground)
        while time.monotonic()-begin<12 and window(gui.pid)[2]>100:time.sleep(.03)
        elapsed=time.monotonic()-begin;checks['dismiss_elapsed_from_first_send']=elapsed
        check('eight_second_dwell_not_extended_by_burst',7.8<elapsed<9.5 and window(gui.pid)[2]<=60)
        send([payload(20,'冷却期收件')]);check('cooldown_does_not_open_again',window(gui.pid)[2]<=60)
        replayed=False
        while time.monotonic()-begin<31:
            replayed|=window(gui.pid)[2]>100;time.sleep(.1)
        check('cooldown_does_not_replay_backlog',not replayed)
        second=payload(100,'第二批固定目标');send([second]);send([payload(i,f'第二批后续 {i}') for i in range(101,120)])
        time.sleep(.4);check('new_event_after_cooldown_opens',window(gui.pid)[2]>100)
        (root/'state.json').write_text(json.dumps({'cwd':str(root/'missing-cwd')}),encoding='utf-8')
        ui('第二批固定目标，打开任务');time.sleep(.5);tree=ui()
        requests=[json.loads(line) for line in (root/'requests.jsonl').read_text().splitlines()]
        read=next(item for item in requests if item['method']=='thread/read')
        check('click_routes_to_original_batch_thread',read['params']['threadId']==second['thread_id'])
        check('missing_directory_is_reported',any('工作目录已不存在' in item['name'] for item in tree))
        check('failed_return_keeps_receipt',any(item['report']['event_id']==second['event_id'] for item in json.loads((root/'data/history.json').read_text(encoding='utf-8'))))
        check('copy_identifier_action_available',any(item['name']=='复制任务标识' for item in tree))
        def open_original_detail():
            tree=ui()
            back=next((item['name'] for item in tree if '返回任务列表' in item['name']),None)
            if back:ui(back)
            ui('已完成');ui('下一页');ui('第二批固定目标，查看详情')
        def return_from_detail():
            tree=ui();action=next(item['name'] for item in tree if item['name'].startswith('返回 Codex'))
            ui(action);time.sleep(.3);return ui()
        time.sleep(2.1);(root/'state.json').write_text(json.dumps({'read_fail':True}),encoding='utf-8')
        open_original_detail();tree=return_from_detail()
        check('deleted_thread_is_reported_without_losing_detail',any('Controlled missing thread' in item['name'] for item in tree) and any(item['name']=='第二批固定目标' for item in tree))
        time.sleep(2.1);(root/'state.json').write_text('{}',encoding='utf-8')
        helper=app/'resume-thread.ps1';saved_helper=root/'resume-thread.ps1'
        helper.rename(saved_helper)
        try:
            open_original_detail();tree=return_from_detail()
            check('missing_launch_helper_is_reported',any('缺少任务返回辅助文件' in item['name'] for item in tree))
        finally:saved_helper.rename(helper)
        check('all_failure_scenarios_preserve_receipt',any(item['report']['event_id']==second['event_id'] for item in json.loads((root/'data/history.json').read_text(encoding='utf-8'))))
    finally:
        if gui.poll() is None:gui.terminate();gui.wait(timeout=5)
        save()
