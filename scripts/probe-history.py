"""Verify timestamp/lineage fields of existing threads without saving conversation bodies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy

Proxy = runpy.run_path(str(Path(__file__).with_name('probe-daemon.py')))['Proxy']
parser = argparse.ArgumentParser()
parser.add_argument('--codex', required=True)
parser.add_argument('--out', required=True, type=Path)
args = parser.parse_args()
proxy = Proxy(args.codex)
result = {'main': [], 'child_count': 0, 'loaded_count': 0}
try:
    cursor = None
    ids = []
    while True:
        page = proxy.call('thread/loaded/list', {'cursor': cursor, 'limit': 5})
        ids.extend(page['data'])
        cursor = page['nextCursor']
        if not cursor:
            break
    result['loaded_count'] = len(ids)
    for thread_id in ids:
        thread = proxy.call('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']
        child = bool(thread.get('parentThreadId')) or isinstance(thread.get('source'), dict) and 'subAgent' in thread['source']
        if child:
            result['child_count'] += 1
            continue
        if os.path.normcase(thread['cwd']) != os.path.normcase(os.getcwd()):
            continue
        turns = proxy.call('thread/turns/list', {'threadId': thread_id, 'limit': 20, 'itemsView': 'summary'})
        evidence = {'thread_hash': hashlib.sha256(thread_id.encode()).hexdigest()[:12], 'source': thread['source'],
                    'status': thread['status'], 'turns': [{'id_hash': hashlib.sha256(t['id'].encode()).hexdigest()[:12],
                        'started_at': t.get('startedAt'), 'status': t['status'], 'item_types': [i['type'] for i in t['items']]}
                        for t in turns['data']], 'has_more_turns': bool(turns.get('nextCursor'))}
        if turns['data']:
            items = proxy.call('thread/items/list', {'threadId': thread_id, 'turnId': turns['data'][0]['id'], 'limit': 5})
            evidence['first_items_shape'] = [{'keys': list(i), 'type': i['item'].get('type'), 'started_at_ms': i.get('startedAtMs')} for i in items['data']]
        result['main'].append(evidence)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
finally:
    proxy.close()
