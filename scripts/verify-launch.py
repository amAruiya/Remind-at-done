"""Test the actual PowerShell 5.1 resume helper against an argv-capturing executable."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--capture-exe', required=True, type=Path)
args = parser.parse_args()
helper = Path(__file__).resolve().with_name('resume-thread.ps1')
with tempfile.TemporaryDirectory(prefix='rad-launch-') as temp:
    root = Path(temp)
    cwd = root / "中文 空格 ; & ' $() ` 目录"
    cwd.mkdir()
    codex_home = root / '实例 home'
    codex_home.mkdir()
    captured = root / 'argv.json'
    identity = '00000000-0000-0000-0000-000000000123'
    capsule = base64.b64encode(json.dumps({'executable': str(args.capture_exe.resolve()),
        'codex_home': str(codex_home), 'thread_id': identity, 'cwd': str(cwd) + os.sep}, ensure_ascii=False).encode()).decode()
    env = dict(os.environ, RAD_ARGV_RECORD=str(captured),NO_COLOR='1',TERM='dumb',COLORTERM='')
    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper), '-Capsule', capsule],
                   env=env, check=True, timeout=10, creationflags=0x08000000)
    actual = json.loads(captured.read_text(encoding='utf-8'))
    assert actual['args'] == ['resume', identity, '--cd', str(cwd)], actual
    assert actual['cwd'] == str(cwd), actual
    assert actual['codex_home'] == str(codex_home), actual
    assert actual['no_color'] is None and actual['term'] is None and actual['colorterm'] is None, actual
    print('PASS: PS5.1 exact UUID, cwd, CODEX_HOME, Unicode and shell metacharacters; no prompt/fork/last.')
    print('PASS: tool-only NO_COLOR / TERM=dumb are removed for interactive Codex.')
    env.update(TERM='xterm-256color',COLORTERM='truecolor')
    subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(helper),'-Capsule',capsule],env=env,check=True,timeout=10,creationflags=0x08000000)
    actual=json.loads(captured.read_text(encoding='utf-8'))
    assert actual['term']=='xterm-256color' and actual['colorterm']=='truecolor' and actual['no_color'] is None
    print('PASS: valid terminal color capabilities are preserved.')
