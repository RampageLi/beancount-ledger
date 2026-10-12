from pathlib import Path
from .base import Importer, Record, money, timestamp, xlsx_rows, table_rows, clean


class CIBCreditImporter(Importer):
    source = 'cib_credit'
    account = 'Liabilities:CN:Bank:CIB'

    def identify(self, filepath):
        return Path(filepath).suffix.lower() == '.xlsx' and any(
            '兴业银行信用卡' in str(row[0]) for row in xlsx_rows(filepath)[:5] if row)

    def parse_bill(self, filepath):
        records = []
        for number, raw in table_rows(xlsx_rows(filepath), {'交易日期', '记账日期', '交易金额', '交易摘要'}):
            row = clean(raw)
            date = row.get('交易日期', '')
            if not date or date == 'Trans Date' or date.startswith(('共计', '说明')):
                continue
            try:
                amount = money(row['交易金额'])
                records.append(Record(
                    self.source, str(Path(filepath)), number, timestamp(date), amount,
                    signed_amount=-amount, payee=row['交易摘要'], narration=row['交易摘要'],
                    direction='支出' if amount > 0 else '收入',
                    posting_date=timestamp(row['记账日期']).date().isoformat(),
                    card=row.get('尾号4位', ''), raw=row))
            except (ValueError, ArithmeticError) as exc:
                raise ValueError(f'{filepath}: row {number}: {exc}') from exc
        return records
