"""Render task/statement.txt from the issued task/statement.docx for a reader without a Word viewer.

The docx stays the official statement and is not rewritten. In the text copy tables are drawn with ASCII borders
and each figure is replaced by a reference to its file in task/assets/ with a text sketch of what it shows. The
sketches are the stand's transcription of the pictures; the picture files remain the source.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bench import docx_text  # noqa: E402

TASK = ROOT / 'tasks/1c-platform-official-sample'

SKETCHES = {
    1: '''+-------------------------+----------------------------------------------------------------------------------+
|                         |                                          Настройка навигации   Настройка действий |
| Главное                 |                                                                                  |
| Бизнес-процессы         |  Документы                Планы видов расчета            Создать                 |
| Оперативный учет        |    Начисление зарплаты      Основные начисления            Начисление зарплаты   |
| Бухгалтерский учет      |                             Дополнительные начисления                            |
| > Периодические расчеты |  Справочники                                             Отчеты                  |
| Сервис                  |    Сотрудники             Регистры расчета                 Перерасчеты           |
|                         |    Подразделения            Регистр "Дополнительные        По начислениям        |
|                         |    Графики                  начисления"                                          |
|                         |                             Регистр "Основные начисления"  Сервис                |
|                         |  См. также                                                   Заполнение графика  |
|                         |    Сведения о сотрудниках                                                        |
|                         |    Данные по графикам работы                                                     |
+-------------------------+----------------------------------------------------------------------------------+
Слева — Панель разделов (выбран раздел «Периодические расчеты»), справа — Панель навигации
(Документы, Справочники, См. также, Планы видов расчета, Регистры расчета) и Панель действий
(Создать, Отчеты, Сервис) этого раздела.''',
    2: '''+--------------------------------------------------------------+
| Иванов И.И. (Сотрудники)                                     |
| [Записать и закрыть]  [Записать]                    [Еще v]  |
| Код:           [Иванов                                    ]  |
| Наименование:  [Иванов И.И.                               ]  |
| [Добавить]                                          [Еще v]  |
| +----+-----------------------------------------------------+ |
| | N  | Дополнительный реквизит контрагента                 | |
| +----+-----------------------------------------------------+ |
| | 1  | Валюта кредита                                      | |
| | 2  | Срок кредита, дни                                   | |
| | 3  | Регион                                              | |
| +----+-----------------------------------------------------+ |
+--------------------------------------------------------------+
Форма элемента справочника сотрудников: табличная часть со списком дополнительных
реквизитов контрагента, которые использует этот менеджер.''',
    3: '''+--------------------------------------------------------------+
| Завод "Сатурн" (Контрагенты) *                               |
| [Записать и закрыть]  [Записать]                    [Еще v]  |
| Код:                [3]                                      |
| Наименование:       [Завод "Сатурн"                       ]  |
| Менеджер:           [Иванов И.И.                     v] [_]  |
| Валюта кредита:     [Доллар США                      v] [_]  |
| Срок кредита, дни:  [10]                                     |
| Регион:             [Москва                          v] [_]  |
+--------------------------------------------------------------+
Форма контрагента после выбора менеджера Иванов И.И.: под полем «Менеджер» появились поля
«Валюта кредита», «Срок кредита, дни», «Регион» — дополнительные реквизиты из списка этого менеджера.''',
}


def render(docx):
    elements, media = docx_text.body(docx)
    figure = lambda n: [f'[Рисунок {n}: файл task/assets/figure-{n}.png. Ниже — его текстовая схема, источник — сам файл]', SKETCHES[n]]
    return '\n'.join(docx_text.render(elements, media, figure)) + '\n'


def main():
    public = TASK / 'public'
    text = render(public / 'statement.docx')
    (public / 'statement.txt').write_text(text, encoding='utf-8')
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    manifest_path = TASK / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['public']['text_sha256'] = digest
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    source_map_path = TASK / 'private/source-map.json'
    source_map = json.loads(source_map_path.read_text())
    source_map['output_sha256']['public/statement.txt'] = digest
    source_map['text_rendering'] = 'tools/render_statement_text.py: ASCII tables, figure references with text sketches'
    source_map_path.write_text(json.dumps(source_map, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'statement.txt': digest, 'lines': text.count('\n')}))


if __name__ == '__main__':
    main()
