"""Verify passive notifications during real typing, and Tab/Esc in the task panel.

Uses an owned editor and isolated app data. Aborts input if foreground ownership
changes; restores the previous foreground window and never types in user apps.
"""
import argparse
import ctypes
from ctypes import wintypes as w
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--app', type=Path, required=True)
parser.add_argument('--test-exe', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
app = args.app.resolve()
u = ctypes.windll.user32
ctypes.windll.shcore.SetProcessDpiAwareness(2)
u.GetForegroundWindow.restype = w.HWND
u.SetForegroundWindow.argtypes = [w.HWND]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
u.FindWindowExW.restype = w.HWND
u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u.WindowFromPoint.argtypes = [w.POINT]; u.WindowFromPoint.restype = w.HWND
u.GetAncestor.argtypes = [w.HWND, w.UINT]; u.GetAncestor.restype = w.HWND
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
u.SendMessageTimeoutW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM, w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)]

class Keyboard(ctypes.Structure):
    _fields_ = [('vk', w.WORD), ('scan', w.WORD), ('flags', w.DWORD), ('time', w.DWORD), ('extra', ctypes.c_size_t)]

class Mouse(ctypes.Structure):
    _fields_ = [('dx', w.LONG), ('dy', w.LONG), ('data', w.DWORD), ('flags', w.DWORD), ('time', w.DWORD), ('extra', ctypes.c_size_t)]

class Payload(ctypes.Union):
    _fields_ = [('keyboard', Keyboard), ('mouse', Mouse)]

class Input(ctypes.Structure):
    _fields_ = [('kind', w.DWORD), ('payload', Payload)]

def keys(hwnd, code, unicode=False):
    if u.GetForegroundWindow() != hwnd:
        raise RuntimeError('Input target changed; no further keyboard input was sent.')
    events = (Input * 2)()
    for index in range(2):
        events[index].kind = 1
        events[index].payload.keyboard = Keyboard(0 if unicode else code, code if unicode else 0, (4 if unicode else 0) | (2 if index else 0), 0, 0)
    if u.SendInput(2, events, ctypes.sizeof(Input)) != 2:
        raise RuntimeError('Keyboard input was not delivered')

def windows(pid):
    found = []
    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def each(hwnd, _):
        owner = w.DWORD(); u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and u.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(128); u.GetWindowTextW(hwnd, title, 128)
            rect = w.RECT(); u.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append((hwnd, title.value, rect.right - rect.left))
        return True
    u.EnumWindows(each, 0)
    return found

def wait_for(predicate):
    for _ in range(100):
        value = predicate()
        if value: return value
        time.sleep(.05)
    raise RuntimeError('Expected UI state did not arrive')

results = {}; gui = editor = None; foreground = u.GetForegroundWindow()
cursor = w.POINT(); u.GetCursorPos(ctypes.byref(cursor))
def check(name, condition):
    results[name] = bool(condition)
    print(('PASS ' if condition else 'FAIL ') + name, flush=True)
    assert condition, name

try:
    with tempfile.TemporaryDirectory(prefix='rad-keyboard-') as directory:
        root = Path(directory)
        settings = json.loads((Path(os.environ['LOCALAPPDATA']) / 'RemindAtDone/settings.json').read_text(encoding='utf-8'))
        settings.update(left=-68, top=1300, selected_tab='completed', do_not_disturb=False, hide_launcher=False, card_seconds=8, reduce_motion=False)
        (root / 'settings.json').write_text(json.dumps(settings), encoding='utf-8')
        env = dict(os.environ, RAD_DATA_DIR=str(root), DOTNET_ROOT=str(Path(os.environ['LOCALAPPDATA']) / 'RemindAtDone.Build/dotnet'))
        editor_script = root / 'editor.ps1'
        editor_script.write_text('''Add-Type -AssemblyName System.Windows.Forms
$form=New-Object Windows.Forms.Form
$form.Text='Remind input acceptance'
$form.TopMost=$true
$form.StartPosition='Manual';$form.Location=New-Object Drawing.Point(300,300);$form.Size=New-Object Drawing.Size(500,180)
$edit=New-Object Windows.Forms.TextBox;$edit.Multiline=$true;$edit.Dock='Fill';$form.Controls.Add($edit)
$form.Add_Shown({$form.Activate();$edit.Focus()})
[Windows.Forms.Application]::Run($form)
''', encoding='utf-8-sig')
        editor = subprocess.Popen(['powershell', '-NoProfile', '-File', str(editor_script)], creationflags=0x08000000)
        editor_hwnd = wait_for(lambda: next((h for h,t,width in windows(editor.pid) if t == 'Remind input acceptance'), None))
        edit = wait_for(lambda: u.FindWindowExW(editor_hwnd, None, None, None))
        time.sleep(.4)
        u.SetWindowPos(editor_hwnd, -1, 0, 0, 0, 0, 0x13)
        cloaked = w.DWORD(); ctypes.windll.dwmapi.DwmGetWindowAttribute(w.HWND(editor_hwnd), 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value:
            raise RuntimeError('The owned editor is on an inactive virtual desktop; keyboard acceptance requires a visible desktop.')
        bounds = w.RECT(); u.GetWindowRect(edit, ctypes.byref(bounds))
        point = w.POINT(bounds.left+20, bounds.top+20)
        if u.GetAncestor(u.WindowFromPoint(point), 2) != editor_hwnd:
            raise RuntimeError(f'Owned editor is not under the test point: {point.x},{point.y}; editor={editor_hwnd}, edit={edit}, hit={u.WindowFromPoint(point)}')
        u.SetCursorPos(point.x, point.y)
        u.mouse_event(2,0,0,0,0); time.sleep(.05); u.mouse_event(4,0,0,0,0)
        wait_for(lambda: u.GetForegroundWindow() == editor_hwnd)
        gui = subprocess.Popen([str(app / 'RemindAtDone.exe')], env=env, creationflags=0x08000000)
        wait_for(lambda: windows(gui.pid))
        instance = settings['instances'][0]['id']; thread = '00000000-0000-4000-8000-000000000001'; task = 'keyboard-check'
        report = dict(schema_version=1, instance_id=instance, thread_id=thread, task_key=task,
            event_id=hashlib.sha256(json.dumps([instance, thread, task], separators=(',', ':')).encode()).hexdigest(),
            status='completed', title='连续输入验收', summary='受控提醒，不属于用户任务。',
            completed_at=dt.datetime.now(dt.timezone.utc).isoformat(), elapsed_seconds=301, timing_source='context', cwd=str(root))
        batch = root / 'batch.json'; batch.write_text(json.dumps([report]), encoding='utf-8')
        expected = ''; expanded = False; collapsed_after = False; sender = None
        for index in range(110):
            if index == 10:
                sender = subprocess.Popen([str(args.test_exe.resolve()), '--wire-batch', str(batch)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x08000000)
            character = chr(ord('a') + index % 26)
            keys(editor_hwnd, ord(character), unicode=True); expected += character
            current = windows(gui.pid)
            expanded |= any(width > 100 for _,_,width in current)
            collapsed_after |= expanded and any(width <= 60 for _,_,width in current)
            time.sleep(.1)
        sender.communicate(timeout=5); check('report_accepted', sender.returncode == 0)
        actual = ctypes.create_unicode_buffer(1024); response = ctypes.c_size_t()
        if not u.SendMessageTimeoutW(edit, 0xD, 1024, ctypes.addressof(actual), 2, 2000, ctypes.byref(response)):
            raise RuntimeError('Owned editor did not return its test text')
        check('all_typed_characters_reach_editor', actual.value == expected)
        check('notification_expands_and_dismisses_during_typing', expanded and collapsed_after)
        check('editor_keeps_foreground', u.GetForegroundWindow() == editor_hwnd)

        # The panel is intentionally activated from here onward.
        ui = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(Path(__file__).with_name('ui-inspect.ps1')), '-ProcessId', str(gui.pid)]
        subprocess.run(ui + ['-OpenPanel'], check=True, stdout=subprocess.DEVNULL, creationflags=0x08000000)
        panel = wait_for(lambda: next((h for h,_,width in windows(gui.pid) if width > 100 and u.GetForegroundWindow() == h), None))
        focus_script = root / 'focus.ps1'
        focus_script.write_text('''[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
$element=[System.Windows.Automation.AutomationElement]::FocusedElement
@{name=$element.Current.Name;pid=$element.Current.ProcessId;type=$element.Current.ControlType.ProgrammaticName} | ConvertTo-Json -Compress
''', encoding='utf-8-sig')
        def focus():
            return json.loads(subprocess.check_output(['powershell','-NoProfile','-File',str(focus_script)],encoding='utf-8-sig',creationflags=0x08000000))
        initial = focus(); check('panel_focus_starts_on_selected_tab', initial['name'] == '已完成' and initial['pid'] == gui.pid)
        keys(panel, 9); time.sleep(.1); next_focus = focus()
        check('tab_moves_to_panel_control', next_focus['pid'] == gui.pid and next_focus['type'] == 'ControlType.Button' and next_focus['name'] != initial['name'])
        keys(panel, 27)
        wait_for(lambda: all(width <= 60 for _,_,width in windows(gui.pid)))
        check('escape_closes_panel', all(width <= 60 for _,_,width in windows(gui.pid)))
        check('escape_restores_editor_focus', u.GetForegroundWindow() == editor_hwnd)
finally:
    for process in (gui, editor):
        if process and process.poll() is None: process.terminate(); process.wait(timeout=5)
    u.SetForegroundWindow(foreground)
    u.SetCursorPos(cursor.x,cursor.y)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding='utf-8')
