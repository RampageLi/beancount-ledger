import csv
from pathlib import Path
from .base import Importer, Record, money, timestamp, xlsx_rows, table_rows, clean


class PlatformImporter(Importer):
    def parse_bill(self, filepath):
        records = []
        rows = self.read_rows(filepath)
        for number, raw in table_rows(rows, {'交易时间', '交易对方', '收/支'}):
            row = clean(raw)
            # Export footnotes are outside the transaction table.
            if not row.get('交易时间') or row['交易时间'].startswith(('说明', '注', '---')):
                continue
            try:
                amount = money(row.get('金额', row.get('金额(元)')))
                direction = row['收/支']
                status = row.get('交易状态', row.get('当前状态', ''))
                signed = {'支出': -abs(amount), '收入': abs(amount)}.get(direction)
                if direction not in ('支出', '收入') and ('退款' in row.get('交易分类', '') or row.get('交易类型') == '退款'):
                    signed = abs(amount)
                if (self.source == 'alipay' and status == '交易成功'
                        and row.get('商品说明', '').startswith('余额宝-')
                        and row.get('商品说明', '').endswith('-收益发放')):
                    signed = abs(amount)
                if status in ('交易关闭', '支付失败', '已关闭', '未支付'):
                    signed = None
                records.append(Record(
                    self.source, str(Path(filepath)), number, timestamp(raw['交易时间']), amount,
                    signed_amount=signed, payee=row['交易对方'],
                    narration=row.get('商品说明', row.get('商品', '')),
                    direction=direction, status=status,
                    payment_method=row.get('收/付款方式', row.get('支付方式', '')),
                    transaction_id=row.get('交易订单号', row.get('交易单号', '')),
                    merchant_id=row.get('商家订单号', row.get('商户单号', '')), raw=row))
            except (ValueError, ArithmeticError) as exc:
                raise ValueError(f'{filepath}: row {number}: {exc}') from exc
        return records


class AlipayImporter(PlatformImporter):
    source = 'alipay'
    account = 'Assets:CN:Alipay:Balance'

    def read_rows(self, filepath):
        content = Path(filepath).read_bytes()
        for encoding in ('utf-8-sig', 'gb18030'):
            try:
                return list(csv.reader(content.decode(encoding).splitlines(keepends=True)))
            except UnicodeDecodeError:
                pass
        raise ValueError('Unsupported CSV encoding')

    def identify(self, filepath):
        return Path(filepath).suffix.lower() == '.csv' and any(
            '支付宝' in ''.join(row) for row in self.read_rows(filepath)[:25])


class WechatImporter(PlatformImporter):
    source = 'wechat'
    account = 'Assets:CN:Wechat:Balance'
    read_rows = staticmethod(xlsx_rows)

    def identify(self, filepath):
        return Path(filepath).suffix.lower() == '.xlsx' and any(
            '微信支付账单' in str(row[0]) for row in xlsx_rows(filepath)[:5] if row)
