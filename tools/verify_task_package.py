"""Check the design package and numeric oracles. Does not test a 1C solution."""
from collections import Counter
from decimal import Decimal as D
from pathlib import Path
import hashlib
import json
import zipfile
import xml.etree.ElementTree as ET
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bench.materials import (METHODS_REF, POLICY_REF, SOURCE_SHA256,
                                 SOURCE_TEXT_SHA256, delivery_metadata,
                                 extract_methods, render_policy)
TASK = ROOT / 'tasks/1c-platform-official-sample'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
ET.register_namespace('w', W[1:-1])

def read(name):
    return json.loads((TASK/name).read_text(encoding='utf-8'))

def check(condition, message):
    if not condition:
        raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    manifest=read('manifest.json')
    profile=read('private/rules.json')
    rules=profile['rules']
    clauses=read('private/obligations.json')['clauses']
    cases=read('private/fixtures.json')['fixtures']
    questions=read('private/questions.json')['questions']
    source=read('private/source-map.json')
    for records in (rules,clauses,cases,questions):
        check(len({x['id'] for x in records})==len(records),'duplicate identifier')
    case_ids={c['id'] for c in cases}
    question_ids={q['id'] for q in questions}
    clause_map={c['id']:c for c in clauses}
    referenced=set()
    for r in rules:
        check(r['clause_id'] in clause_map,f'{r["id"]}: missing clause')
        check(clause_map[r['clause_id']]['rules']==[r['id']],'clause link mismatch')
        check(r['fixtures'] and set(r['fixtures'])<=case_ids,'missing fixture')
        referenced.update(r['fixtures'])
        check(set(r['blocked_by'])<=question_ids,'missing question')
        check(bool(r['blocked_by'])==(r['status']=='partial_specification'),'incorrect status')
        check(r['oracle'] and r['mandatory'] and r['methods'],'incomplete rule')
        check(r['implementation']=='not_implemented' and r['execution']=='not_run','unexpected implementation claim')
        for a,b in r['source']['lines']:
            check(279<=a<=b<=486,'locator outside task')
    check(referenced==case_ids,'unreferenced fixture')
    for q in questions:
        check(set(q['rules'])=={r['id'] for r in rules if q['id'] in r['blocked_by']},'question links mismatch')
    check(manifest['ready'] is False and manifest['evaluation']['coverage_verified'] is False,'premature ready')
    check(manifest['public']['statement_sha256']==source['output_sha256']['public/statement.docx'],'manifest hash differs')
    check(manifest['public']['text_sha256']==source['output_sha256']['public/statement.txt'],'manifest text hash differs')
    check(manifest['evaluation']['profile_id']==profile['profile_id'],'profile differs')
    expected_public={'public/statement.docx','public/statement.txt',*[f'public/assets/figure-{i}.png' for i in (1,2,3)]}
    delivery_metadata(TASK)
    expected_public.update((METHODS_REF, POLICY_REF))
    methods_source=read('private/methodical-source-map.json')
    check(methods_source['source_sha256']==SOURCE_SHA256,'methodical source identity differs')
    check(methods_source['source_text_sha256']==SOURCE_TEXT_SHA256,'methodical text identity differs')
    check(methods_source['source_text_lines']==[1,278],'methodical source interval differs')
    check(methods_source['output_sha256']==manifest['public']['guidance_sha256'],'methodical output map differs')
    check(methods_source['owner_policy_sha256']==sha((TASK/'private/owner-scoring-policy.json').read_bytes()),'owner policy changed since disclosure')
    execution_path=ROOT/'profiles/ai-exam-execution-policy.json'
    check(methods_source['execution_policy_sha256']==sha(execution_path.read_bytes()),'execution policy changed since disclosure')
    check((TASK/POLICY_REF).read_text()==render_policy(read('private/owner-scoring-policy.json'),json.loads(execution_path.read_text())),'public policy differs from owner decisions')
    official_text=ROOT/'sources/1c/ATT83PL.txt'
    if official_text.exists():
        check((TASK/METHODS_REF).read_text()==extract_methods(official_text.read_text()),'methodical preface rewritten or includes example')
    for key,allowed in [('protocol_ref','public/protocol.md'),('binding_contract_ref','public/binding-contract.json')]:
        declared=manifest['public'].get(key)
        if declared is not None:
            check(declared==allowed, f'Unexpected public protocol reference: {declared}')
            expected_public.add(declared)
    actual_public={str(p.relative_to(TASK)) for p in (TASK/'public').rglob('*') if p.is_file()}
    check(actual_public==expected_public,'unexpected file in agent statement')
    for path,digest in source['output_sha256'].items():
        check(sha((TASK/path).read_bytes())==digest,f'hash mismatch: {path}')
    check(source['qa_status']=='visually_verified' and source['qa_pages']==4,'missing visual QA')
    with zipfile.ZipFile(TASK/'public/statement.docx') as z:
        body=ET.fromstring(z.read('word/document.xml')).find(W+'body')
        check(len(body)==len(source['retained_body_elements']),'source element count differs')
        check(len(body.findall(W+'tbl'))==source['table_count'],'table count differs')
        check(len([n for n in z.namelist() if n.startswith('word/media/')])==3,'missing figure')
        for element,record in zip(body,source['retained_body_elements']):
            check(sha(ET.tostring(element))==record['xml_sha256'],'retained source element rewritten')
    # Official acquisition files are versioned; always verify their identity.
    for name,key in [('ATT83PL.rtf','source_sha256'),('ATT83PL.txt','source_text_sha256')]:
        p=ROOT/'sources/1c'/name
        check(sha(p.read_bytes())==source[key],'source hash differs')
    converted=ROOT/'.local/documents/ATT83PL.docx'
    if converted.exists():
        check(sha(converted.read_bytes())==source['converted_source_sha256'],'converted source changed')
        with zipfile.ZipFile(converted) as z:
            original=ET.fromstring(z.read('word/document.xml')).find(W+'body')
            for r in source['retained_body_elements']:
                check(sha(ET.tostring(original[r['body_index']]))==r['xml_sha256'],'source map differs from original')
    fixture={c['id']:c for c in cases}
    comparisons=0
    def inputs(fid):
        return fixture[fid]['arithmetic_inputs']
    def expected(fid):
        return fixture[fid]['expected']
    def eq(actual,want,label):
        nonlocal comparisons
        check(D(actual)==D(want),f'{label}: {actual} != {want}')
        comparisons+=1
    def scalar(fid,key,value): eq(value,expected(fid)[key],fid+'.'+key)
    x=inputs('OU-POLICIES')
    batches=[(D(b['qty']),D(b['price'])) for b in x['receipts']]
    quantity=sum(q for q,p in batches)
    amount=sum(q*p for q,p in batches)
    sold=D(x['sale_qty'])
    for policy,order in [('F',batches),('L',batches[::-1]),('M',None)]:
        if order is None: cost=amount/quantity*sold
        else:
            remaining=sold;cost=D(0)
            for qty,price in order:
                take=min(remaining,qty);cost+=take*price;remaining-=take
            check(remaining==0,'insufficient FIFO fixture')
        e=expected('OU-POLICIES')[policy]
        for k,v in {'expense_qty':sold,'expense_amount':cost,'closing_qty':quantity-sold,'closing_amount':amount-cost}.items():eq(v,e[k],policy+'.'+k)
    x={k:D(v) for k,v in inputs('OU-ASSEMBLY').items()}
    a=x['blocks']*x['spec_A']+x['extra_A'];b=x['blocks']*x['spec_B']
    for k,v in dict(consumed_A_P1=a,consumed_B_Q1=b,cost_A_P1=a*x['price_A'],cost_B_Q1=b*x['price_B'],consumed_cost=a*x['price_A']+b*x['price_B'],produced_K_D=x['blocks'],closing_A_P1_S=x['opening_A']-a,closing_B_Q1_S=x['opening_B']-b).items():scalar('OU-ASSEMBLY',k,v)
    duplicate=fixture['OU-ASSEMBLY']['expected_duplicate_extra_variant']
    a2=x['blocks']*x['spec_A']+sum(map(D,duplicate['extra_rows']))
    for k,v in dict(consumed_A_P1=a2,cost_A_P1=a2*x['price_A'],consumed_B_Q1=b,consumed_cost=a2*x['price_A']+b*x['price_B']).items():eq(v,duplicate[k],'OU-ASSEMBLY.duplicate.'+k)
    x={k:D(v) for k,v in inputs('BU-MANUAL').items()}
    qty=x['receipt_qty']+x['manual_qty'];amount=x['receipt_amount']+x['manual_amount'];cost=amount/qty*x['sale_qty']
    for k,v in dict(available_qty=qty,available_amount=amount,expense_qty=x['sale_qty'],expense_amount=cost,closing_qty=qty-x['sale_qty'],closing_amount=amount-cost).items():scalar('BU-MANUAL',k,v)
    x={k:D(v) for k,v in inputs('BU-AVERAGE').items()}
    qty=x['W1_qty']+x['W2_qty'];amount=x['W1_amount']+x['W2_amount'];average=amount/qty;cost=average*x['sale_qty'];revenue=x['sale_qty']*x['sale_price']
    for k,v in dict(global_qty=qty,global_amount=amount,average=average,sale_cost=cost,sale_revenue=revenue,sale_profit=revenue-cost,after_W1_qty=x['W1_qty']-x['sale_qty'],after_W2_qty=x['W2_qty'],after_global_amount=amount-cost).items():scalar('BU-AVERAGE',k,v)
    x={k:D(v) for k,v in inputs('BU-REPORT').items()};detail=[]
    for item in ('A','C'):
        qty=x[item+'_qty'];cost=qty*x[item+'_price'];revenue=qty*x['sale_price'];values={'qty':qty,'cost':cost,'revenue':revenue,'profit':revenue-cost};detail.append(values)
        for k,v in values.items():eq(v,expected('BU-REPORT')[item+'_detail'][k],'BU-REPORT.'+item+'.'+k)
    for k in detail[0]:eq(sum(v[k] for v in detail),expected('BU-REPORT')['A_group'][k],'BU-REPORT.group.'+k)
    x={k:D(v) for k,v in inputs('OU-REPORT').items()};e=expected('OU-REPORT')
    # Known FIFO fixture consumes all opening stock and one unit of the receipt.
    cost=x['opening_amount']+(x['sale_qty']-x['opening_qty'])*x['receipt_amount']/x['receipt_qty']
    for k,v in dict(closing_qty=x['opening_qty']+x['receipt_qty']-x['sale_qty'],expense_qty=x['sale_qty'],expense_amount=cost,closing_amount=x['opening_amount']+x['receipt_amount']-cost,revenue=x['sale_qty']*x['sale_price'],profit=x['sale_qty']*x['sale_price']-cost).items():scalar('OU-REPORT',k,v)
    x={k:D(v) for k,v in inputs('PR-TARIFF').items()}
    for k,v in dict(January_D1=x['January_rate']*x['D1_hours'],January_D2=x['January_rate']*x['D2_hours'],February_D1=x['February_rate']*x['D1_hours'],January_selected_rate=x['January_rate'],February_selected_rate=x['February_rate']).items():scalar('PR-TARIFF',k,v)
    x={k:D(v) for k,v in inputs('PR-BONUS').items()};base=x['E1_tariff']+x['E2_tariff'];scalar('PR-BONUS','base',base)
    for percent in (10,12,17):scalar('PR-BONUS','bonus_'+str(percent),base*D(percent)/100)
    x=inputs('PR-TRIP');amount=sum(map(D,x['month_accruals']));days=sum(map(D,x['month_worked_days']));daily=amount/days
    for month,total in zip(x['accruals_by_type'],x['month_accruals']):eq(sum(map(D,month.values())),total,'PR-TRIP.month_total')
    for k,v in dict(base_accruals=amount,worked_days=days,daily_rate=daily,trip_days=x['trip_days'],trip_amount=daily*D(x['trip_days']),remaining_hours=x['remaining_hours'],tariff_amount=D(x['remaining_hours'])*D(x['tariff_rate'])).items():scalar('PR-TRIP',k,v)
    x={k:D(v) for k,v in inputs('PR-BACKDATE').items()}
    for k,v in dict(tariff_before=x['initial_days']*x['hours_per_day']*x['rate'],tariff_after=(x['initial_days']-x['removed_days'])*x['hours_per_day']*x['rate'],trip_after=x['removed_days']*x['trip_daily_rate']).items():scalar('PR-BACKDATE',k,v)
    x={k:D(v) for k,v in inputs('PR-PERIODS').items()}
    for month in ('January','February'):scalar('PR-PERIODS',month+'_tariff',x[month+'_rate']*x['hours'])
    scalar('PR-REPORT','total_bonus',sum(D(v) for v in inputs('PR-REPORT').values()))
    check(expected('BU-ORDER') is None,'unapproved analog order')
    evidence=read('private/book-evidence.json')
    check([r['printed_page'] for r in evidence['pages']]==list(range(171,185)),'missing book page')
    for r in evidence['pages']:
        local=ROOT/r['local_original']
        if local.exists():check(sha(local.read_bytes())==r['sha256'],'book original changed')
    result={'package':'1c-platform-official-sample','specification_check':'passed','rules':len(rules),'rule_states':dict(Counter(r['status'] for r in rules)),'fixtures':len(cases),'questions_open':len(questions),'decimal_comparisons':comparisons,'source_hashes':'verified','retained_source_xml_elements':'verified','visual_qa':'recorded 4 pages','book_pages':len(evidence['pages']),'runtime_solution_tests_executed':0,'ready':False}
    (TASK/'private/validation-specification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
