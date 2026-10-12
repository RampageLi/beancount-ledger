from datetime import datetime
from decimal import Decimal
from pathlib import Path
import csv
import io

import pytest
from openpyxl import Workbook
from beancount.core import data
from beancount.parser import printer, parser
from ledger.importers import (AlipayImporter, WechatImporter, CMBImporter,
                              CIBDebitImporter, CIBCreditImporter, identify)
from ledger.importers.base import money


@pytest.mark.parametrize('value,expected', [('￥1,234.50', '1234.50'), ('¥-20', '-20'), ('(10.01)', '-10.01')])
def test_decimal(value, expected):
    assert money(value) == Decimal(expected)


def make_alipay(tmp_path):
    path = tmp_path / 'unrelated.csv'
    rows = [
        ['支付宝交易明细'],
        ['交易时间', '交易分类', '交易对方', '商品说明', '收/支', '金额', '收/付款方式', '交易状态', '交易订单号'],
        ['2026-09-01 12:30:00', '购物', '商家', '商品,含逗号\n第二行', '支出', '10.01', '银行卡', '交易成功', '000123\t'],
        ['2026-09-02 12:30:00', '退款', '商家', '退款', '不计收支', '2.00', '银行卡', '退款成功', '000124'],
        ['2026-09-03 12:30:00', '投资理财', '余额宝', '转存', '不计收支', '10', '余额', '交易成功', '000125'],
        ['2026-09-04 12:30:00', '购物', '商家', '关闭', '支出', '10', '银行卡', '交易关闭', '000126'],
    ]
    with path.open('w', encoding='gb18030', newline='') as f:
        csv.writer(f).writerows(rows)
    return path


def test_csv_lossless_and_signs(tmp_path):
    path = make_alipay(tmp_path)
    importer = identify(path)
    rows = importer.parse_bill(path)
    assert isinstance(importer, AlipayImporter)
    assert len(rows) == 4
    assert [r.signed_amount for r in rows] == [Decimal('-10.01'), Decimal('2'), None, None]
    assert rows[0].transaction_id == '000123'
    assert rows[0].narration == '商品,含逗号\n第二行'
    assert rows[2].amount == Decimal('10')


def test_beancount_draft_and_existing_ids(tmp_path):
    path = make_alipay(tmp_path)
    importer = AlipayImporter()
    entries = importer.extract(path)
    assert len(entries) == 2
    assert all(e.flag == '!' and sum(p.units.number for p in e.postings) == 0 for e in entries)
    assert importer.extract(path, existing=entries) == []
    output = io.StringIO()
    printer.print_entries(entries, file=output)
    parsed, errors, _ = parser.parse_string(output.getvalue())
    assert not errors
    assert len(parsed) == 2


def test_xlsx_dates_and_refunds(tmp_path):
    path = tmp_path / 'wechat.xlsx'
    book = Workbook()
    sheet = book.active
    sheet.append(['微信支付账单明细'])
    sheet.append(['交易时间', '交易类型', '交易对方', '商品', '收/支', '金额(元)', '支付方式', '当前状态', '交易单号'])
    sheet.append([datetime(2026, 9, 1, 12, 0), '退款', '商家', '退款', '/', '￥1.20', '零钱', '退款成功', '001'])
    book.save(path)
    row = identify(path).parse_bill(path)[0]
    assert row.date == datetime(2026, 9, 1, 12, 0)
    assert row.signed_amount == Decimal('1.20')
    assert row.transaction_id == '001'


def test_credit_liability_sign(tmp_path):
    path = tmp_path / 'credit.xlsx'
    book = Workbook()
    sheet = book.active
    sheet.append(['兴业银行信用卡历史账单交易流水'])
    sheet.append(['交易日期', '记账日期', '交易金额', '交易摘要', '尾号4位'])
    sheet.append(['Trans Date', 'Post Date', 'Amount', 'Tran Description', 'Card No.'])
    for amount in ['¥10.50', '¥-2.50']:
        sheet.append(['20260930 23:50', '20261001', amount, '商户', '主卡1234'])
    book.save(path)
    rows = identify(path).parse_bill(path)
    assert [r.signed_amount for r in rows] == [Decimal('-10.50'), Decimal('2.50')]
    assert rows[0].date.month == 9
    assert rows[0].posting_date == '2026-10-01'


def test_bad_amount_is_not_silently_dropped(tmp_path):
    path = make_alipay(tmp_path)
    path.write_text(path.read_text(encoding='gb18030').replace('10.01', 'bad'), encoding='gb18030')
    with pytest.raises(ValueError, match='row 3'):
        AlipayImporter().parse_bill(path)


DATA = Path(__file__).resolve().parents[1] / 'ledger/data'


@pytest.mark.parametrize('source,count', [('alipay', 136), ('wechat', 90), ('cmb_debit', 48), ('cib_debit', 2), ('cib_credit', 85)])
def test_local_statements(source, count):
    files = [p for p in DATA.glob('*') if p.suffix in ('.csv', '.xlsx', '.pdf')]
    match = [(p, identify(p)) for p in files if identify(p).source == source]
    if len(match) != 1:
        pytest.skip('Private sample not available')
    path, importer = match[0]
    rows = importer.parse_bill(path)
    assert len(rows) == count
    assert all(r.date.year == 2026 and r.date.month == 9 for r in rows)
    assert all(isinstance(r.amount, Decimal) for r in rows)
    if source == 'cmb_debit':
        assert {r.page for r in rows} == {1, 2, 3}
        for before, after in zip(rows, rows[1:]):
            assert before.balance + after.amount == after.balance
    if source == 'cib_debit':
        assert sum(r.amount for r in rows) == 0
        assert {abs(r.amount) for r in rows} == {Decimal('4245.47')}
        assert rows[0].raw['交易地点'] == '兴业银行专业处理中心'
        assert rows[1].raw['交易地点'] == '兴业银行北京广渠门支行'
        assert all(r.balance is None for r in rows)
    if source == 'wechat':
        assert sum(r.amount for r in rows) == Decimal('5654.96')
    if source == 'alipay':
        assert sum(r.amount for r in rows if r.direction == '支出' and r.status != '交易关闭') == Decimal('11079.57')
        assert sum(r.amount for r in rows if r.direction == '收入') == Decimal('120')
        assert sum(r.amount for r in rows if r.direction == '不计收支') == Decimal('138.44')
    entries = importer.extract(path)
    assert all(isinstance(e, data.Transaction) for e in entries)
    assert all(sum(p.units.number for p in e.postings) == 0 for e in entries)

    output = io.StringIO()
    printer.print_entries(entries, file=output)
    _, errors, _ = parser.parse_string(output.getvalue())
    assert not errors


def test_cmb_wrapped_payee_stays_on_its_own_row():
    paths = list(DATA.glob('招商*.pdf'))
    if len(paths) != 1:
        pytest.skip('Private sample not available')
    rows = CMBImporter().parse_bill(paths[0])
    interest = next(r for r in rows if r.narration == '账户结息')
    assert interest.payee == '应付利息-应付个人活期存款利息(自动计提)（新)'
    assert all('应付利息' not in r.payee for r in rows if r.narration == '快捷支付')


def test_yuebao_yield_has_positive_direction_but_closed_yield_does_not(tmp_path):
    path = tmp_path / 'yield.csv'
    rows = [
        ['支付宝交易明细'],
        ['交易时间', '交易分类', '交易对方', '商品说明', '收/支', '金额', '收/付款方式', '交易状态', '交易订单号'],
        ['2026-09-01 03:00:00', '投资理财', '基金公司', '余额宝-2026.08.31-收益发放', '不计收支', '0.05', '余额宝', '交易成功', '001'],
        ['2026-09-02 03:00:00', '投资理财', '基金公司', '余额宝-2026.09.01-收益发放', '不计收支', '0.07', '余额宝', '交易关闭', '002'],
    ]
    with path.open('w', encoding='utf-8', newline='') as f:
        csv.writer(f).writerows(rows)
    records = AlipayImporter().parse_bill(path)
    assert records[0].signed_amount == Decimal('0.05')
    assert records[0].direction == '不计收支'
    assert records[1].signed_amount is None
    from ledger.build_fava import build
    entries, _ = build(records)
    transaction = next(e for e in entries if isinstance(e, data.Transaction))
    assert transaction.postings[1].account == 'Income:Investment:YuEBao'
    assert transaction.postings[1].units.number == Decimal('-0.05')
