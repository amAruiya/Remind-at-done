"""Read-only protocol probe. Outputs metadata, never message bodies or credentials."""
import argparse
import json
import os
import queue
import subprocess
import threading
import websocket


class PipeSocket:
    def __init__(self, process):
        self.process = process
    def send(self, data):
        self.process.stdin.write(data)
        self.process.stdin.flush()
        return len(data)
    def recv(self, size):
        return os.read(self.process.stdout.fileno(), size)
    def settimeout(self, value):
        pass
    def gettimeout(self):
        return 15
    def close(self):
        self.process.kill()


class Proxy:
    def __init__(self, executable):
        self.process = subprocess.Popen([executable, 'app-server', 'proxy'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=None, creationflags=0x08000000)
        self.socket = websocket.WebSocket()
        self.socket.connect('ws://localhost/', socket=PipeSocket(self.process))
        self.messages = queue.Queue()
        self.sequence = 0
        threading.Thread(target=self._read, daemon=True).start()
        self.call('initialize', {'clientInfo': {'name': 'remind_at_done_probe', 'version': '0.1.0'},
                                 'capabilities': {'experimentalApi': True}})
        self.send({'method': 'initialized'})

    def _read(self):
        while True:
            try:
                self.messages.put(json.loads(self.socket.recv()))
            except Exception:
                return

    def send(self, payload):
        self.socket.send(json.dumps(payload))

    def call(self, method, params):
        self.sequence += 1
        self.send({'id': self.sequence, 'method': method, 'params': params})
        while True:
            response = self.messages.get(timeout=15)
            if response.get('id') == self.sequence:
                if 'error' in response:
                    raise RuntimeError(response['error'])
                return response['result']

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()  # Only our short-lived proxy, never the daemon.


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--codex', required=True)
    args = parser.parse_args()
    proxy = Proxy(args.codex)
    try:
        current = os.environ['CODEX_THREAD_ID']
        loaded = proxy.call('thread/loaded/list', {})
        print(json.dumps({'loaded': loaded}, ensure_ascii=False))
        thread = proxy.call('thread/read', {'threadId': current, 'includeTurns': False})
        metadata = thread.get('thread', thread)
        print(json.dumps({'thread_metadata': {k: v for k, v in metadata.items()
              if k not in ('turns', 'preview')}}, ensure_ascii=False))
        turns = proxy.call('thread/turns/list', {'threadId': current, 'limit': 5})
        print(json.dumps({'turn_shape': {k: ([{a: b for a, b in t.items() if a != 'items'}
              for t in v] if isinstance(v, list) else v) for k, v in turns.items()}}, ensure_ascii=False))
    finally:
        proxy.close()
