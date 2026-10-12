from datetime import datetime
from decimal import Decimal
from pathlib import Path

from beancount import loader
from beancount.core import data
from ledger.build_fava import build, render, reconcile, record_id, TRANSFER, PENDING
from ledger.importers.base import Record


def row(source, number, amount='-10', **kwargs):
    return Record(source, 'sample', number, datetime(2026, 9, 1, 12, 30),
                  Decimal(amount), signed_amount=Decimal(amount), **kwargs)


def test_unique_card_match_keeps_only_bank_posting():
    bank = row('cib_credit', 1, card='主卡1234')
    platform = row('wechat', 1, payment_method='兴业银行信用卡(1234)', transaction_id='001')
    entries, audit = build([bank, platform])
    transactions = [e for e in entries if isinstance(e, data.Transaction)]
    assert len(transactions) == 1
    assert transactions[0].meta['platform_id'] == '001'
    assert transactions[0].postings[0].units.number == Decimal('-10')
    assert audit[1]['disposition'] == 'matched_bank_transaction'


def test_ambiguous_or_wrong_card_not_merged():
    banks = [row('cib_credit', n, card='主卡1234') for n in (1, 2)]
    platform = row('wechat', 1, payment_method='兴业银行信用卡(1234)')
    assert not reconcile(banks + [platform])
    platform.payment_method = '兴业银行信用卡(9999)'
    assert not reconcile([banks[0], platform])


def test_two_platform_matches_are_not_both_removed():
    bank = row('cib_credit', 1, card='主卡1234')
    platforms = [row(s, 1, payment_method='兴业银行信用卡(1234)') for s in ('wechat', 'alipay')]
    assert not reconcile([bank] + platforms)


def test_combined_and_unknown_rows_remain_auditable():
    combined = row('alipay', 1, payment_method='余额宝&红包')
    neutral = row('alipay', 2, payment_method='余额宝')
    neutral.signed_amount = None
    entries, audit = build([combined, neutral])
    transactions = [e for e in entries if isinstance(e, data.Transaction)]
    assert len(transactions) == 1
    assert transactions[0].postings[0].account == 'Assets:CN:Alipay:YuEBao'
    assert transactions[0].postings[0].units.number == Decimal('-10')
    assert transactions[0].postings[1].units.number == Decimal('10')
    assert audit[0]['policy'] == 'statement_amount_for_discount_payment'
    assert len([e for e in entries if isinstance(e, data.Note)]) == 1
    assert len(audit) == 2
    _, errors, _ = loader.load_string(render(entries))
    assert not errors


def test_transfers_and_unknown_income_do_not_inflate_spending():
    entries, _ = build([row('cib_debit', 1, narration='转账'), row('cib_debit', 2, '20', narration='来款')])
    transactions = [e for e in entries if isinstance(e, data.Transaction)]
    assert transactions[0].postings[1].account == TRANSFER
    assert transactions[1].postings[1].account == PENDING


def test_wallet_payment_and_repeated_id():
    wallet = row('wechat', 1, payment_method='零钱', transaction_id='001', narration='餐饮')
    entries, audit = build([wallet, wallet])
    txns = [e for e in entries if isinstance(e, data.Transaction)]
    assert len(txns) == 1
    assert txns[0].postings[0].account == 'Assets:CN:Wechat:Balance'
    assert txns[0].postings[1].account == 'Expenses:Food:Restaurants'
    assert audit[1]['disposition'] == 'duplicate_source_id'


def test_fava_app_loads_generated_ledger():
    import pytest
    from fava.application import create_app
    path = Path('ledger/main.beancount').resolve()
    if not Path('ledger/output/fava/transactions.beancount').exists():
        pytest.skip('Run make build with private statements first')
    _, errors, _ = loader.load_file(str(path))
    assert not errors
    app = create_app([str(path)])
    client = app.test_client()
    response = client.get('/', follow_redirects=True)
    assert response.status_code == 200
    for page in ('income_statement', 'balance_sheet', 'journal', 'errors'):
        base = response.request.path.rsplit('/', 2)[0]
        result = client.get(f'{base}/{page}/')
        assert result.status_code == 200, page


def confirmation(transaction, account):
    keys = ('source', 'date', 'signed_amount', 'currency', 'payee', 'narration')
    return {'match': {key: str(getattr(transaction, key)) for key in keys},
            'account': account, 'description': '用户确认用途'}


def test_confirmation_reclassifies_transfer_and_clears_review():
    transaction = row('wechat', 1, '-1000', payment_method='零钱', narration='转账', payee='收款人')
    rule = confirmation(transaction, 'Expenses:Gifts:Wedding')
    entries, audit = build([transaction], [rule])
    entry = next(e for e in entries if isinstance(e, data.Transaction))
    assert entry.flag == '*'
    assert 'review' not in entry.tags and 'confirmed' in entry.tags
    assert entry.postings[1].account == 'Expenses:Gifts:Wedding'
    assert entry.postings[1].units.number == Decimal('1000')
    assert audit[0]['disposition'] == 'confirmed'
    assert audit[0]['confirmation'] == rule
    _, errors, _ = loader.load_string(render(entries))
    assert not errors


def test_confirmation_survives_file_rename_but_rejects_ambiguous_match():
    import pytest
    transaction = row('wechat', 1, payment_method='零钱')
    rule = confirmation(transaction, 'Expenses:Other')
    transaction.source_file = 'renamed.xlsx'
    entries, _ = build([transaction], [rule])
    assert next(e for e in entries if isinstance(e, data.Transaction)).flag == '*'
    with pytest.raises(ValueError, match='matched 2 records'):
        build([transaction, transaction], [rule])
    transaction.payee = 'different payee'
    with pytest.raises(ValueError, match='matched 0 records'):
        build([transaction], [rule])


def test_reimbursement_offsets_expenses_without_changing_cash():
    transaction = row('cib_debit', 1, '50', narration='代发款项')
    rule = confirmation(transaction, 'Expenses:Reimbursable')
    entries, _ = build([transaction], [rule])
    entry = next(e for e in entries if isinstance(e, data.Transaction))
    assert entry.postings[0].units.number == Decimal('50')
    assert entry.postings[1].units.number == Decimal('-50')
    assert entry.postings[1].account == 'Expenses:Reimbursable'


def test_combined_card_payment_matches_only_exact_bank_amount():
    bank = row('cib_credit', 1, card='主卡1234')
    platform = row('alipay', 1, payment_method='兴业银行信用卡(1234)&兴业银行立减金')
    assert reconcile([bank, platform]) == {record_id(platform): record_id(bank)}
    platform.signed_amount = Decimal('-11')
    assert not reconcile([bank, platform])


def test_main_ledger_uses_english_account_types():
    import pytest
    from ledger.config.accounts import ROOTS
    if not Path('ledger/output/fava/transactions.beancount').exists():
        pytest.skip('Private statements not available')
    entries, errors, options = loader.load_file('ledger/main.beancount')
    assert not errors
    for name, root in ROOTS.items():
        assert options[f'name_{name}'] == root
    assert sum(isinstance(e, data.Transaction) and 'confirmed' in e.tags for e in entries) == 5
    for entry in entries:
        if isinstance(entry, data.Open):
            assert entry.account.split(':')[0] in ROOTS.values()
            assert entry.account.isascii()


def test_later_bank_statement_replaces_unmatched_card_expense():
    from datetime import timedelta
    platform = row('wechat', 1, '-28.19', payment_method='兴业银行信用卡(1234)',
                   transaction_id='001', payee='7-Eleven')
    entries, _ = build([platform])
    transaction = next(e for e in entries if isinstance(e, data.Transaction))
    assert transaction.postings[1].account == 'Expenses:CreditCard:Unmatched'
    assert transaction.postings[0].account == 'Liabilities:CN:Bank:CIB'
    bank = row('cib_credit', 1, '-28.19', card='主卡1234', payee='财付通快捷--7-Eleven', posting_date='2026-10-01')
    bank.date = platform.date + timedelta(seconds=60)
    entries, audit = build([platform, bank])
    transactions = [e for e in entries if isinstance(e, data.Transaction)]
    assert len(transactions) == 1
    assert transactions[0].postings[1].account == 'Expenses:Shopping:Groceries'
    assert transactions[0].postings[1].units.number == Decimal('28.19')
    assert audit[0]['disposition'] == 'matched_bank_transaction'
    assert transactions[0].date == platform.date.date()


def test_ambiguous_bank_match_does_not_add_platform_expense():
    bank = row('cib_credit', 1, card='主卡1234')
    platforms = [row(s, 1, payment_method='兴业银行信用卡(1234)') for s in ('wechat', 'alipay')]
    entries, audit = build([bank] + platforms)
    assert len([e for e in entries if isinstance(e, data.Transaction)]) == 1
    assert [a['disposition'] for a in audit[1:]] == ['ambiguous_card_match'] * 2


def test_nearby_different_merchant_not_matched():
    from datetime import timedelta
    bank = row('cib_credit', 1, card='主卡1234', payee='支付宝--商户甲')
    platform = row('alipay', 1, payment_method='兴业银行信用卡(1234)',payee='商户乙')
    platform.date += timedelta(seconds=60)
    assert not reconcile([bank, platform])


def test_discount_policy_does_not_guess_two_cash_sources():
    combined = row('alipay', 1, payment_method='余额宝&账户余额')
    entries, audit = build([combined])
    assert not any(isinstance(e, data.Transaction) for e in entries)
    assert audit[0]['disposition'] == 'unmatched_card_or_combined_payment'
