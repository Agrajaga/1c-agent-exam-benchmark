"""Bounded stdio MCP client for local harness checks; never contacts an LLM."""
import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path


class Client:
    def __init__(self, command, args, cwd, env, log):
        self.log = Path(log)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.errors = self.log.open('wb')
        options = {'creationflags': 0x4 | subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        self.process = subprocess.Popen([command, *args], cwd=cwd, env=env, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=self.errors, **options)
        self.job = None
        if os.name == 'nt':
            from exam_bench.windows_job import Job
            try:
                self.job = Job(self.process)
            except BaseException:
                self.process.kill(); self.process.wait(); self.errors.close(); raise
        self.lines = queue.Queue()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        self.counter = 0
        self.transcript = []

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def send(self, payload):
        self.process.stdin.write((json.dumps(payload) + '\n').encode())
        self.process.stdin.flush()

    def request(self, method, params=None, timeout=60):
        self.counter += 1
        self.send({'jsonrpc': '2.0', 'id': self.counter, 'method': method, 'params': params or {}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                raise RuntimeError('MCP process closed its output; see ' + str(self.log))
            try:
                value = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            self.transcript.append(value)
            if value.get('id') == self.counter:
                if value.get('error'):
                    raise RuntimeError('MCP error: ' + json.dumps(value['error']))
                return value['result']
        raise TimeoutError('MCP request timed out: ' + method)

    def initialize(self, timeout=60):
        result = self.request('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                             'clientInfo': {'name': 'exam-bench-native-probe', 'version': '1'}}, timeout=timeout)
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return result

    def close(self):
        if self.job:
            self.job.terminate()
        elif self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGTERM)
        if self.process.poll() is None:
            self.process.wait(timeout=5)
        if self.job:
            deadline = time.monotonic() + 5
            while self.job.active() and time.monotonic() < deadline:
                time.sleep(.05)
            self.job.close()
        self.process.stdin.close(); self.process.stdout.close(); self.errors.close()
        self.thread.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
