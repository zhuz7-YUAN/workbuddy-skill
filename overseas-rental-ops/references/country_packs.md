# 国家包（Country Pack）：把通用引擎落到具体国家

## 设计原则

本技能分两层：

- **核心引擎（国家无关）**：抓取 → 核验六字段 → 一次问全 → 台账 → 前置门禁。
  这一层在任何国家都成立，**不要为了"通用"把它改软**。
- **国家包（国家相关）**：税号叫什么、押金上限、担保机制、合同类型、登记义务、常用平台、
  合同注册方式。这一层**必须按国家替换**，换国家就是换一个包。

一份文档假装通吃全欧，结果就是每个国家都写不对——那是废物，不是通用。

## 国家包的六个槽位（换国家时逐项替换）

| 槽位 | 作用 | 为什么关键 |
|---|---|---|
| ① 身份号 | 租房/开户/办居留要的那种号 | 没它很多房东直接拒你 |
| ② 担保机制 | 房东凭什么相信你会付钱 | 这是外国学生**最大的卡点** |
| ③ 押金惯例 | 几个月、能不能退、什么时候退 | 决定你要备多少现金 |
| ④ 合同类型 | 哪种能签短租 | 决定 4–6 个月的可行性 |
| ⑤ 登记义务 | 落地后必须向谁登记 | 不做会连带影响居留/银行/医保 |
| ⑥ 主要平台 | 房源在哪找 | 决定抓取清单 |

> ⚠️ **各国具体数字与法规以当地最新官方规定为准。**
> 下表是"该核实什么 + 已知的大致情况"，用于**建立核实清单**，不作为法律依据。
> 每换一个国家，先按本表逐项去当地官方渠道确认一遍，再把确认结果写回本文件对应行。

## 欧洲主要国家对照（结构速查）

### 意大利 Italy
| 槽位 | 情况 |
|---|---|
| 身份号 | **Codice Fiscale**（税务局 Agenzia delle Entrate 办，当场出） |
| 担保机制 | 无国家担保；靠**押金 + 预付月租 + 学校介绍信**。外国学生常被要 garante |
| 押金惯例 | 常见 1–3 个月（习惯值，非法律硬上限）；退还条件**必须写进合同** |
| 合同类型 | `transitorio`（临时性质，可短）／`concordato`（约定租金）／`libero`。**优先找 transitorio** |
| 登记义务 | 合同须在 Agenzia delle Entrate 注册（imposta di registro）；办居留需注册合同 |
| 主要平台 | 学生板 trent.operauni.tn.it 类各地 Opera 板、subito.it、immobiliare.it、idealista.it、bakeca.it、Facebook 租房群 |

### 法国 France
| 槽位 | 情况 |
|---|---|
| 身份号 | 租房通常不强制；长期居住办居留时用 |
| 担保机制 | ★ **Visale**（Action Logement 提供的国家免费担保）——外国学生可申请，是最大杠杆；否则要法国籍 garant |
| 押金惯例 | 空屋约 1 个月、带家具约 2 个月（需核实最新规定） |
| 合同类型 | `bail`（含 meublé 带家具版，更适合短租） |
| 登记义务 | 无住址登记；但社保/医保需另办 |
| 主要平台 | leboncoin、SeLoger、LocService、Studapart、CROUS（学生宿舍） |

### 德国 Germany
| 槽位 | 情况 |
|---|---|
| 身份号 | Steuer-ID（税号）；租房本身通常不需要，但开户/工作要用 |
| 担保机制 | **Schufa 信用报告**（外国新生往往没有→ 用押金 + 收入/资助证明替代） |
| 押金惯例 | 法定上限约 3 个月冷租（Nettokaltmiete），常见分 3 期付 |
| 合同类型 | `Mietvertrag`；WG（合租）常见，走 Zwischenmiete（转租）能短租 |
| 登记义务 | ★ **Anmeldung**（到市政厅登记住址）——开户、税号、延签都要它，**落地第一周就办** |
| 主要平台 | WG-Gesucht、ImmobilienScout24、ImmoWelt、kleinanzeigen、Studenten-WG 群 |

### 西班牙 Spain
| 槽位 | 情况 |
|---|---|
| 身份号 | ★ **NIE**（外国人身份号）——租房、开户、办卡几乎都要 |
| 担保机制 | 押金 + 额外 garantía；有的房东要西班牙本地担保 |
| 押金惯例 | 通常 1 个月 fianza，可能再加 1–2 个月 garantía（需核实） |
| 合同类型 | `contrato de arrendamiento`；`habitación`（单间）合同更灵活 |
| 登记义务 | ★ **Empadronamiento**（住址登记），办居留/医保要用 |
| 主要平台 | Idealista、Fotocasa、Habitaclia、Milanuncios、学生公寓运营商 |

### 荷兰 Netherlands
| 槽位 | 情况 |
|---|---|
| 身份号 | ★ **BSN**（公民服务号）——开户、工作、医保都要 |
| 担保机制 | 押金 + 收入证明；房源极紧张，**抢房速度是第一位** |
| 押金惯例 | 常见 1–2 个月 |
| 合同类型 | 短期合同（bepaalde tijd）常见；学生公寓运营商最省事 |
| 登记义务 | ★ 到市政厅 `inschrijving` 登记住址（BSN 前提） |
| 主要平台 | Kamernet、HousingAnywhere、Funda、Facebook 群、学校 housing office |

### 其它（简表，用前逐项核实）
| 国家 | 身份号 | 担保特点 | 主要平台 |
|---|---|---|---|
| 比利时 BE | 市政登记后取得 | 押金通常 2 个月 | Immoweb、Zimmo |
| 葡萄牙 PT | NIF | 押金 1–2 月 | Idealista、Imovirtual、OLX |
| 奥地利 AT | Meldezettel（登记单） | 押金常 3 个月 | Willhaben、ImmoScout |
| 波兰 PL | PESEL | 押金 1–2 月 | Otodom、OLX、Gratka |
| 捷克 CZ | rodné číslo / 学生号 | 押金 1–2 月 | Bezrealitky、Sreality |
| 爱尔兰 IE | PPS Number | 押金 1 月；注意押金保护 | Daft.ie |
| 英国 UK | National Insurance | ★ 押金**法定**须存入政府认可的押金保护计划（DPS 等） | Rightmove、Zoopla、SpareRoom |

## 一条跨国的通用规律

**每个国家都有"一个必须先办的号"和"一套让你被信任的机制"。**
顺序永远是：**先办号 → 再建立可信度 → 才有资格谈房源**。
搞反顺序（先找房再问要什么材料）就会出现"到了那一步才发现没做"。

所以 `prep_check.py` 的**阶段 0** 在任何国家都是第一优先——换国家时，
第一件事是把这个国家的"号"和"担保方案"填进 `assets/checklist.json` 的阶段 0。

## 换国家怎么做（五步）

1. 复制一份 `assets/checklist.json`，把阶段 0 的"税号/证件/付款/担保/居留材料"五项
   **逐项替换**成该国的叫法与办理地点。
2. 更新 `assets/sources.json`：把该国主要平台加进去，标注可达性（直连/代理/需登录）。
3. 为每个新平台写一个 `extract_<站点>.py`（照 `scripts/extract_example_operauni.py` 的字段结构）。
4. 更新 `assets/templates/messages.json`：加该国语言的问询模板。
5. 在 `references/verification_rules.md` 里补该国的字段名对应（如德国 `Verfügbar ab`、
   法国 `Disponible à partir de`、西班牙 `Disponible desde`）与押金/合同术语。

**注意**：第 1 步之后先跑一次 `prep_check.py --stage now`，确认阶段 0 没有空槽位。
