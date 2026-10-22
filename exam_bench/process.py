"""Bound process trees and stream evidence on Windows, Linux and macOS."""
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

_jobs = {}


def active_group(pgid):
    if os.name == 'nt':
        job = _jobs.get(pgid)
        return job.active() if job else False
    p = subprocess.run(['ps', '-axo', 'pgid=,stat='], capture_output=True, text=True, check=True)
    return any(len(parts := row.split()) >= 2 and parts[0] == str(pgid) and not parts[1].startswith('Z') for row in p.stdout.splitlines())


def stop_group(pgid, grace):
    if not active_group(pgid):
        return True
    if os.name == 'nt':
        _jobs[pgid].terminate()
    else:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return True
    deadline = time.monotonic() + grace
    while active_group(pgid) and time.monotonic() < deadline:
        time.sleep(.02)
    if os.name != 'nt' and active_group(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 1
    while active_group(pgid) and time.monotonic() < deadline:
        time.sleep(.02)
    return not active_group(pgid)


def supervise(argv, cwd, env, prompt, timeout, grace, evidence):
    evidence = Path(evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    options = {'creationflags': 0x4 | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
    job = None
    try:
        if os.name == 'nt':
            from .windows_job import Job
            job = Job(process)
            _jobs[process.pid] = job
        return _observe(process, prompt, timeout, grace, evidence, start)
    except BaseException:
        if os.name == 'nt' and job is None:
            process.kill()
        else:
            stop_group(process.pid, grace)
        process.wait(timeout=grace + 2)
        raise
    finally:
        if job:
            job.close(); _jobs.pop(process.pid, None)
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


def _observe(process, prompt, timeout, grace, evidence, start):
    # Windows selectors cannot select pipes. Concurrent input also prevents a
    # client that does not read stdin from bypassing the solve deadline.
    chunks = queue.Queue(maxsize=128)
    def read(stream, name):
        try:
            while chunk := stream.read1(65536):
                chunks.put((name, chunk))
        finally:
            chunks.put((name, None))
    def write():
        try:
            process.stdin.write(prompt.encode('utf-8')); process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()
    readers = [threading.Thread(target=read, args=(stream, name), daemon=True)
               for stream, name in ((process.stdout, 'out'), (process.stderr, 'err'))]
    for thread in readers:
        thread.start()
    writer = threading.Thread(target=write, daemon=True); writer.start()
    status = None; root_finished_at = None; open_streams = 2
    with (evidence/'stdout.jsonl').open('wb') as out, (evidence/'stderr.log').open('wb') as err:
        while open_streams or process.poll() is None:
            if time.monotonic() - start >= timeout and process.poll() is None and status is None:
                status = 'timeout'
                if not stop_group(process.pid, grace):
                    raise RuntimeError('Cannot confirm termination of the supervised process tree')
            try:
                name, chunk = chunks.get(timeout=.02)
                if chunk is None:
                    open_streams -= 1
                else:
                    target = out if name == 'out' else err
                    target.write(chunk); target.flush()
            except queue.Empty:
                pass
            if process.poll() is not None and root_finished_at is None:
                root_finished_at = time.monotonic(); stop_group(process.pid, grace)
            if root_finished_at is not None and time.monotonic()-root_finished_at >= grace+1 and chunks.empty():
                break
    if process.poll() is None:
        status = status or 'timeout'; stop_group(process.pid, grace)
    code = process.wait(timeout=grace+2)
    for thread in readers + [writer]:
        thread.join(timeout=1)
    stopped = stop_group(process.pid, grace)
    return {'status': status or ('completed' if code == 0 else 'client_error'), 'exit_code': code,
            'pid': process.pid, 'elapsed_ms': round((time.monotonic()-start)*1000), 'stop_confirmed': stopped}
