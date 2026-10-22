"""Extract the task blocks without rewriting source text, tables or images.

Input conversion: bundled LibreOffice ATT83PL.rtf -> ATT83PL.docx.
Run with the bundled Python runtime. This does not author acceptance rules.
"""
from pathlib import Path
import hashlib
import json
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'tasks/1c-platform-official-sample'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
ET.register_namespace('w', W[1:-1])

def sha(data):
    return hashlib.sha256(data).hexdigest()

def text_of(element):
    return ''.join(x.text or '' for x in element.iter(W+'t'))

def main():
    original = ROOT / '.local/documents/ATT83PL.docx'
    with zipfile.ZipFile(original) as z:
        members = {name: z.read(name) for name in z.namelist()}
    document = ET.fromstring(members['word/document.xml'])
    body = document.find(W+'body')
    children = list(body)
    assert 'Примеры заданий:' in text_of(children[113])
    removed = list(range(113))
    for element in children[:113]:
        body.remove(element)
    # Only empty trailing paragraphs; preserve final section properties.
    for index in range(len(children)-2, 112, -1):
        element = children[index]
        if element.tag != W+'p' or text_of(element).strip() or list(element.iter(W+'drawing')) or list(element.iter(W+'pict')):
            break
        body.remove(element)
        removed.append(index)
    included = [(index, element) for index, element in enumerate(children) if index not in removed]
    fingerprints = [{'body_index': i, 'xml_sha256': sha(ET.tostring(e)), 'kind': e.tag.rsplit('}',1)[-1]} for i,e in included]
    members['word/document.xml'] = ET.tostring(document, encoding='utf-8', xml_declaration=True)
    public = TASK / 'public'
    public.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(public/'statement.docx','w',compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name,data)
    lines=[]
    for element in body:
        if element.tag == W+'tbl':
            lines.extend('\t'.join(text_of(cell) for cell in row.findall(W+'tc')) for row in element.findall(W+'tr'))
        elif element.tag == W+'p':
            lines.append(text_of(element))
    (public/'statement.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    assets=public/'assets'
    assets.mkdir(exist_ok=True)
    media=[(name,data) for name,data in members.items() if name.startswith('word/media/')]
    assert len(media)==3, media
    for i,(name,data) in enumerate(media,1):
        (assets/f'figure-{i}.png').write_bytes(data)
    private=TASK/'private'
    private.mkdir(exist_ok=True)
    outputs={str(p.relative_to(TASK)):sha(p.read_bytes()) for p in sorted(public.rglob('*')) if p.is_file()}
    source_map={
        'source_url':'https://static.1c.ru/rus/partners/training/files/ATT83PL.rtf?356jhteyner67j340',
        'retrieved_on':'2026-10-09',
        'source_sha256':sha((ROOT/'.local/sources/ATT83PL.rtf').read_bytes()),
        'source_text_sha256':sha((ROOT/'.local/sources/ATT83PL.txt').read_bytes()),
        'source_text_lines':[279,486],
        'conversion':'bundled LibreOffice; original tables and drawings retained',
        'converted_source_sha256':sha(original.read_bytes()),
        'removed_body_indices':sorted(removed),
        'removed_trailing_content':'empty paragraphs only; no task text removed',
        'retained_body_elements':fingerprints,
        'output_sha256':outputs,
        'qa_status':'requires_render_and_visual_check_after_regeneration',
        'table_count':len(body.findall(W+'tbl')),
        'figure_count':len(media),
        'statement_contains_only_source':True,
    }
    (private/'source-map.json').write_text(json.dumps(source_map,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'outputs':outputs,'retained_elements':len(included),'removed_trailing':len(removed)-113},ensure_ascii=False))

if __name__=='__main__':
    main()
