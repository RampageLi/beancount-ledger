# Beancount ledger with Fava

本地解析五类账单，生成可重复构建的账本并在 Fava 中查看。账户名称全部为英文，界面、商户原文和确认说明保留中文。

## 安装与使用

要求 Python 3.10+，在项目根目录运行：

```sh
make install
make serve                  # 生成、校验，并在本机 5001 端口启动 Fava
# make serve PORT=5010       # 自选端口
make check                  # 更新账单后重新生成并校验，Fava 自动加载
```

访问 <http://127.0.0.1:5001>。主入口为 `ledger/main.beancount`，时间筛选可输入 `2026-09`。

原始账单放在 `ledger/data`，输出在 `ledger/output`，两者均已 gitignore。所有解析在本地进行；不要把生成文件直接当作人工编辑文件，重建会覆盖它们。

## 五类 importer

| 类 | 输入 |
| --- | --- |
| `AlipayImporter` | 支付宝 CSV，UTF-8 / GB18030，自动寻找表头 |
| `WechatImporter` | 微信支付 XLSX，支持 Excel 日期单元格 |
| `CMBImporter` | 招商银行借记卡文字型 PDF，支持跨页及换行商户 |
| `CIBDebitImporter` | 兴业银行借记卡人民币文字型 PDF，处理水印、表格换行、隐藏余额 |
| `CIBCreditImporter` | 兴业银行信用卡历史账单 XLSX，保留交易日与记账日 |

PDF 不支持扫描件 OCR。解析器针对现有导出模板，模板变化时需要调整。

```sh
.venv/bin/python -m ledger.importers ledger/data --month 2026-09 -o ledger/output/transactions.json
.venv/bin/python -m ledger.importers ledger/data --month 2026-09 --format csv -o ledger/output/transactions.csv
```

也可传入单文件。不指定月份则导出所有月份。`--month` 按交易日期筛选；招行只提供记账日期，采用记账日期。CSV 使用 UTF-8 BOM。

`parse_bill(path)` 返回 `list[Record]`；`to_dict()` 输出适合 JSON 的内容。`amount` 保留账单金额；`signed_amount` 为账户变动（支出负、收入正），无法判断方向时为 null。金额用 Decimal，序列化为十进制字符串；订单号保留文本。关闭交易不产生账户变动。支付宝明确的余额宝收益即使标注“不计收支”，也识别为正向变动。

每行保留原始字段、来源文件和位置。PDF 以页码及页内记录定位；CSV 为逻辑记录号，含引号的多行字段算一条。解析失败时不写入部分结果。

各 importer 提供 `identify(path)`、`parse_bill(path)`、`extract(path, existing=None)`。`extract` 是简单的待核对草稿接口，对侧为 `Equity:Pending`，有来源订单号时跳过已有交易；它不执行下面的完整 Fava 合并和分类流程。

## 入账与去重口径

完整流程在 `ledger/build_fava.py`，输出：

- `ledger/output/fava/transactions.beancount`：账户声明、交易、招行日末余额断言及未解决记录备注。
- `ledger/output/fava/audit.json`：每条原始记录的去向、匹配关系、采用的政策和账户。

当前采用用户指定的政策：

1. 余额宝收益全部进入 `Income:Investment:YuEBao`，对侧为 `Assets:CN:Alipay:YuEBao`，采用到账日期。
2. 支付宝、微信的兴业信用卡消费优先匹配银行流水。先要求卡号、币种、金额、交易日和分钟一致；没有精确匹配时，允许规范化商户名相同且时间差不超过 120 秒。双方必须唯一。银行记账日期可以在下个月，匹配依据仍为交易日期。
3. 没有银行匹配候选的信用卡消费，按平台账单金额进入 `Expenses:CreditCard:Unmatched`，同时增加信用卡负债。后续把补充银行流水放入数据目录并重建，匹配成功后将由银行交易替代原临时分类，不重复计支出。存在多个候选时保留备注，避免重复入账；跨日或商户信息不一致等无法安全匹配的情况仍需人工核对。
4. 余额宝/账户余额/微信零钱与红包或优惠券组合支付，按账单金额全额扣减对应资金账户并计支出，不拆分优惠，也不另记优惠收入。支持红包、现金抵价券、到店支付立减券、支付立减优惠；多个真实资金账户混合支付仍需核对。
5. 内部转账、信用卡还款不计损益，先使用 `Assets:Transfers:Pending` 中转；退款冲减费用；不明收入先挂 `Equity:Pending`。已确认的生活费、婚礼随礼等覆盖自动转账分类。
6. 招行期初余额从首笔流水反推，并逐日校验余额。其余账户缺少期初余额，资产负债表不是完整净资产。组合优惠支付按用户指定口径扣减余额，可能与实际现金扣款有差异，后续账户对账需注意。

当前五份样例：361 条原始记录中，276 条生成交易（271 条待核对、5 条人工确认），83 条平台记录匹配到银行交易，2 条只保留备注（120 元余额宝自动转入、16.90 元关闭订单）。另外生成一笔招行期初余额。

本次补记：30 笔余额宝收益 1.54 元；3 笔未匹配信用卡支出 380.07 元；5 笔组合支付支出 178.91 元。宇游 30 元的时间差匹配已解决，不再重复入账。

批量生成会重建全部已提供月份。带相同来源订单号的记录可以去重；银行无订单号的重叠导出不自动推断去重，请避免重复放入重叠账单。所有原始行仍保存在 audit.json 中。

## 英文账户与细分类目

五大根账户为 `Assets`、`Liabilities`、`Equity`、`Income`、`Expenses`。账户配置位于 `ledger/config/accounts.py`，分类规则集中于 `ledger/utils/transaction_classifier.py`；legacy `cmb_classifier(dict)` 也复用这些规则。

| 内容 | 账户示例 |
| --- | --- |
| 银行、钱包、信用卡 | `Assets:CN:Bank:CMB`、`Assets:CN:Alipay:YuEBao`、`Liabilities:CN:Bank:CIB` |
| 工资、公积金、利息 | `Income:Salary`、`Income:HousingFund`、`Income:Interest` |
| 余额宝收益、闲鱼收入 | `Income:Investment:YuEBao`、`Income:SecondhandSales` |
| 公司餐饮、咖啡、快餐、餐厅 | `Expenses:Food:WorkMeals` / `Coffee` / `FastFood` / `Restaurants` |
| 地铁、公交、单车、打车、火车、机票 | `Expenses:Transport:Subway` / `BusAndTram` / `BikeSharing` / `Taxi` / `Rail` / `Flights` |
| 超市、日用品、网购、衣服 | `Expenses:Shopping:Groceries` / `HouseholdGoods` / `Online` / `Clothing` |
| 攀岩 | `Expenses:Fitness:Climbing` |
| 游戏、软件订阅 | `Expenses:Leisure:Games` / `Subscriptions` |
| 酒店、景点、证件 | `Expenses:Travel:Hotels` / `Attractions` / `Documents` |
| 水电、话费、生活费 | `Expenses:Household:Utilities` / `Phone`、`Expenses:LivingAllowance` |
| 报销、随礼、其他 | `Expenses:Reimbursable`、`Expenses:Gifts:Wedding`、`Expenses:Other` |
| 未匹配信用卡消费、待分类 | `Expenses:CreditCard:Unmatched`、`Expenses:Uncategorized` |

分类顺序：用户确认 > 明确商品摘要/具体商户 > 平台分类 > 待分类。不会把通用词“店”“有限公司”“美团”全部归为网购或餐饮。原始商户名称不做翻译。历史 `ledger/accounts.beancount` 账户名已转英文，但它未被主账本包含，历史余额也不与预览混用。

## 人工确认与 Fava 查询

人工确认持久保存在 `ledger/config/confirmations.json`，重建会重新应用。规则要求来源、时间、金额、币种、商户、摘要及可用订单号精确匹配一条记录；零匹配或多匹配停止生成。规则不依赖文件路径，不自动扩展到以后月份。

已确认五笔：生活费、公司报销、闲鱼收入、婚礼随礼、其他用途。人工确认交易标为 `*` / `#confirmed`，其余自动分类为 `!` / `#review`。是否计入损益取决于 Income/Expenses 分录，而不是确认标记。公司报销冲减费用，尚未关联原垫付支出。

Fava 侧栏查询包含“待核对交易”“待核对转账”“未匹配信用卡消费”。主账本语言仍为中文，账户名称均为英文。

## 验证

```sh
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
make check
```

测试覆盖解析、金额精度、退款与负债方向、余额衔接、PDF 水印与换行、细分类目、人工确认、优惠账单金额、收益补记、延迟银行流水去重、英文账户以及 Fava 页面加载。私有原始账单缺失时跳过对应集成测试。
