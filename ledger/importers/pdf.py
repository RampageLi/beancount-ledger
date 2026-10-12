"""Use PDF column geometry to preserve wrapped payees and ignore page furniture."""
from bisect import bisect_right
from pathlib import Path
import re
import pymupdf
from .base import Importer


class PDFImporter(Importer):
    title = ''
    columns = ()

    def identify(self, filepath):
        if Path(filepath).suffix.lower() != '.pdf':
            return False
        with pymupdf.open(filepath) as document:
            return bool(len(document)) and self.title in document[0].get_text()

    def rows(self, filepath):
        with pymupdf.open(filepath) as document:
            for page_number, page in enumerate(document, 1):
                horizontal = {
                    block['number']
                    for block in page.get_text('dict', flags=pymupdf.TEXTFLAGS_WORDS)['blocks'] if 'lines' in block
                    for index, line in enumerate(block['lines'])
                    if abs(line['dir'][0] - 1) < 0.001 and abs(line['dir'][1]) < 0.001
                }
                words = [w for w in page.get_text('words') if w[5] in horizontal]
                headers = []
                for name in self.columns:
                    matches = [w for w in words if w[4] == name]
                    if not matches:
                        raise ValueError(f'{filepath}: page {page_number}: missing column {name}')
                    headers.append(matches[-1])
                centers = [(w[0] + w[2]) / 2 for w in headers]
                boundaries = [(a + b) / 2 for a, b in zip(centers, centers[1:])]
                dates = sorted([w for w in words if re.fullmatch(r'\d{4}-\d{2}-\d{2}', w[4])
                                and w[0] < boundaries[0] and w[1] > headers[0][3]], key=lambda w: w[1])
                if not dates:
                    raise ValueError(f'{filepath}: page {page_number}: no recognizable transactions')
                grid = sorted({round(item[1].y, 2)
                               for drawing in page.get_drawings() for item in drawing['items']
                               if item[0] == 'l' and abs(item[1].y - item[2].y) < 0.1
                               and min(item[1].x, item[2].x) <= centers[1] <= max(item[1].x, item[2].x)})
                for index, anchor in enumerate(dates):
                    top = anchor[1] - 1
                    bottom = dates[index + 1][1] - 1 if index + 1 < len(dates) else anchor[1] + 32
                    if self.source == 'cib_debit':
                        above = [y for y in grid if y < anchor[1]]
                        below = [y for y in grid if y > anchor[3]]
                        if not above or not below:
                            raise ValueError(f'{filepath}: page {page_number}: missing table grid')
                        top, bottom = max(above), min(below)
                    cells = [[] for _ in self.columns]
                    for word in words:
                        in_row = word[5] == anchor[5] if self.source == 'cmb_debit' else top <= word[1] < bottom
                        if in_row:
                            cells[bisect_right(boundaries, (word[0] + word[2]) / 2)].append(word)
                    values = [''.join(w[4] for w in sorted(cell, key=lambda w: (round(w[1], 1), w[0]))) for cell in cells]
                    yield page_number, index + 1, dict(zip(self.columns, values))
