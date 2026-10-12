from pathlib import Path
from .base import Record, money, timestamp
from .pdf import PDFImporter


class CMBImporter(PDFImporter):
    source = 'cmb_debit'
    account = 'Assets:CN:Bank:CMB'
    title = '招商银行交易流水'
    columns = ('记账日期', '货币', '交易金额', '联机余额', '交易摘要', '对手信息')

    def parse_bill(self, filepath):
        records = []
        for page, number, row in self.rows(filepath):
            try:
                amount = money(row['交易金额'])
                records.append(Record(
                    self.source, str(Path(filepath)), number, timestamp(row['记账日期']), amount,
                    currency=row['货币'], signed_amount=amount, balance=money(row['联机余额']),
                    payee=row['对手信息'], narration=row['交易摘要'],
                    posting_date=row['记账日期'], direction='支出' if amount < 0 else '收入',
                    page=page, raw=row))
            except (ValueError, ArithmeticError) as exc:
                raise ValueError(f'{filepath}: page {page}, row {number}: {exc}') from exc
        return records
