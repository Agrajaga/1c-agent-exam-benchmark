"""Independent adapter to the installed 1C platform, not a Unica verdict."""
import json
import os
import platform
import subprocess
import time
from pathlib import Path

from .common import digest, tree_manifest, utc, write_json


class PlatformError(RuntimeError):
    pass


def platform_argv(args):
    """1C's Windows connection-string parser expects doubled nested quotes.

    This is a CreateProcess command line, never a shell command. Keep normal
    arguments under Python's quoting rules; only CREATEINFOBASE's connection
    string uses the syntax documented by 1C.
    """
    if os.name == 'nt' and len(args)>2 and args[1]=='CREATEINFOBASE':
        return (subprocess.list2cmdline(args[:2])+' "'+args[2].replace('"','""')+'" '+
                subprocess.list2cmdline(args[3:]))
    return args


class OneC:
    def __init__(self, binary, evidence, timeout=180):
        self.binary = Path(binary).resolve()
        self.evidence = Path(evidence).resolve()
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.sequence = 0

    def command(self, argv, label, confined=None):
        """confined: case root; submitted code then runs without network, operator env or host files."""
        self.sequence += 1
        stem = self.evidence / f'{self.sequence:03}-{label}'
        log = stem.with_suffix('.platform.log')
        args = [str(self.binary), *map(str, argv), '/DisableStartupMessages', '/DisableStartupDialogs', '/Out', str(log)]
        started_at = utc()
        start = time.monotonic()
        import os
        from .process import supervise
        env=dict(os.environ)
        if confined is not None:
            from .isolation import grading_profile,grading_environment
            from .runtime import require_execution_mode
            Path(confined,'tmp').mkdir(parents=True,exist_ok=True)
            if require_execution_mode()=='macos':
                args=['/usr/bin/sandbox-exec','-f',str(grading_profile(confined,self.binary)),*args]
            elif require_execution_mode()=='bubblewrap':
                from .isolation import linux_wrapped
                args=linux_wrapped(args,confined,grading=True)
            env=grading_environment(confined)
        supervised=supervise(platform_argv(args),self.evidence,env,'',self.timeout,3,stem.with_suffix('.streams'))
        outcome={'exit_code':supervised['exit_code'] if supervised['status']!='timeout' else None,'status':supervised['status'],'stop_confirmed':supervised['stop_confirmed']}
        if not supervised['stop_confirmed']:outcome['exit_code']=None
        from .runtime import settings
        outcome.update(label=label, argv=args, confined=confined is not None and settings()['isolation'] in ('macos','bubblewrap'), started_at=started_at, elapsed_ms=round((time.monotonic()-start)*1000))
        write_json(stem.with_suffix('.json'), outcome)
        if outcome['exit_code'] != 0:
            raise PlatformError(f'{label}: platform failed; see {stem.name}.json')
        return outcome

    def create(self, infobase):
        infobase = Path(infobase).resolve()
        if infobase.exists():
            raise PlatformError('Refuse to create over an existing infobase')
        infobase.parent.mkdir(parents=True, exist_ok=True)
        self.command(['CREATEINFOBASE', f'File="{infobase}";'], 'create')
        if not infobase.is_dir():
            raise PlatformError('Platform returned success without creating an infobase')

    def restore(self, infobase, original):
        infobase, original = Path(infobase).resolve(), Path(original).resolve()
        if not original.is_file():
            raise PlatformError('Missing DT input')
        if not infobase.is_dir():
            self.create(infobase)
        self.command(['DESIGNER', '/F', infobase, '/RestoreIB', original], 'restore')

    def export(self, infobase, target):
        target = Path(target).resolve()
        if target.exists():
            raise PlatformError('Export requires an absent target directory')
        target.mkdir(parents=True)
        self.command(['DESIGNER', '/F', Path(infobase).resolve(), '/DumpConfigToFiles', target], 'export')
        if not (target/'Configuration.xml').is_file():
            raise PlatformError('Platform returned success without exported Configuration.xml')
        return tree_manifest(target)

    def load(self, infobase, source):
        self.command(['DESIGNER', '/F', Path(infobase).resolve(), '/LoadConfigFromFiles', Path(source).resolve(), '/UpdateDBCfg'], 'load-apply')

    def build_epf(self, infobase, source, target):
        self.command(['DESIGNER', '/F', Path(infobase).resolve(), '/LoadExternalDataProcessorOrReportFromFiles', Path(source).resolve(), Path(target).resolve()], 'build-epf')
        if not Path(target).is_file():
            raise PlatformError('No EPF produced')

    def execute(self, infobase, epf, startup_parameter=''):
        return self.command(['ENTERPRISE', '/F', Path(infobase).resolve(), '/Execute', Path(epf).resolve(), '/C', startup_parameter], 'enterprise')


def prepare_environment(binary, starter, root):
    from .runtime import machine_identity, require_execution_mode, platform_binary
    require_execution_mode()
    if str(Path(binary).resolve())!=platform_binary():
        raise ValueError('The prepare binary must match platform_binary in the machine settings')
    root = Path(root).resolve()
    if root.exists():
        raise PlatformError('Environment evidence directory must be new')
    root.mkdir(parents=True)
    adapter = OneC(binary, root/'evidence')
    passport = {'schema_version': 1, 'state': 'preparing', 'os': platform.platform(), 'architecture': platform.machine(), 'platform_binary': str(adapter.binary), 'platform_binary_sha256': digest(adapter.binary), 'starter_sha256': digest(starter), 'adapter': 'independent-platform-cli', 'unica_provider_required': False}
    passport['machine']=machine_identity()
    write_json(root/'passport.json', passport)
    try:
        for index in (1, 2):
            adapter.restore(root/f'ib-{index}', starter)
            adapter.export(root/f'ib-{index}', root/f'src-{index}')
        a, b = tree_manifest(root/'src-1'), tree_manifest(root/'src-2')
        # ConfigDumpInfo describes technical export versioning, not configuration content.
        a.pop('ConfigDumpInfo.xml', None); b.pop('ConfigDumpInfo.xml', None)
        if a != b:
            raise PlatformError('Independent exports differ')
        passport.update(state='configuration_verified', configuration_files=a, runtime_probe_verified=False, gui_verified=False, reset_verified=False)
    except PlatformError as exc:
        passport.update(state='infrastructure_error', reason=str(exc))
        write_json(root/'passport.json', passport)
        raise
    write_json(root/'passport.json', passport)
    return passport


def verify_runtime_and_reset(binary, starter, root):
    """Continue the prepared worker with a real application probe, persistence, reset and negative DT."""
    from .observer import inject,RUNTIME_PROBE
    root=Path(root).resolve()
    passport=json.loads((root/'passport.json').read_text(encoding='utf-8'))
    adapter=OneC(binary,root/'runtime-reset-evidence',90)
    def observe(source,index,infobase):
        injected=inject(source,root/f'probe-src-{index}',RUNTIME_PROBE)
        adapter.load(infobase,injected)
        output=root/f'probe-result-{index}.json'
        adapter.command(['ENTERPRISE','/F',infobase,'/C',output],'runtime-probe')
        data=json.loads(output.read_text(encoding='utf-8-sig'))
        if not data.get('read_after_write'):raise PlatformError('Real write/read probe failed')
        return data
    try:
        first=observe(root/'src-1',1,root/'ib-1')
        output=root/'persist-result.json'
        adapter.command(['ENTERPRISE','/F',root/'ib-1','/C',output],'persistence-probe')
        persisted=json.loads(output.read_text(encoding='utf-8-sig'))
        if not first.get('absent_before') or persisted.get('absent_before') or not persisted.get('read_after_write'):raise PlatformError('Persistence observation failed')
        second=observe(root/'src-2',2,root/'ib-2')
        if first!=second:raise PlatformError('Fresh database data probes differ')
        adapter.restore(root/'ib-1',starter)
        adapter.export(root/'ib-1',root/'reset-src')
        a,b=tree_manifest(root/'src-1'),tree_manifest(root/'reset-src')
        a.pop('ConfigDumpInfo.xml',None);b.pop('ConfigDumpInfo.xml',None)
        if a!=b:raise PlatformError('Reset changed source configuration')
        third=observe(root/'reset-src',3,root/'ib-1')
        if third!=first:raise PlatformError('Reset did not remove probe record')
        damaged=root/'invalid.dt';damaged.write_bytes(b'not-a-1c-infobase-dump')
        negative=False
        try:adapter.restore(root/'invalid-ib',damaged)
        except PlatformError:negative=True
        if not negative:raise PlatformError('Damaged input was accepted')
        passport.update(state='verified',runtime_probe_verified=True,reset_verified=True,negative_input_verified=True,gui_required=False,gui_verified=False,controlled_data_probe=first,source_comparison_ignored=['ConfigDumpInfo.xml'],process_boundary='native process group')
    except (PlatformError,OSError,ValueError) as exc:
        passport.update(state='infrastructure_error',reason=str(exc));write_json(root/'passport.json',passport);raise
    write_json(root/'passport.json',passport)
    return passport
