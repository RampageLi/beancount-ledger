"""Build a reviewable Fava ledger from statement files; never modify the originals."""
import argparse
from collections import Counter
from datetime import timedelta
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re

from beancount import loader
from beancount.core import data
from beancount.core.amount import Amount
from beancount.parser import printer
from ledger.importers import identify
from ledger.config.accounts import account_name, OPTIONS, UNMATCHED_CARD_EXPENSE
from ledger.utils.transaction_classifier import classify

ACCOUNTS = {
    'cmb_debit': 'Assets:CN:Bank:CMB',
    'cib_debit': 'Assets:CN:Bank:CIB',
    'cib_credit': 'Liabilities:CN:Bank:CIB',
    '余额宝': 'Assets:CN:Alipay:YuEBao',
    '账户余额': 'Assets:CN:Alipay:Balance',
    '零钱': 'Assets:CN:Wechat:Balance',
}
ACCOUNTS = {key: account_name(value) for key, value in ACCOUNTS.items()}
PENDING = account_name('Equity:Pending')
TRANSFER = account_name('Assets:Transfers:Pending')


def record_id(row):
    key = (row.source, row.transaction_id) if row.transaction_id else (
        row.source, row.source_file, row.page, row.source_row)
    return hashlib.sha256(repr(key).encode()).hexdigest()[:24]




def merchant_key(name):
    name = re.sub(r'^(支付宝|财付通)(快捷)?--', '', name)
    return re.sub(r'[^\w]', '', name.casefold())


def card_candidates(row, card_rows):
    tail = re.search(r'兴业银行信用卡\((\d{4})\)', row.payment_method)
    if not tail:
        return []
    eligible = [bank for bank in card_rows
                if bank.card.endswith(tail[1]) and bank.currency == row.currency
                and bank.signed_amount == row.signed_amount
                and bank.date.date() == row.date.date()]
    exact = [bank for bank in eligible
             if bank.date.replace(second=0, microsecond=0) == row.date.replace(second=0, microsecond=0)]
    return exact or [bank for bank in eligible if merchant_key(bank.payee) == merchant_key(row.payee)
                     and merchant_key(row.payee)
                     and abs((bank.date - row.date).total_seconds()) <= 120]


def reconcile(rows):
    """Prefer exact-minute matches; tolerate 120s only with the same merchant.

    Always require the same card, currency, amount and transaction date, and a
    one-to-one match. A later posting date does not create another expense.
    """
    card_rows = [r for r in rows if r.source == 'cib_credit']
    candidates = {}
    for row in rows:
        if row.source not in ('alipay', 'wechat') or row.signed_amount is None:
            continue
        matches = card_candidates(row, card_rows)
        if len(matches) == 1:
            candidates[record_id(row)] = record_id(matches[0])
    frequency = Counter(candidates.values())
    return {key: value for key, value in candidates.items() if frequency[value] == 1}


def resolve_confirmations(rows, confirmations):
    """Apply explicit decisions to exactly one source record, independent of file paths."""
    resolved = {}
    for rule in confirmations:
        selector = rule['match']
        required = {'source', 'date', 'signed_amount', 'currency', 'payee', 'narration'}
        if not required.issubset(selector):
            raise ValueError('Confirmation must specify source, date, amount, currency, payee and narration')
        matches = [row for row in rows if all(
            str(getattr(row, key)) == str(value) for key, value in selector.items())]
        if len(matches) != 1:
            raise ValueError(f"Confirmation {rule['description']!r} matched {len(matches)} records; expected one")
        identity = record_id(matches[0])
        if identity in resolved:
            raise ValueError('Multiple confirmations for the same transaction')
        resolved[identity] = rule
    return resolved


def build(rows, confirmations=()):
    confirmed = resolve_confirmations(rows, confirmations)
    matches = reconcile(rows)
    by_id = {record_id(row): row for row in rows}
    enrichment = {bank: by_id[platform] for platform, bank in matches.items()}
    entries, audit = [], []
    seen = set()
    for row in rows:
        identity = record_id(row)
        reason = ''
        policy = ''
        account = ACCOUNTS.get(row.source)
        if identity in seen:
            reason = 'duplicate_source_id'
        elif row.signed_amount is None:
            reason = 'closed_or_unknown_direction'
        elif identity in matches:
            reason = 'matched_bank_transaction'
        elif account is None:
            account = ACCOUNTS.get(row.payment_method)
            if account is None:
                methods = row.payment_method.split('&')
                discounts = {'红包', '现金抵价券', '到店支付立减券', '支付立减优惠'}
                if (methods[0] in ACCOUNTS and len(methods) > 1
                        and set(methods[1:]).issubset(discounts)):
                    account = ACCOUNTS[methods[0]]
                    policy = 'statement_amount_for_discount_payment'
                elif re.fullmatch(r'兴业银行信用卡\(\d{4}\)(?:&.*)?', row.payment_method) and row.signed_amount < 0:
                    if card_candidates(row, [r for r in rows if r.source == 'cib_credit']):
                        reason = 'ambiguous_card_match'
                    else:
                        account = ACCOUNTS['cib_credit']
                        policy = 'unmatched_card_expense'
                else:
                    reason = 'unmatched_card_or_combined_payment'
        seen.add(identity)
        decision = confirmed.get(identity)
        if decision and reason:
            raise ValueError(f'Cannot confirm a non-posted record: {identity} ({reason})')
        audit.append({'id': identity, 'disposition': reason or ('confirmed' if decision else 'posted_for_review'),
                      'confirmation': decision, 'policy': policy,
                      'matched_to': matches.get(identity), 'record': row.to_dict()})
        if reason:
            if reason not in ('matched_bank_transaction', 'duplicate_source_id'):
                meta = data.new_metadata(row.source_file, row.source_row)
                meta.update(import_id=identity, reason=reason, source=row.source)
                entries.append(data.Note(meta, row.date.date(), PENDING,
                                         f'待核对：{row.payee} / {row.narration} / {row.amount} {row.currency}',
                                         frozenset({'review'}), frozenset()))
            continue
        enriched = enrichment.get(identity)
        meta = data.new_metadata(row.source_file, row.source_row)
        meta.update(import_id=identity, source=row.source, source_file=row.source_file,
                    source_row=Decimal(row.source_row), payment_method=row.payment_method)
        if row.page:
            meta['source_page'] = Decimal(row.page)
        if row.transaction_id:
            meta['transaction_id'] = row.transaction_id
        if row.posting_date:
            meta['posting_date'] = row.posting_date
        if enriched:
            meta.update(platform_id=enriched.transaction_id, platform_source=enriched.source,
                        platform_file=enriched.source_file)
        contra = account_name(decision['account']) if decision else classify(row, enriched)
        if policy == 'unmatched_card_expense' and not decision:
            contra = UNMATCHED_CARD_EXPENSE
        if policy:
            meta['accounting_policy'] = policy
        audit[-1]['account'] = account
        audit[-1]['counter_account'] = contra
        if decision:
            meta['confirmation'] = decision['description']
        entries.append(data.Transaction(
            meta, row.date.date(), '*' if decision else '!', (enriched or row).payee, (enriched or row).narration,
            frozenset({'confirmed' if decision else 'review', row.source}), frozenset({identity}), [
                data.Posting(account, Amount(row.signed_amount, row.currency), None, None, None, None),
                data.Posting(contra, Amount(-row.signed_amount, row.currency), None, None, None, None),
            ]))
    accounts = {PENDING}
    for entry in entries:
        if isinstance(entry, data.Transaction):
            accounts.update(p.account for p in entry.postings)
    opening_date = min(r.date.date() for r in rows) - timedelta(days=1)
    # Only CMB provides an observable balance for these statements. Do not invent other openings.
    cmb = sorted([r for r in rows if r.source == 'cmb_debit'], key=lambda r: (r.date, r.page or 0, r.source_row))
    if cmb:
        first = cmb[0]
        accounts.add(account_name('Equity:Opening-Balances'))
        opening = first.balance - first.signed_amount
        entries.insert(0, data.Transaction(data.new_metadata('<statement-opening>', 0),
            first.date.date() - timedelta(days=1), '*', None, '招行期初余额（由首笔流水反推）',
            frozenset(), frozenset(), [
                data.Posting(ACCOUNTS['cmb_debit'], Amount(opening, first.currency), None, None, None, None),
                data.Posting(account_name('Equity:Opening-Balances'), Amount(-opening, first.currency), None, None, None, None)]))
        # Day-end assertions expose gaps/overlaps in concatenated statements.
        last_per_day = {r.date.date(): r for r in cmb}
        for day, last in last_per_day.items():
            entries.append(data.Balance(data.new_metadata(last.source_file, last.source_row),
                day + timedelta(days=1), ACCOUNTS['cmb_debit'], Amount(last.balance, last.currency), None, None))
    opens = [data.Open(data.new_metadata('<generated>', 0), opening_date, a, None, None) for a in sorted(accounts)]
    return opens + entries, audit


def render(entries):
    stream = io.StringIO()
    printer.print_entries(sorted(entries, key=data.entry_sortkey), file=stream)
    return OPTIONS + "\n" + stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('ledger/data'))
    parser.add_argument('--output', type=Path, default=Path('ledger/output/fava'))
    parser.add_argument('--confirmations', type=Path,
                        default=Path(__file__).parent / 'config/confirmations.json')
    args = parser.parse_args()
    rows = []
    for path in sorted(args.data.iterdir()):
        if path.suffix.lower() in ('.csv', '.xlsx', '.pdf'):
            rows.extend(identify(path).parse_bill(path))
    if not rows:
        parser.error('No statement records found')
    confirmations = json.loads(args.confirmations.read_text(encoding='utf-8'))
    entries, audit = build(rows, confirmations)
    content = render(entries)
    _, errors, _ = loader.load_string(content)
    if errors:
        parser.exit(1, '\n'.join(e.message for e in errors) + '\n')
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'transactions.beancount').write_text('; Generated by ledger.build_fava; do not edit.\n' + content)
    (args.output / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    counts = Counter(item['disposition'] for item in audit)
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == '__main__':
    main()
