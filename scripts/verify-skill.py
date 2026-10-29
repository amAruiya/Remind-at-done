"""Exercise the skill's deterministic eligibility helper; not proof of agent invocation rate."""
import datetime as dt
import json
from pathlib import Path
import subprocess

helper = Path(__file__).resolve().parents[1] / 'skills/remind-at-done/scripts/check-completion.ps1'
start = dt.datetime(2026, 10, 29, 0, tzinfo=dt.timezone.utc)

def decide(seconds=301, state='completed', root=True, begin=None):
    command = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper),
               '-StartedAt', begin or start.isoformat(), '-CompletedAt', (start + dt.timedelta(seconds=seconds)).isoformat(), '-State', state]
    if root:
        command.append('-RootTask')
    return json.loads(subprocess.check_output(command, text=True, encoding='utf-8', creationflags=0x08000000))

for seconds, eligible in [(299, False), (300, False), (300.001, True), (301, True)]:
    assert decide(seconds)['eligible'] is eligible, seconds
for state in ['waiting', 'paused', 'failed', 'in_progress']:
    assert not decide(600, state)['eligible'], state
assert not decide(root=False)['eligible']
assert not decide(-1)['eligible']
assert not decide(begin='2026-10-29T00:00:00')['eligible']
assert not decide(begin='unknown')['eligible']
print('12 eligibility checks passed: exact threshold, incomplete states, child, reversed/missing timezone.')
