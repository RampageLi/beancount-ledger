"""python -m ledger.importers ledger/data --output ledger/output/transactions.json"""
import argparse
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path
from . import identify


def main():
    parser = argparse.ArgumentParser(description='解析五类账单；默认保留全部明细，不进行跨渠道去重。')
    parser.add_argument('path', type=Path, nargs='?', default=Path('ledger/data'))
    parser.add_argument('--format', choices=['json', 'csv'], default='json')
    parser.add_argument('--output', '-o', type=Path)
    parser.add_argument('--month', help='按交易日期筛选自然月，例如 2026-09')
    args = parser.parse_args()
    if args.month:
        try:
            parsed = date.fromisoformat(args.month + '-01')
            if parsed.strftime('%Y-%m') != args.month:
                raise ValueError
        except ValueError:
            parser.error('--month 必须是 YYYY-MM')
    paths = sorted(p for p in args.path.iterdir() if p.suffix.lower() in {'.csv', '.xlsx', '.pdf'}) if args.path.is_dir() else [args.path]
    records = []
    try:
        if not paths:
            raise ValueError('No statement files found')
        for path in paths:
            importer = identify(path)
            rows = importer.parse_bill(path)
            print(f'{importer.source}: {len(rows)} records', file=sys.stderr)
            records.extend(row for row in rows if not args.month or row.date.strftime('%Y-%m') == args.month)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'解析失败：{exc}\n')
    values = [row.to_dict() for row in sorted(records, key=lambda row: (row.date, row.source, row.source_row))]
    if args.format == 'json':
        content = json.dumps(values, ensure_ascii=False, indent=2) + '\n'
    else:
        stream = io.StringIO()
        from .base import Record
        writer = csv.DictWriter(stream, fieldnames=list(Record.__dataclass_fields__))
        writer.writeheader()
        for row in values:
            row['raw'] = json.dumps(row['raw'], ensure_ascii=False)
            writer.writerow(row)
        content = stream.getvalue()
    if args.output:
        if args.output.resolve() in {p.resolve() for p in paths}:
            parser.error('输出文件不能覆盖原始账单')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding='utf-8-sig' if args.format == 'csv' else 'utf-8')
    else:
        print(content, end='')


if __name__ == '__main__':
    main()
