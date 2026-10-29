import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--app', type=Path, required=True)
parser.add_argument('--codex', required=True)
args = parser.parse_args()
app = args.app.resolve()
with tempfile.TemporaryDirectory(prefix='rad-install-') as directory:
    root = Path(directory)
    home = root / '配置 home'; home.mkdir()
    instructions = home / 'AGENTS.md'
    original = '保留已有指令。\nDo not change unrelated configuration.\n'
    instructions.write_text(original, encoding='utf-8')
    data = root / 'data'
    env = dict(os.environ, RAD_DATA_DIR=str(data))
    def execute(script, *parameters):
        result=subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), *parameters],
                              env=env, capture_output=True, timeout=15, creationflags=0x08000000)
        if result.returncode:raise RuntimeError((result.stdout.decode('utf-8',errors='replace'),result.stderr.decode('utf-8',errors='replace')))
        return result
    try:
        execute(app / 'install.ps1', '-CodexHome', str(home), '-CodexExe', args.codex, '-Destination', str(app))
        first = json.loads((data / 'settings.json').read_text(encoding='utf-8'))['instances'][0]['id']
        execute(app / 'install.ps1', '-CodexHome', str(home) + os.sep, '-CodexExe', args.codex, '-Destination', str(app))
        text = instructions.read_text(encoding='utf-8')
        assert text.startswith(original)
        assert text.count('<!-- remind-at-done:start -->') == 1
        assert '主任务准备最终答复前' in text
        assert json.loads((data / 'settings.json').read_text(encoding='utf-8'))['instances'][0]['id'] == first
        assert not json.loads((data / 'settings.json').read_text(encoding='utf-8'))['login_startup']
        assert (home / 'skills/remind-at-done/installation.json').exists()
        print('PASS install/update: stable instance, one instruction block, Unicode preserved, startup off.')
    finally:
        execute(app / 'uninstall.ps1', '-CodexHome', str(home))
    assert original in instructions.read_text(encoding='utf-8')
    assert '<!-- remind-at-done:' not in instructions.read_text(encoding='utf-8')
    assert not (home / 'skills/remind-at-done').exists()
    assert (data / 'settings.json').exists()
    print('PASS uninstall: integration removed, prior instructions and data preserved.')
