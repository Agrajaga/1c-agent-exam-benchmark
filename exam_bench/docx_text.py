"""Plain-text rendering of Word documents for the solver: paragraphs as lines, tables with ASCII borders.

Cell text wraps inside its column, so a long penalty description stays readable next to its score.
"""
import re
import textwrap
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
MAX_COLUMN = 88


def text_of(element):
    return ''.join(x.text or '' for x in element.iter(W + 't')).replace('\xa0', ' ')


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in s)


def cell_lines(cell, limit):
    """Paragraphs of a cell, each wrapped to the column width."""
    out = []
    for p in cell.findall(W + 'p'):
        text = re.sub(r'\s+', ' ', text_of(p)).strip()
        if text:
            out += textwrap.wrap(text, limit, break_long_words=False, break_on_hyphens=False) or ['']
    return out or ['']


def table(element, limit=MAX_COLUMN):
    rows = []
    for row in element.findall(W + 'tr'):
        cells = []
        for cell in row.findall(W + 'tc'):
            span = cell.find(W + 'tcPr/' + W + 'gridSpan')
            cells.append((cell, int(span.get(W + 'val')) if span is not None else 1))
        rows.append(cells)
    columns = max(sum(s for _, s in r) for r in rows)
    natural = [0] * columns
    for r in rows:
        col = 0
        for cell, span in r:
            if span == 1:
                natural[col] = max(natural[col], max(width(x) for x in cell_lines(cell, 10 ** 6)))
            col += span
    widths = [min(w, limit) for w in natural]
    rendered = []
    for r in rows:
        col, cells = 0, []
        for cell, span in r:
            w = sum(widths[col:col + span]) + 3 * (span - 1)
            cells.append((cell_lines(cell, w), w))
            col += span
        rendered.append(cells)
    for r, cells in zip(rows, rendered):
        col = 0
        for (cell, span), (lines, w) in zip(r, cells):
            need = max(width(x) for x in lines)
            if need > w:  # an unbreakable word wider than the column
                widths[col + span - 1] += need - w
            col += span
    rule = '+' + '+'.join('-' * (w + 2) for w in widths) + '+'
    out = [rule]
    for i, r in enumerate(rows):
        col, cells = 0, []
        for cell, span in r:
            w = sum(widths[col:col + span]) + 3 * (span - 1)
            cells.append((cell_lines(cell, w), w))
            col += span
        for k in range(max(len(lines) for lines, _ in cells)):
            out.append('|' + '|'.join(' ' + (lines[k] if k < len(lines) else '') + ' ' * (w - width(lines[k] if k < len(lines) else '')) + ' '
                                      for lines, w in cells) + '|')
        out.append(rule.replace('-', '=') if i == 0 and len(rows) > 1 else rule)
    return out


def body(docx):
    with zipfile.ZipFile(docx) as z:
        rels = z.read('word/_rels/document.xml.rels').decode()
        root = ET.fromstring(z.read('word/document.xml')).find(W + 'body')
    return list(root), dict(re.findall(r'Id="(rId\d+)"[^>]*Target="media/image(\d+)\.\w+"', rels))


def render(elements, media=None, figure=None):
    """Lines of the given body elements; figure(n) gives the lines that replace image n."""
    lines = []
    for element in elements:
        if element.tag == W + 'tbl':
            lines.extend(table(element))
        elif element.tag == W + 'p':
            blips = list(element.iter(A + 'blip'))
            for blip in blips:
                if figure and media:
                    lines += figure(int(media[blip.get(R + 'embed')]))
            text = text_of(element)
            if text or not blips:
                lines.append(text)
    return lines


def words(text):
    """Word sequence without table borders, to prove a rendering keeps the official text."""
    return re.findall(r'[0-9A-Za-zА-Яа-яЁё]+(?:[,.][0-9]+)?', re.sub(r'[+|=-]{3,}', ' ', text))
