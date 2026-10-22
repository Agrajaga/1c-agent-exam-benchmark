"""Start the local demo server once, wait for readiness, then open its page."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:8879/'


def available():
    try:
        with urllib.request.urlopen(URL + 'api/demo', timeout=2) as response:
            return 'enabled' in json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return False


def main():
    if sys.version_info < (3, 11):
        raise SystemExit('Python 3.11+ is required: https://www.python.org/downloads/')
    (ROOT / '.local').mkdir(exist_ok=True)
    if not available():
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        with (ROOT / '.local/site-demo.stdout.log').open('ab') as out, (ROOT / '.local/site-demo.stderr.log').open('ab') as err:
            process = subprocess.Popen([sys.executable, '-X', 'utf8', str(ROOT / 'tools/serve_result_site.py'), '--catalogue-only'],
                                       cwd=ROOT, stdout=out, stderr=err, **options)
        (ROOT / '.local/site.pid').write_text(str(process.pid), encoding='ascii')
        for _ in range(40):
            if available():
                break
            if process.poll() is not None:
                raise SystemExit('Server did not start; see .local/site-demo.stderr.log')
            time.sleep(.25)
        else:
            raise SystemExit('Server readiness timed out; see .local/site-demo.stderr.log')
    webbrowser.open(URL)
    print('Demo: ' + URL)
    print('The server continues running after this window closes.')


if __name__ == '__main__':
    main()
