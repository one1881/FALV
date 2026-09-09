"""
一次性把数据库补全到 V1 MVP 生产级别:
1. Customer 从 1→20 家真实企业(各行业,完整工商信息)
2. Contract 给 33 条都补 customer_id + 合理 amount + signing_date + status 多样化 + 充实 content
3. 不动 schema(避免破坏向后兼容,缺失字段如 risk_score 后端会读 fallback)

可重复运行(已存在的 customer/contract 不会重复插入)
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime, timedelta
import random

from app.core.database import SessionLocal
from app.models.customer import Customer
from app.models.contract import Contract
from app.models.user import User
from sqlalchemy import text


# ===========================================
# 20 家真实样例企业(覆盖科技/制造/贸易/金融/医疗/教育/能源/服务 8 大行业,每家完整工商信息)
# ===========================================
SAMPLE_CUSTOMERS = [
    # 科技 5
    {"name": "云起科技有限公司", "code": "CUS-T001", "contact_person": "王志远", "phone": "010-88881234",
     "email": "wangzy@yunqi-tech.com", "address": "北京市海淀区中关村大街1号科技大厦8层",
     "legal_representative": "李明华", "unified_social_credit_code": "91110108000000001X"},
    {"name": "星河数据有限公司", "code": "CUS-T002", "contact_person": "刘晓晨", "phone": "021-58880101",
     "email": "liuxc@xinghe-data.com", "address": "上海市浦东新区张江高科园区科苑路200号",
     "legal_representative": "张敏", "unified_social_credit_code": "91310115000000002Y"},
    {"name": "数聚未来科技股份公司", "code": "CUS-T003", "contact_person": "陈昊", "phone": "0755-86660001",
     "email": "chenhao@datagather.com.cn", "address": "深圳市南山区科技园南区高新南一道",
     "legal_representative": "黄建国", "unified_social_credit_code": "91440300000000003Z"},
    {"name": "华讯集成股份有限公司", "code": "CUS-T004", "contact_person": "赵静怡", "phone": "010-59060999",
     "email": "zhao.jy@huaxun-it.com", "address": "北京市朝阳区建国门外大街甲9号",
     "legal_representative": "周文军", "unified_social_credit_code": "91110105000000004A"},
    {"name": "极云云计算有限公司", "code": "CUS-T005", "contact_person": "孙磊", "phone": "0571-88001234",
     "email": "sunlei@jiycloud.com", "address": "杭州市余杭区文一西路1818号",
     "legal_representative": "吴启明", "unified_social_credit_code": "91330100000000005B"},
    # 制造 4
    {"name": "智造精密机械有限公司", "code": "CUS-M001", "contact_person": "林志刚", "phone": "0575-83332222",
     "email": "linzg@zhizao-mfg.com", "address": "浙江省绍兴市柯桥区开发区",
     "legal_representative": "徐国华", "unified_social_credit_code": "91330600000000006C"},
    {"name": "华工智能装备股份公司", "code": "CUS-M002", "contact_person": "邓浩宇", "phone": "027-87555333",
     "email": "denghy@huagong-ie.com", "address": "武汉市东湖高新区光谷大道77号",
     "legal_representative": "高俊", "unified_social_credit_code": "91420100000000007D"},
    {"name": "鑫源材料科技有限公司", "code": "CUS-M003", "contact_person": "邱丽娟", "phone": "0519-86669999",
     "email": "qiulj@xinyuan-mat.com", "address": "江苏省常州市武进区遥观镇工业园",
     "legal_representative": "蒋百川", "unified_social_credit_code": "91320400000000008E"},
    {"name": "蓝海船舶工程有限公司", "code": "CUS-M004", "contact_person": "潘文武", "phone": "021-38888800",
     "email": "panww@bluemarine-eng.com", "address": "上海市崇明区长兴岛凤凰路",
     "legal_representative": "叶知秋", "unified_social_credit_code": "91310230000000009F"},
    # 贸易 3
    {"name": "万通进出口贸易有限公司", "code": "CUS-W001", "contact_person": "冯国栋", "phone": "020-83338888",
     "email": "feng.gd@wantong-trade.com", "address": "广州市天河区珠江新城华夏路16号",
     "legal_representative": "钱进", "unified_social_credit_code": "91440101000000010G"},
    {"name": "宏达国际商贸集团", "code": "CUS-W002", "contact_person": "袁忠义", "phone": "0532-85880001",
     "email": "yuanzy@hongda-intl.com", "address": "青岛市市南区香港中路20号",
     "legal_representative": "曹云鹏", "unified_social_credit_code": "91370200000000011H"},
    {"name": "中盈物资贸易有限公司", "code": "CUS-W003", "contact_person": "邓玉琴", "phone": "023-67890567",
     "email": "dengyq@zhongying-wz.com", "address": "重庆市江北区江北城西大街25号",
     "legal_representative": "崔志雄", "unified_social_credit_code": "91500100000000012J"},
    # 金融 2
    {"name": "中泰证券股份有限公司", "code": "CUS-F001", "contact_person": "梁志远", "phone": "0531-87999999",
     "email": "liangzy@zhongtai-sec.com", "address": "济南市市中区经七路86号",
     "legal_representative": "萧文豪", "unified_social_credit_code": "91370100000000013K"},
    {"name": "汇通商业保理有限公司", "code": "CUS-F002", "contact_person": "郝明珠", "phone": "021-50996677",
     "email": "haomz@huitong-factoring.com", "address": "上海市浦东新区世纪大道1568号",
     "legal_representative": "霍建华", "unified_social_credit_code": "91310115000000014L"},
    # 医疗 2
    {"name": "康宁医疗科技股份有限公司", "code": "CUS-H001", "contact_person": "邱文静", "phone": "021-50120000",
     "email": "qiuwj@kangning-med.com", "address": "上海市徐汇区漕宝路100号",
     "legal_representative": "段一鸣", "unified_social_credit_code": "91310104000000015M"},
    {"name": "仁和制药股份有限公司", "code": "CUS-H002", "contact_person": "夏志强", "phone": "0571-82118888",
     "email": "xiazq@renhe-pharma.com", "address": "杭州市滨江区江南大道4760号",
     "legal_representative": "尹天华", "unified_social_credit_code": "91330100000000016N"},
    # 教育 / 能源 / 服务 各 1
    {"name": "学海教育投资集团有限公司", "code": "CUS-E001", "contact_person": "时文澜", "phone": "010-82523333",
     "email": "shiwl@xuehai-edu.com", "address": "北京市西城区西直门外大街1号",
     "legal_representative": "甘雨", "unified_social_credit_code": "91110102000000017P"},
    {"name": "绿源新能源股份有限公司", "code": "CUS-N001", "contact_person": "项明阳", "phone": "010-59998888",
     "email": "xiangmy@lvyuan-ne.com", "address": "北京市经济技术开发区荣华南路13号",
     "legal_representative": "阮学农", "unified_social_credit_code": "91110302000000018Q"},
    {"name": "联运物流服务股份有限公司", "code": "CUS-S001", "contact_person": "邬思源", "phone": "021-58320999",
     "email": "wusy@union-logistics.com", "address": "上海市虹口区四川北路1350号",
     "legal_representative": "云清扬", "unified_social_credit_code": "91310109000000019R"},
    {"name": "致远法律咨询服务有限公司", "code": "CUS-S002", "contact_person": "宁思敏", "phone": "020-38770199",
     "email": "ningsm@zhiyuan-legal.com", "address": "广州市天河区天河北路233号",
     "legal_representative": "段和平", "unified_social_credit_code": "91440101000000020S"},
]


# ===========================================
# 4 种合同类型×5-6 个历史样本 = 20+ 条历史合同(供相似检索)
# ===========================================

def gen_sales_template(name: str, counterparty: str, amount: float) -> str:
    return f"""# 销售合同

合同编号:{name}
签订地点:中国
签订日期:____年____月____日

**甲方(销售方):** 智契数字科技(上海)有限公司
**乙方(购买方):** {counterparty}

鉴于甲方同意销售、乙方同意购买本合同所述标的物,双方依据《中华人民共和国民法典》及相关法律法规,本着平等自愿、诚实信用的原则,经友好协商,达成如下协议:

## 第一条 销售标的与数量
本合同项下销售标的为:**软件系统及相关服务**(包括软件系统一套、技术文档、安装部署服务及一年期技术支持)。标的物具体规格、技术参数以双方签字盖章确认的技术协议为准。本条款依据《民法典》第五百九十五条。

## 第二条 合同金额
本合同总金额为人民币 **{amount:,.2f}** 元(大写:____),含税价格,已包含标的物本身价格、包装、运输、装卸、安装调试、培训、质保期内售后服务等全部费用。

## 第三条 价款与付款方式
| 付款节点 | 付款比例 | 付款金额(元) | 付款条件 |
|---------|---------|------------|---------|
| 第一期:合同签订生效后 | 30% | {amount*0.3:,.2f} | 合同生效且收到合规发票后 5 个工作日内 |
| 第二期:标的物验收合格后 | 70% | {amount*0.7:,.2f} | 通过验收并收到合规发票后 5 个工作日内 |

## 第四条 交付与转移
4.1 交付时间:合同生效之日起 **30 个工作日** 内完成全部交付。
4.2 交付方式:甲方负责运送至乙方指定地点并安装调试。
4.3 验收:乙方应在收到通知后 10 个工作日内组织验收。

## 第五条 质量保证
质保期自验收合格之日起 12 个月。质保期内出现质量问题,甲方应在 48 小时内响应,7 个工作日内免费维修或更换。

## 第六条 违约责任
依据《民法典》第五百七十七条。甲方逾期交付的,每逾期一日按合同总金额 0.05% 支付违约金;乙方逾期付款的,按逾期金额 0.05% 支付违约金。

## 第七条 争议解决
因本合同引起的争议,双方应友好协商解决;协商不成的,提交上海国际经济贸易仲裁委员会仲裁。

---

甲方(盖章)_____________  日期_____________
乙方(盖章)_____________  日期_____________
"""


def gen_purchase_template(name: str, counterparty: str, amount: float, goods: str) -> str:
    return f"""# 采购合同

合同编号:{name}
签订地点:中国
签订日期:____年____月____日

**甲方(采购方):** 智契数字科技(上海)有限公司
**乙方(供应方):** {counterparty}

根据《中华人民共和国民法典》及有关法律法规,甲乙双方就采购事宜达成如下协议:

## 第一条 采购标的
乙方向甲方提供以下货物/服务:**{goods}**

## 第二条 合同金额
合同总金额:**人民币 {amount:,.2f} 元**(大写:____)

## 第三条 付款方式
- 预付款:合同生效后 5 个工作日内支付 30% ({amount*0.3:,.2f} 元)
- 到货款:货物到场并签收合格后 10 个工作日内支付 60% ({amount*0.6:,.2f} 元)
- 质保金:验收合格 6 个月后无质量问题支付 10% ({amount*0.1:,.2f} 元)

## 第四条 交付安排
- 交付时间:合同生效后 45 日历日内
- 交付地点:甲方指定仓库(上海市浦东新区张江高科技园区)
- 运输方式:乙方负责运输并承担费用,运输保险由乙方办理

## 第五条 质量保证
- 乙方保证提供的货物全新、符合国家标准及合同约定的技术规格
- 质保期:自验收合格之日起 24 个月
- 质保期内出现质量问题,乙方应在 48 小时内响应,15 日内完成维修或更换

## 第六条 验收
- 甲方应在货物到场后 7 个工作日内组织验收
- 验收标准按双方确认的技术规格书

## 第七条 违约责任
依据《民法典》第五百七十七条。乙方逾期交货的,每逾期一日按合同总额 0.05% 支付违约金;甲方逾期付款的,按逾期金额 0.05% 支付违约金。违约金累计不超过合同总额的 10%。

## 第八条 知识产权
乙方保证拥有或合法授权相关产品的知识产权,不侵犯任何第三方权利。

## 第九条 争议解决
协商不成的,提交上海国际经济贸易仲裁委员会仲裁,仲裁裁决为终局裁决。

---

甲方(盖章)_____________  日期_____________
乙方(盖章)_____________  日期_____________
"""


def gen_service_template(name: str, counterparty: str, amount: float, service: str) -> str:
    return f"""# 服务合同

合同编号:{name}
签订地点:中国
签订日期:____年____月____日

**甲方(委托方):** 智契数字科技(上海)有限公司
**乙方(服务方):** {counterparty}

根据《中华人民共和国民法典》及有关法律法规,双方就以下服务事项达成一致:

## 第一条 服务内容
**服务事项:** {service}

## 第二条 服务期限
本合同服务期限为自 ____ 年 ____ 月 ____ 日起至 ____ 年 ____ 月 ____ 日止,共 12 个月。

## 第三条 服务费用
本合同服务费用合计:**人民币 {amount:,.2f} 元**(含税)。按季度支付,每季度 {amount/4:,.2f} 元。

## 第四条 双方义务
- 甲方:按时支付服务费用、提供必要的工作条件、对乙方工作给予合理配合
- 乙方:按约定提供高质量服务、保护甲方商业秘密、定期汇报工作进展

## 第五条 知识产权
服务过程中产生的所有成果(包括但不限于代码、文档、报告)知识产权归甲方所有。

## 第六条 保密条款
双方对合作过程中知悉的对方商业秘密、技术信息及未公开信息负有保密义务,保密期限至本合同终止后 3 年。

## 第七条 违约责任
依据《民法典》第五百七十七条。任何一方违约应赔偿对方因此造成的全部直接损失。

## 第八条 合同解除
任何一方违约且在对方书面通知后 30 日内未予纠正的,对方有权单方解除合同。

---

甲方(盖章)_____________  日期_____________
乙方(盖章)_____________  日期_____________
"""


def gen_lease_template(name: str, counterparty: str, amount: float, premises: str) -> str:
    return f"""# 租赁合同

合同编号:{name}
签订地点:中国
签订日期:____年____月____日

**出租人(甲方):** 智契数字科技(上海)有限公司
**承租人(乙方):** {counterparty}

## 第一条 租赁标的
甲方将位于 **{premises}** 的房屋(以下简称\"该房屋\")出租给乙方使用。

## 第二条 租赁期限
租赁期限:自 ____ 年 ____ 月 ____ 日起至 ____ 年 ____ 月 ____ 日止,共 36 个月。

## 第三条 租金与支付方式
- 月租金:**人民币 {amount/12:,.2f} 元**(大写:____)
- 季度租金:**人民币 {amount/4:,.2f} 元**
- 年租金:**人民币 {amount:,.2f} 元**
- 支付方式:每季度首日前 5 个工作日内支付当季租金

押金:两个月租金,合计 {amount*2/12:,.2f} 元,合同签订时一次性支付,租赁期满无违约行为无息退还。

## 第四条 用途限制
乙方租赁该房屋仅用于 **办公经营**,不得用于违法活动,不得擅自转租、转借。

## 第五条 房屋维修
- 房屋及附属设施在租赁期间的一般性维护由乙方负责
- 房屋主体结构的维修由甲方负责

## 第六条 合同解除与终止
- 租赁期满,乙方应在 7 日内腾空并返还房屋
- 乙方逾期返还的,按日租金的 200% 支付占有使用费

## 第七条 争议解决
协商不成的,提交房屋所在地人民法院诉讼解决。

---

甲方(盖章)_____________  日期_____________
乙方(盖章)_____________  日期_____________
"""


def gen_employment_template(name: str, counterparty: str, amount: float) -> str:
    """劳动合同,counterparty=劳动者姓名"""
    return f"""# 劳动合同

合同编号:{name}
签订地点:上海

**甲方(用人单位):** 智契数字科技(上海)有限公司
**乙方(劳动者):** {counterparty}

根据《中华人民共和国劳动法》《中华人民共和国劳动合同法》及有关规定,甲乙双方在平等自愿的基础上,订立本合同。

## 第一条 合同期限
本合同为 **固定期限劳动合同**,期限 3 年。
- 合同生效日期:____ 年 ____ 月 ____ 日
- 合同终止日期:____ 年 ____ 月 ____ 日
- 试用期:6 个月

## 第二条 工作内容与地点
- 工作岗位:**高级软件工程师**
- 工作部门:技术研发部
- 工作地点:上海市浦东新区

## 第三条 工时制度
- 执行标准工时制,每日工作 8 小时,每周工作 40 小时
- 因工作需要加班,按公司《加班管理制度》支付加班费

## 第四条 劳动报酬
- 月工资(税前):人民币 **{amount:,.2f}** 元
- 试用期工资:月工资的 80%
- 发薪日:每月 15 日

## 第五条 社会保险与福利
- 甲方按国家和上海市规定为乙方办理并缴纳社会保险(养老/医疗/失业/工伤/生育)和住房公积金
- 除法定福利外,乙方享受公司年度体检、节日福利等

## 第六条 保密与竞业限制
- 乙方在职及离职后 2 年内,对甲方商业秘密负有保密义务
- 涉及核心技术的岗位,甲方可与乙方单独签订竞业限制协议,补偿金另行约定

## 第七条 合同解除与终止
按《劳动合同法》第三十六条至第四十四条相关规定执行。

## 第八条 争议解决
本合同发生争议的,双方协商解决;协商不成的,提交上海市劳动争议仲裁委员会仲裁。

---

甲方(盖章)_____________  日期_____________
乙方(签字)_____________  日期_____________
"""


# 历史合同样本
SAMPLE_HISTORICAL_CONTRACTS = [
    # 销售合同 6 条
    {"type": "sales", "tpl": gen_sales_template, "customer_code": "CUS-T002", "amount": 480000, "extra": "数据中台及可视化模块" },
    {"type": "sales", "tpl": gen_sales_template, "customer_code": "CUS-T003", "amount": 1200000, "extra": "AI 智能合同审查平台" },
    {"type": "sales", "tpl": gen_sales_template, "customer_code": "CUS-T004", "amount": 850000, "extra": "企业法务管理系统" },
    {"type": "sales", "tpl": gen_sales_template, "customer_code": "CUS-T005", "amount": 320000, "extra": "云资源集成及迁移服务" },
    {"type": "sales", "tpl": gen_sales_template, "customer_code": "CUS-H001", "amount": 680000, "extra": "医疗数据治理平台" },
    {"type": "sales", "tpl": gen_sales_template, "customer_code": "CUS-F001", "amount": 1850000, "extra": "金融合同风控系统" },
    # 采购合同 4 条
    {"type": "purchase", "tpl": gen_purchase_template, "customer_code": "CUS-M001", "amount": 380000, "extra": "精密机械零部件(轴承/齿轮)" },
    {"type": "purchase", "tpl": gen_purchase_template, "customer_code": "CUS-M002", "amount": 920000, "extra": "智能装备制造原材料" },
    {"type": "purchase", "tpl": gen_purchase_template, "customer_code": "CUS-M003", "amount": 245000, "extra": "新型复合材料(碳纤维)" },
    {"type": "purchase", "tpl": gen_purchase_template, "customer_code": "CUS-S001", "amount": 156000, "extra": "仓储设备及物流器具" },
    # 服务合同 5 条
    {"type": "service", "tpl": gen_service_template, "customer_code": "CUS-T002", "amount": 360000, "extra": "数据中台运维服务(年度)" },
    {"type": "service", "tpl": gen_service_template, "customer_code": "CUS-H002", "amount": 240000, "extra": "GMP 合规咨询及体系搭建" },
    {"type": "service", "tpl": gen_service_template, "customer_code": "CUS-W001", "amount": 180000, "extra": "海外市场调研及合规服务" },
    {"type": "service", "tpl": gen_service_template, "customer_code": "CUS-F002", "amount": 420000, "extra": "保理业务系统运维" },
    {"type": "service", "tpl": gen_service_template, "customer_code": "CUS-E001", "amount": 560000, "extra": "智慧校园软件 SaaS 服务" },
    # 租赁合同 3 条
    {"type": "lease", "tpl": gen_lease_template, "customer_code": "CUS-S002", "amount": 396000, "extra": "上海市静安区南京西路 1788 号 1808 室" },
    {"type": "lease", "tpl": gen_lease_template, "customer_code": "CUS-W003", "amount": 240000, "extra": "重庆市江北区观音桥商圈办公位" },
    {"type": "lease", "tpl": gen_lease_template, "customer_code": "CUS-N001", "amount": 480000, "extra": "北京经济技术开发区厂房 B 区" },
    # 劳动合同 3 条
    {"type": "employment", "tpl": gen_employment_template, "customer_code": None, "amount": 35000, "extra": "周明宇" },
    {"type": "employment", "tpl": gen_employment_template, "customer_code": None, "amount": 45000, "extra": "林晓彤" },
    {"type": "employment", "tpl": gen_employment_template, "customer_code": None, "amount": 28000, "extra": "陈思源" },
]


def gen_contract_number(prefix: str, idx: int) -> str:
    return f"{prefix}-HIST-{2024}{idx:03d}"


def upsert_customers(db):
    inserted = 0
    for c in SAMPLE_CUSTOMERS:
        existing = db.query(Customer).filter(Customer.code == c["code"]).first()
        if existing:
            # 补全空字段
            for k, v in c.items():
                if not getattr(existing, k, None):
                    setattr(existing, k, v)
            continue
        db.add(Customer(**c))
        inserted += 1
    db.commit()
    return inserted


def generate_content_from_type(contract_type: str, title: str, customer_name: str) -> str:
    """给现存但 content<100 字的合同按其类型生成一份填充文"""
    if contract_type in ("sales", "销售合同"):
        return gen_sales_template(title, customer_name, 100000 + random.randint(0, 9) * 50000)
    if contract_type in ("purchase", "采购合同"):
        return gen_purchase_template(title, customer_name, 80000 + random.randint(0, 15) * 30000, "相关货物/服务")
    if contract_type in ("service", "服务合同"):
        return gen_service_template(title, customer_name, 120000 + random.randint(0, 8) * 40000, "相关技术服务")
    if contract_type in ("lease", "租赁合同"):
        return gen_lease_template(title, customer_name, 240000 + random.randint(0, 6) * 60000, "具体地址以合同附件为准")
    if contract_type in ("employment", "劳动合同"):
        return gen_employment_template(title, customer_name, 30000)
    if contract_type in ("nda", "保密协议"):
        return f"""# 保密协议

**披露方(甲方):** 智契数字科技(上海)有限公司
**接收方(乙方):** {customer_name or '—'}

## 第一条 保密信息范围
本协议保密信息包括但不限于:技术方案、源代码、算法、客户名单、财务数据、商业计划及任何标注\"秘密\"或\"机密\"的信息。

## 第二条 保密义务
未经披露方书面同意,接收方不得向任何第三方披露、使用或允许他人使用保密信息。

## 第三条 保密期限
本协议保密期限至本合同终止后 3 年。

## 第四条 违约责任
依据《民法典》第五百七十七条。如违反本协议,违约方应赔偿对方全部损失。

---

甲方(盖章)_____________  日期_____________
乙方(盖章)_____________  日期_____________
"""
    return f"本合同类型 [{contract_type}] 的历史记录,甲乙双方于 ____ 年签订,合同金额 ____ 元。具体条款以原合同为准。"


def fill_existing_contracts(db):
    """给现有 contract 补 customer_name/amount/signing_date/status/customer_id/content"""
    customers_by_code = {c.code: c for c in db.query(Customer).filter(Customer.code.isnot(None)).all()}
    # 实际企业没有固定 code,就用名称匹配
    customers_by_name = {c.name: c for c in db.query(Customer).all()}

    contracts = db.query(Contract).all()
    fixed = 0
    now = datetime.now()
    for i, c in enumerate(contracts):
        # 关联客户
        if c.customer_name and c.customer_name in customers_by_name and not c.customer_id:
            cust = customers_by_name[c.customer_name]
            c.customer_id = cust.id
            fixed += 1
        elif not c.customer_id and customers_by_code:
            # 没 customer_name 也没 id,随便指一家(相似检索能用)
            cust = list(customers_by_code.values())[i % len(customers_by_code)]
            c.customer_id = cust.id
            c.customer_name = cust.name
            fixed += 1

        # 补 amount
        if c.amount is None:
            base = {"sales": 600000, "purchase": 400000, "service": 200000,
                    "lease": 300000, "employment": 30000, "nda": 50000}.get(c.contract_type, 200000)
            c.amount = base + random.randint(-3, 8) * 50000
            fixed += 1

        # signing_date 缺失就给一个 2024 年内的合理时间
        if c.signing_date is None:
            days_back = random.randint(30, 600)
            c.signing_date = now - timedelta(days=days_back)
            if c.start_date is None:
                c.start_date = c.signing_date
            if c.end_date is None and c.contract_type not in ("employment", "nda"):
                c.end_date = c.signing_date + timedelta(days=365)
            fixed += 1

        # status 多样化(让前端各 tab 都有数据)
        statuses = ["draft", "pending", "approved", "active", "expired"]
        if c.status and c.status not in ("draft", "pending"):
            continue
        # 重新分配状态:按 created_at 时间远近,越早的越成熟
        if c.signing_date:
            # PostgreSQL 的 timezone 列可能返回带时区时间，统一到合同时间的时区后再计算。
            compare_now = (
                datetime.now(c.signing_date.tzinfo)
                if c.signing_date.tzinfo
                else now
            )
            days_old = (compare_now - c.signing_date).days
            if days_old > 540:
                c.status = random.choice(["active", "expired"])
            elif days_old > 200:
                c.status = random.choice(["approved", "active"])
            elif days_old > 60:
                c.status = random.choice(["approved", "pending", "active"])
            else:
                c.status = "draft"
            fixed += 1

        # 充实 content(若空或太短)
        if not c.content or len(c.content) < 100:
            try:
                c.content = generate_content_from_type(c.contract_type, c.title, c.customer_name or "—")
                fixed += 1
            except Exception as e:
                print(f"生成合同[{c.id}]content失败: {e}")
    db.commit()
    return fixed


def insert_historical_contracts(db):
    """插入 21 条高质量历史合同(供相似检索命中)"""
    users = db.query(User).all()
    if not users:
        print("无用户,跳过历史合同插入")
        return 0
    admin_user = users[0]

    customers_by_code = {c.code: c for c in db.query(Customer).filter(Customer.code.isnot(None)).all()}

    inserted = 0
    for i, h in enumerate(SAMPLE_HISTORICAL_CONTRACTS):
        cust = None
        if h["customer_code"]:
            cust = customers_by_code.get(h["customer_code"])
            if not cust:
                # 自动创建
                cust = Customer(
                    name=f"样本客户-{h['customer_code']}",
                    code=h["customer_code"],
                    contact_person="联系人",
                    phone="021-50000000",
                    address="上海",
                )
                db.add(cust)
                db.flush()
                customers_by_code[cust.code] = cust

        number = gen_contract_number(h["type"].upper()[:3], i + 1)
        # 跳过已存在
        if db.query(Contract).filter(Contract.contract_number == number).first():
            continue

        # 生成正文: type=="employment" 时 extra 是劳动者姓名,否则一般指标的
        if h["type"] == "employment":
            content = gen_employment_template(number, h["extra"], h["amount"])
            customer_name = "智契数字科技(上海)有限公司"  # 公司本身
            title = f"{h['extra']}-劳动合同"
        elif h["type"] == "lease":
            content = gen_lease_template(number, cust.name if cust else "—", h["amount"], h["extra"])
            customer_name = cust.name if cust else "—"
            title = f"房屋租赁合同-{cust.name if cust else '—'}"
        elif h["type"] == "service":
            content = gen_service_template(number, cust.name if cust else "—", h["amount"], h["extra"])
            customer_name = cust.name if cust else "—"
            title = f"服务合同-{cust.name if cust else '—'}"
        elif h["type"] == "purchase":
            content = gen_purchase_template(number, cust.name if cust else "—", h["amount"], h["extra"])
            customer_name = cust.name if cust else "—"
            title = f"采购合同-{cust.name if cust else '—'}"
        else:  # sales
            content = gen_sales_template(number, cust.name if cust else "—", h["amount"])
            customer_name = cust.name if cust else "—"
            title = f"销售合同-{cust.name if cust else '—'}"

        months_ago = random.randint(2, 18)
        signing_date = datetime.now() - timedelta(days=months_ago * 30)

        c = Contract(
            contract_number=number,
            title=title,
            contract_type=h["type"],
            status=random.choice(["approved", "active", "expired"]) if months_ago > 6 else "active",
            customer_id=cust.id if cust else None,
            customer_name=customer_name,
            amount=h["amount"],
            signing_date=signing_date,
            start_date=signing_date,
            end_date=signing_date + timedelta(days=365),
            content=content,
            created_by=admin_user.id,
        )
        db.add(c)
        inserted += 1

    db.commit()
    return inserted


def main():
    print("=" * 60)
    print("数据库补全(20 家企业 + 历史合同 + 既存合同归一)")
    print("=" * 60)

    with SessionLocal() as db:
        # 先 customers,再合同(合同引用 customer_id)
        ins_c = upsert_customers(db)
        print(f"\n[1] Customer upsert: 新增 {ins_c} 家, 总数 {db.query(Customer).count()}")

        ins_h = insert_historical_contracts(db)
        print(f"[2] 历史合同: 新增 {ins_h} 条")

        fixed = fill_existing_contracts(db)
        print(f"[3] 既存合同补全字段: 修改 {fixed} 处")

        # 最终统计
        print("\n=== 补全后数据量 ===")
        print(f"  customers: {db.query(Customer).count()}")
        print(f"  contracts: {db.query(Contract).count()}")
        print(f"  contract total_amount: CNY {sum(c.amount or 0 for c in db.query(Contract).all()):,.2f}")
        # content 长度分布
        rows = db.execute(text("SELECT LENGTH(COALESCE(content,'')) FROM contracts")).all()
        lens = [r[0] for r in rows]
        print(f"  content 长度: min={min(lens)} max={max(lens)} 中位数≈{sorted(lens)[len(lens)//2]}")

        # 状态分布
        rows = db.execute(text("SELECT status, COUNT(*) FROM contracts GROUP BY status")).all()
        print("  status 分布:", [(s, n) for s, n in rows])
        rows = db.execute(text("SELECT contract_type, COUNT(*) FROM contracts GROUP BY contract_type")).all()
        print("  类型分布:", [(t, n) for t, n in rows])


if __name__ == "__main__":
    main()
