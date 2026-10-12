"""Shared classification for Fava and legacy CMB callers.

Specific product/merchant rules precede platform categories; ambiguous merchants
remain uncategorized. Transfers and refunds are not new expenses/income.
"""
from ledger.config.accounts import account_name, INVESTMENT_INCOME

PENDING = account_name('Equity:Pending')
TRANSFER = account_name('Assets:Transfers:Pending')

# Ordered, concrete keywords. Do not classify generic '有限公司', '店', '美团' as shopping.
RULES = [
 ('Expenses:Fitness:Climbing', ('岩时', '攀岩', '攀登中心')),
 ('Expenses:Travel:Hotels', ('酒店', '香港东隅', '住宿', 'hotel')),
 ('Expenses:Travel:Attractions', ('迪士尼尊享卡', '迪士尼乐园', '门票')),
 ('Expenses:Transport:Subway', ('轨道交通', '地铁', 'mtr corporation')),
 ('Expenses:Transport:BusAndTram', ('tramways', 'tram', 'bus', '公交')),
 ('Expenses:Transport:BikeSharing', ('单车', '先骑后付', '广州骑安')),
 ('Expenses:Transport:Taxi', ('滴滴出行', '打车', '出租车')),
 ('Expenses:Transport:Rail', ('12306', '中国铁路', '火车票', '高铁')),
 ('Expenses:Transport:Flights', ('机票', '航空', 'flight')),
 ('Expenses:Household:Utilities', ('电力公司', '电费', '水费', '燃气')),
 ('Expenses:Household:Phone', ('手机充值', '话费', '中国移动')),
 ('Expenses:Travel:Documents', ('出入境证件费', '签证')),
 ('Expenses:Leisure:Games', ('游戏充值', '盛趣游戏')),
 ('Expenses:Leisure:Subscriptions', ('icloud', 'app store', 'apple music')),
 ('Expenses:Shopping:Clothing', ('优衣库',)),
 ('Expenses:Food:WorkMeals', ('百度简单支付',)),
 ('Expenses:Shopping:Groceries', ('正大优鲜', '优家便利', '智能售货', '超市', '山姆', 'samsclub', '盒马', '便利店', '7-eleven', '7‑eleven', '7 6 2eleven')),
 ('Expenses:Food:Coffee', ('咖啡', 'coffee', 'starbucks', '星巴克', 'm stand')),
 ('Expenses:Food:FastFood', ('麦当劳', 'mcdonald', '肯德基', 'kfc')),
 ('Expenses:Food:Restaurants', ('餐饮', '烧烤', '云南菜', '生蚝', '水煮鱼', '涮肉', '炸酱面', '峨嵋酒家', 'noodle', 'korean', 'restaurant')),
 ('Expenses:Shopping:HouseholdGoods', ('胶水胶带', '高露洁')),
 ('Expenses:Shopping:Online', ('京东', '淘宝')),
]
CATEGORY_FALLBACK = {
 '餐饮美食': account_name('Expenses:Food'), '交通出行': account_name('Expenses:Transport'),
 '文化休闲': account_name('Expenses:Leisure'), '日用百货': 'Expenses:Shopping:HouseholdGoods',
 '服饰装扮': 'Expenses:Shopping:Clothing', '医疗健康': account_name('Expenses:Health'),
}


def classify_transaction(payee, narration, amount, category='', transaction_type=''):
    text = f'{payee} {narration}'.casefold()
    transfer_text = f'{narration} {transaction_type}'
    if any(word in transfer_text for word in ('转账', '汇款', '还款', '红包')):
        return TRANSFER
    refund = any(word in text for word in ('退款', '退货')) or category == '退款'
    if amount > 0 and not refund:
        if '余额宝-' in text and '-收益发放' in text:
            return INVESTMENT_INCOME
        if '公积金' in text:
            return account_name('Income:HousingFund')
        if '工资' in text:
            return account_name('Income:Salary')
        if '结息' in text:
            return account_name('Income:Interest')
        return PENDING
    for account, keywords in RULES:
        if any(word.casefold() in text for word in keywords):
            return account
    return CATEGORY_FALLBACK.get(category, account_name('Expenses:Uncategorized'))


def classify(row, enrichment=None):
    detail = enrichment or row
    return classify_transaction(
        row.payee + ' ' + detail.payee, row.narration + ' ' + detail.narration,
        row.signed_amount, detail.raw.get('交易分类', ''), detail.raw.get('交易类型', ''))


def cmb_classifier(data):
    """Compatible with the original dictionary/Series interface."""
    return classify_transaction(data['counter'], data['transaction_type'], data['amount'])
