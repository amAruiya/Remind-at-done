"""Archive a published self-contained directory and verify every archived file."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import zipfile

parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--source-revision')
args=parser.parse_args();app=args.app.resolve();root=args.out.resolve();root.mkdir(parents=True,exist_ok=True);(root/'info').mkdir(exist_ok=True)
for required in ['RemindAtDone.exe','rad.exe','resume-thread.ps1','install.ps1','uninstall.ps1','skills/remind-at-done/SKILL.md','coreclr.dll','PresentationFramework.dll']:
    if not (app/required).is_file():raise SystemExit('Missing release file: '+required)
files=sorted(path for path in app.rglob('*') if path.is_file())
for path in files:
    if path.name in ('settings.json','history.json','installation.json'):
        raise SystemExit('Machine-specific data must not be distributed: '+str(path))
archive=root/'RemindAtDone-0.1.0-preview-win-x64.zip'
checksums={}
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
    for path in files:
        relative='RemindAtDone/'+path.relative_to(app).as_posix()
        content=path.read_bytes();checksums[relative]=hashlib.sha256(content).hexdigest();bundle.writestr(relative,content)
with zipfile.ZipFile(archive) as bundle:
    if bundle.testzip() is not None:raise SystemExit('Archive CRC validation failed')
    for name,checksum in checksums.items():
        if hashlib.sha256(bundle.read(name)).hexdigest()!=checksum:raise SystemExit('Archive contents differ: '+name)
result={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'status':'preview_pending_remaining_acceptance',
        'source_revision':args.source_revision,
        'sdk':'10.0.403','tested_codex':'0.165.0','file_count':len(files),
        'uncompressed_bytes':sum(path.stat().st_size for path in files),'archive_bytes':archive.stat().st_size,
        'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':checksums}
(root/'info/package.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({key:value for key,value in result.items() if key!='files'}))
