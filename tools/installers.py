"""Bring a fresh machine to the point where an exam can start.

Missing tools are installed through the OS package manager (winget, Homebrew) or npm,
never by downloading and running an installer script. Logins use the tools' own device
flows: the page shows the link and one-time code, the user confirms in the browser.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
CODE = re.compile(r'\b([A-Z0-9]{4}-[A-Z0-9]{4,5})\b')
URL = re.compile(r'https://[^\s\x1b]+')
PACKAGES = {
    'gh': {'label': 'GitHub CLI', 'winget': 'GitHub.cli', 'brew': 'gh', 'page': 'https://cli.github.com',
           'manual': 'sudo apt install gh  (или инструкция на cli.github.com)'},
    'git': {'label': 'Git', 'winget': 'Git.Git', 'brew': 'git', 'page': 'https://git-scm.com/downloads',
            'manual': 'sudo apt install git'},
    'node': {'label': 'Node.js', 'winget': 'OpenJS.NodeJS.LTS', 'brew': 'node', 'page': 'https://nodejs.org',
             'manual': 'sudo apt install nodejs npm'},
    'codex': {'label': 'Codex CLI', 'npm': '@openai/codex', 'page': 'https://github.com/openai/codex'},
}
CLAUDE_INSTALL = ('irm https://claude.ai/install.ps1 | iex' if os.name == 'nt'
                  else 'curl -fsSL https://claude.ai/install.sh | bash')
_processes = {}


def _first(paths):
    for path in paths:
        if path and Path(path).is_file():
            return str(Path(path).resolve())
    return None


def _program_files(*parts):
    return [Path(os.environ[k], *parts) for k in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)') if os.environ.get(k)]


def _brew_bin(name):
    return [Path('/opt/homebrew/bin', name), Path('/usr/local/bin', name)]


def find(tool):
    """Path to an installed tool, including standard locations missing from this server's PATH."""
    nt = os.name == 'nt'
    candidates = {
        'gh': _program_files('GitHub CLI', 'gh.exe') if nt else _brew_bin('gh'),
        'git': _program_files('Git', 'cmd', 'git.exe') if nt else _brew_bin('git') + [Path('/usr/bin/git')],
        'node': _program_files('nodejs', 'node.exe') if nt else _brew_bin('node'),
        'npm': _program_files('nodejs', 'npm.cmd') if nt else _brew_bin('npm'),
        'claude': [Path.home() / '.local/bin' / ('claude.exe' if nt else 'claude')],
        'winget': [Path(os.environ.get('LOCALAPPDATA', ''), 'Microsoft/WindowsApps/winget.exe')] if nt else [],
        'brew': [] if nt else _brew_bin('brew'),
    }.get(tool, [])
    which = shutil.which(tool + ('.cmd' if nt and tool == 'npm' else ''))
    return _first([which, *candidates])


def npm_global_roots():
    if os.name == 'nt':
        return [Path(os.environ.get('APPDATA', ''), 'npm/node_modules'), *_program_files('nodejs', 'node_modules')]
    return [Path('/opt/homebrew/lib/node_modules'), Path('/usr/local/lib/node_modules'), Path('/usr/lib/node_modules'),
            Path.home() / '.npm-global/lib/node_modules']


def npm_codex():
    """The native Codex binary inside an npm installation (the bin shim needs Node on PATH)."""
    name = 'codex.exe' if os.name == 'nt' else 'codex'
    return [str(p.resolve()) for root in npm_global_roots() for p in sorted(root.glob('@openai/codex/vendor/*/codex/' + name)) if p.is_file()]


def package_manager():
    if os.name == 'nt':
        return 'winget' if find('winget') else None
    if sys.platform == 'darwin':
        return 'brew' if find('brew') else None
    return None


def install_command(tool):
    spec = PACKAGES[tool]
    if 'npm' in spec:
        npm = find('npm')
        return [npm, 'install', '-g', spec['npm']] if npm else None
    manager = package_manager()
    if manager == 'winget':
        return [find('winget'), 'install', '--id', spec['winget'], '-e', '--source', 'winget', '--silent',
                '--accept-source-agreements', '--accept-package-agreements']
    if manager == 'brew':
        return [find('brew'), 'install', spec['brew']]
    return None


def manual_hint(tool):
    spec = PACKAGES[tool]
    if 'npm' in spec:
        return f'Нужен Node.js. Затем в терминале: npm install -g {spec["npm"]}'
    if os.name == 'nt':
        return (f'Установите {spec["label"]} с {spec["page"]} или командой winget install --id {spec["winget"]}. '
                f'Затем проверьте в терминале: {tool} --version')
    if sys.platform == 'darwin':
        return f'Установите Homebrew (brew.sh), затем в терминале: brew install {spec["brew"]}'
    return 'В терминале: ' + spec['manual']


def login_command(kind, client=None):
    if kind == 'gh-login':
        return [find('gh'), 'auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web', '--skip-ssh-key']
    if kind == 'codex-login':
        return [client, 'login', '--device-auth']
    raise ValueError('Unknown login')


def _state_path(root):
    return root / '.local/community/helper.json'


def helper(root=ROOT):
    """The current or last install/login helper with the link and code it printed."""
    path = _state_path(root)
    if not path.is_file():
        return None
    state = json.loads(path.read_text(encoding='utf-8'))
    process = _processes.get(state['kind'])
    if state.get('returncode') is None:
        if process is not None and process.pid == state['pid']:
            code = process.poll()
        else:
            from tools.demo_runner import alive
            code = None if alive(state['pid']) else -1  # a server restart loses the exit code
        if code is not None:
            state['returncode'] = code
            path.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    log = Path(state['log'])
    text = ANSI.sub('', log.read_text(encoding='utf-8', errors='replace')) if log.is_file() else ''
    codes, urls = CODE.findall(text), URL.findall(text)
    return {**state, 'running': state.get('returncode') is None, 'code': codes[-1] if codes else None,
            'url': urls[0].rstrip('.,)') if urls else None, 'tail': text.strip().splitlines()[-1:] if text.strip() else []}


def start(kind, argv, root=ROOT):
    """One helper at a time; output goes to a log the page reads for the link and code."""
    current = helper(root)
    if current and current['running']:
        raise RuntimeError('Дождитесь завершения: ' + current['kind'])
    if not argv or not argv[0]:
        raise ValueError('Команда недоступна на этом компьютере')
    log = root / '.local/community' / (kind + '.log')
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    extra = [str(Path(p).parent) for p in (find('node'), find('git'), find('gh')) if p]
    env['PATH'] = os.pathsep.join(extra + [env.get('PATH', '')])
    env['NO_COLOR'] = '1'
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    with log.open('wb') as stream:
        process = subprocess.Popen([str(a) for a in argv], stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, env=env, **options)
    _processes[kind] = process
    _state_path(root).write_text(json.dumps({'kind': kind, 'pid': process.pid, 'log': str(log), 'started': time.time(),
                                             'returncode': None}, ensure_ascii=False), encoding='utf-8')
    return {'started': True}
