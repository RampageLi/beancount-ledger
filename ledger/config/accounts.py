"""English account configuration shared by generation and Fava."""
ROOTS = {'assets': 'Assets', 'liabilities': 'Liabilities', 'equity': 'Equity',
         'income': 'Income', 'expenses': 'Expenses'}
OPTIONS = ''.join(f'option "name_{key}" "{value}"\n' for key, value in ROOTS.items())
OPTIONS += ''.join(f'option "{key}" "{value}"\n' for key, value in {
    'account_previous_balances': 'Previous-Balances',
    'account_previous_earnings': 'Previous-Earnings',
    'account_previous_conversions': 'Previous-Conversions',
    'account_current_earnings': 'Current-Earnings',
    'account_current_conversions': 'Current-Conversions',
    'account_unrealized_gains': 'Unrealized-Gains',
}.items())
INVESTMENT_INCOME = 'Income:Investment:YuEBao'
UNMATCHED_CARD_EXPENSE = 'Expenses:CreditCard:Unmatched'


def account_name(account):
    """Reject accidental non-English overrides before writing the ledger."""
    import re
    if not re.fullmatch(r'(Assets|Liabilities|Equity|Income|Expenses)(:[A-Z][A-Za-z0-9-]*)+', account):
        raise ValueError(f'Expected an English account name: {account}')
    return account
