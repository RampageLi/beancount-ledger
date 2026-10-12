from decimal import Decimal
import pytest
from ledger.utils.transaction_classifier import classify_transaction, cmb_classifier, classify
from ledger.importers.base import Record
from datetime import datetime


@pytest.mark.parametrize('payee,narration,amount,category,expected', [
 ('百度简单支付','快捷支付','-20','','Expenses:Food:WorkMeals'),
 ('北京住房公积金管理中心','代发住房公积金','8724','','Income:HousingFund'),
 ('北京百度网讯科技有限公司','代发工资','20000','','Income:Salary'),
 ('银行','账户结息','15.20','','Income:Interest'),
 ('公司','代发款项','50','','Equity:Pending'),
 ('某科技有限公司','支付','-20','','Expenses:Uncategorized'),
 ('美团','Meituan-岩时攀岩（回龙观店）','-90','文化休闲','Expenses:Fitness:Climbing'),
 ('美团','香港东隅-美团App','-3223.13','餐饮美食','Expenses:Travel:Hotels'),
 ('咖啡吧','度咖啡','-13.9','','Expenses:Food:Coffee'),
 ('肯德基','KFC','-42.4','','Expenses:Food:FastFood'),
 ('美团','先骑后付','-1.88','','Expenses:Transport:BikeSharing'),
 ('滴滴青桔单车','单车','-1.5','','Expenses:Transport:BikeSharing'),
 ('MTR Corporation Limited','travel ticket','-5','','Expenses:Transport:Subway'),
 ('BOC Credit Card (International) Limited','Bus','-40','','Expenses:Transport:BusAndTram'),
 ('中国铁路网络有限公司','火车票','-248.91','','Expenses:Transport:Rail'),
 ('飞猪','迪士尼乐园-双人同行票+餐饮券','-1256','文化休闲','Expenses:Travel:Attractions'),
 ('iCloud 由云上贵州运营','iCloud','-21','文化休闲','Expenses:Leisure:Subscriptions'),
 ('盛趣游戏','游戏充值','-100','文化休闲','Expenses:Leisure:Games'),
 ('国网北京市电力公司','生活缴费','-98.5','','Expenses:Household:Utilities'),
 ('招商银行','信用卡还款','-4245.47','','Assets:Transfers:Pending'),
 ('本人','转账','4245.47','','Assets:Transfers:Pending'),
 ('美团','退款-新京熹北京涮肉','16.9','退款','Expenses:Food:Restaurants'),
 ('未知商户','退款','10','退款','Expenses:Uncategorized'),
 ('高露洁京东自营旗舰店','快捷支付','-53.79','','Expenses:Shopping:HouseholdGoods'),
 ('优衣库','购买服装','-99','','Expenses:Shopping:Clothing'),
])
def test_specific_classification(payee, narration, amount, category, expected):
    assert classify_transaction(payee, narration, Decimal(amount), category) == expected


def test_bank_and_platform_description_are_both_used():
    bank = Record('cib_credit','bank',1,datetime(2026,9,13),Decimal('3223.13'),
                  signed_amount=Decimal('-3223.13'),payee='支付宝快捷--北京三快在线科技有限公司')
    detail = Record('alipay','platform',1,bank.date,bank.amount,narration='香港东隅-美团App',raw={'交易分类':'餐饮美食'})
    assert classify(bank, detail) == 'Expenses:Travel:Hotels'


def test_legacy_cmb_interface():
    assert cmb_classifier({'counter':'百度简单支付', 'transaction_type':'快捷支付', 'amount':Decimal('-20')}) == 'Expenses:Food:WorkMeals'
