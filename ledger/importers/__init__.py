from .alipay_importer import AlipayImporter
from .wechat_importer import WechatImporter
from .cmb_importer import CMBImporter
from .cib_debit_importer import CIBDebitImporter
from .cib_credit_importer import CIBCreditImporter

IMPORTERS = [AlipayImporter(), WechatImporter(), CMBImporter(), CIBDebitImporter(), CIBCreditImporter()]


def identify(filepath):
    matches = [importer for importer in IMPORTERS if importer.identify(filepath)]
    if len(matches) != 1:
        raise ValueError(f'{filepath}: expected one importer, found {len(matches)}')
    return matches[0]
