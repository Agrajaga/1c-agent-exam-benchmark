"""Extract open guidance without regenerating the visually verified statement."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bench.common import digest, write_json
from exam_bench.materials import (INPUT_REVISION, METHODS_REF, POLICY_REF,
                                 SOURCE_SHA256, SOURCE_TEXT_SHA256,
                                 extract_methods, render_methods, render_policy)


def main():
    task = ROOT / 'tasks/1c-platform-official-sample'
    source = ROOT / '.local/sources/ATT83PL.txt'
    artifact = ROOT / '.local/sources/ATT83PL.rtf'
    if digest(artifact) != SOURCE_SHA256 or digest(source) != SOURCE_TEXT_SHA256:
        raise ValueError('Official acquisition differs from the verified source')
    policy_path = task / 'private/owner-scoring-policy.json'
    execution_path = ROOT / 'profiles/ai-exam-execution-policy.json'
    policy = json.loads(policy_path.read_text())
    execution = json.loads(execution_path.read_text())
    manifest = json.loads((task / 'manifest.json').read_text())
    original_statement = digest(task / 'public/statement.docx')
    (task / METHODS_REF).write_text(render_methods(ROOT / '.local/documents/ATT83PL.docx', source.read_text()), encoding='utf-8')
    (task / POLICY_REF).write_text(render_policy(policy, execution), encoding='utf-8')
    hashes = {ref: digest(task / ref) for ref in (METHODS_REF, POLICY_REF)}
    manifest['public'].update(input_revision=INPUT_REVISION,
                              methodical_requirements_ref=METHODS_REF,
                              assessment_policy_ref=POLICY_REF,
                              guidance_sha256=hashes)
    write_json(task / 'manifest.json', manifest)
    write_json(task / 'private/methodical-source-map.json', {
        'schema_version': 1, 'input_revision': INPUT_REVISION,
        'source_url': manifest['source']['artifact_url'],
        'source_sha256': SOURCE_SHA256, 'source_text_sha256': SOURCE_TEXT_SHA256,
        'source_text_lines': [1, 278], 'extraction': 'Preface before Примеры заданий: from the Word document; tables drawn with ASCII borders; same words as the official text',
        'owner_policy_sha256': digest(policy_path),
        'execution_policy_sha256': digest(execution_path), 'output_sha256': hashes,
        'historical_runs_rewritten': False,
    })
    if digest(task / 'public/statement.docx') != original_statement:
        raise ValueError('Clean statement was changed')
    print('Open exam guidance prepared: ' + INPUT_REVISION + '; clean statement unchanged')


if __name__ == '__main__':
    main()
