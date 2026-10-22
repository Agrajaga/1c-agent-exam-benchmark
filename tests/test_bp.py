import json
import tempfile
import unittest
from pathlib import Path

from exam_bench.bp import business_processes, recalculations
from exam_bench.penalties import assess

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'tasks/1c-platform-official-sample'


class Metadata:
    """A minimal export of a business process, its task, the addressing register and a recalculated register."""

    def __init__(self, root):
        self.root = Path(root)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def process(self, route=('Start', 'Activity', 'Completion'), route_map=True, own_list=True, in_subsystem=True,
                linked=True, extra_attribute=False):
        attr = lambda name, dim: ('<AddressingAttribute uuid="1"><Properties><Name>%s</Name><AddressingDimension>%s</AddressingDimension>'
                                  '</Properties></AddressingAttribute>' % (name, dim))
        attrs = attr('Исполнитель', 'InformationRegister.Адресация.Dimension.Исполнитель')
        attrs += attr('Должность', 'InformationRegister.Адресация.Dimension.Должность' if linked else '')
        if extra_attribute:
            attrs += attr('Проект', 'InformationRegister.Адресация.Dimension.Проект')
        self.write('Tasks/Задачи.xml', '<Task><Addressing>InformationRegister.Адресация</Addressing>'
                   '<MainAddressingAttribute>Task.Задачи.AddressingAttribute.Исполнитель</MainAddressingAttribute>' + attrs + '</Task>')
        dims = ''.join('<Dimension uuid="2"><Properties><Name>%s</Name></Properties></Dimension>' % d
                       for d in ('Исполнитель', 'Должность') + (('Проект',) if extra_attribute else ()))
        self.write('InformationRegisters/Адресация.xml', '<InformationRegister>' + dims + '</InformationRegister>')
        self.write('BusinessProcesses/Процесс.xml', '<BusinessProcess><Task>Task.Задачи</Task>'
                   '<DefaultObjectForm>BusinessProcess.Процесс.Form.Форма</DefaultObjectForm></BusinessProcess>')
        self.write('BusinessProcesses/Процесс/Ext/Flowchart.xml', ''.join('<%s id="%d">' % (k, i) for i, k in enumerate(route))
                   + '<AddressingAttribute ref="Task.Задачи.AddressingAttribute.Должность"><Value xsi:type="xr:DesignTimeRef">Catalog.Должности.Кассир</Value></AddressingAttribute>')
        self.write('BusinessProcesses/Процесс/Forms/Форма/Ext/Form.xml', '<Form><Type>v8ui:GraphicalSchema</Type></Form>' if route_map else '<Form/>')
        self.write('BusinessProcesses/Процесс/Forms/Форма/Ext/Form/Module.bsl', 'Карта = РеквизитФормыВЗначение("Объект").ПолучитьКартуМаршрута();' if route_map else '')
        main = 'Task.Задачи.TasksByExecutive' if own_list else 'Task.Задачи'
        self.write('Tasks/Задачи/Forms/Мои/Ext/Form.xml', '<Form><MainTable>%s</MainTable><dcsset:item><dcsset:left xsi:type="dcscor:Field">Выполнена</dcsset:left>'
                   '<dcsset:comparisonType>Equal</dcsset:comparisonType><dcsset:right xsi:type="xs:boolean">false</dcsset:right></dcsset:item></Form>' % main)
        self.write('Subsystems/Процессы.xml', '<Subsystem><xr:Item xsi:type="xr:MDObjectRef">%s</xr:Item></Subsystem>' % ('Task.Задачи' if in_subsystem else 'Catalog.Сотрудники'))

    def recalculation(self, linked=True, leading=True):
        self.write('CalculationRegisters/Начисления.xml', '<CalculationRegister><ChartOfCalculationTypes>ChartOfCalculationTypes.Виды</ChartOfCalculationTypes></CalculationRegister>')
        self.write('CalculationRegisters/Начисления/Recalculations/Перерасчет.xml', '<Recalculation><Dimension uuid="3"><Properties><Name>Сотрудник</Name>'
                   '<RegisterDimension>%s</RegisterDimension></Properties></Dimension></Recalculation>' % ('CalculationRegister.Начисления.Dimension.Сотрудник' if linked else ''))
        lead = '<Leading><CalculationType>ChartOfCalculationTypes.Виды.Оклад</CalculationType></Leading>' if leading else ''
        self.write('ChartsOfCalculationTypes/Виды/Ext/Predefined.xml', '<Item id="1"><Name>Оклад</Name></Item>'
                   '<Item id="2"><Name>Премия</Name><Base><CalculationType>ChartOfCalculationTypes.Виды.Оклад</CalculationType></Base>' + lead + '</Item>')


class BusinessProcessSigns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.meta = Metadata(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def states(self, **kw):
        self.meta.process(**kw)
        return {k: v[0] for k, v in business_processes(self.meta.root).items()}

    def test_a_complete_process_is_clean(self):
        self.assertEqual(set(self.states().values()), {'no_violation_found'})

    def test_each_defect(self):
        cases = {'F1C-BP01': dict(route=('Start', 'Completion')), 'F1C-BP02': dict(route_map=False), 'F1C-BP03': dict(own_list=False),
                 'F1C-BP06': dict(extra_attribute=True), 'F1C-BP07': dict(linked=False), 'F1C-BP09': dict(in_subsystem=False)}
        for penalty, kw in cases.items():
            with self.subTest(penalty):
                self.tmp.cleanup(); self.tmp = tempfile.TemporaryDirectory(); self.meta = Metadata(self.tmp.name)
                states = self.states(**kw)
                self.assertEqual(states[penalty], 'violation')
                self.assertEqual({k for k, v in states.items() if v == 'violation'}, {penalty} | ({'F1C-BP06'} if penalty == 'F1C-BP07' else set()))

    def test_no_process_part_at_all(self):
        self.assertEqual(business_processes(self.meta.root)['F1C-BP01'][0], 'violation')

    def test_recalculation_set_up(self):
        self.meta.recalculation()
        self.assertEqual({k: v[0] for k, v in recalculations(self.meta.root).items()}, {'F1C-PR10': 'no_violation_found', 'F1C-PR12': 'no_violation_found'})
        self.meta.recalculation(linked=False, leading=False)
        self.assertEqual({k: v[0] for k, v in recalculations(self.meta.root).items()}, {'F1C-PR10': 'violation', 'F1C-PR12': 'violation'})


class NotApplicableInTheTicket(unittest.TestCase):
    def test_sample_ticket_charges_no_business_process_penalty(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'Configuration.xml').write_text('<Configuration><DataLockControlMode>Managed</DataLockControlMode></Configuration>')
            result = assess([], tmp, {}, json.loads((TASK / 'checks.json').read_text())['requirements'], None,
                            json.loads((TASK / 'private/official-assessment-mapping.json').read_text()),
                            json.loads((TASK / 'private/owner-scoring-policy.json').read_text()))
            self.assertFalse([f for f in result['findings'] if f['penalty_id'].startswith('F1C-BP')])


if __name__ == '__main__':
    unittest.main()
