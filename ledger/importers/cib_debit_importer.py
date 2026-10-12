from pathlib import Path
from .base import Record, money, timestamp
from .pdf import PDFImporter


class CIBDebitImporter(PDFImporter):
    source = 'cib_debit'
    account = 'Assets:CN:Bank:CIB'
    title = '兴业银行交易明细'
    columns = ('交易时间', '记账日期', '摘要', '支/收', '交易金额', '账户余额', '交易地点', '对方户名', '对方账户/对方银行')

    def parse_bill(self, filepath):
        import pymupdf
        with pymupdf.open(filepath) as document:
            if '人民币' not in document[0].get_text():
                raise ValueError(f'{filepath}: unsupported or missing CIB currency')
        records = []
        for page, number, row in self.rows(filepath):
            try:
                amount = money(row['交易金额'])
                date = row['交易时间']
                records.append(Record(
                    self.source, str(Path(filepath)), number, timestamp(date[:10] + ' ' + date[10:]), amount,
                    signed_amount=amount, payee=row['对方户名'], narration=row['摘要'],
                    direction=row['支/收'], posting_date=timestamp(row['记账日期']).date().isoformat(),
                    balance=None if '*' in row['账户余额'] else money(row['账户余额']), page=page, raw=row))
            except (ValueError, ArithmeticError) as exc:
                raise ValueError(f'{filepath}: page {page}, row {number}: {exc}') from exc
        return records
