# 加群与人脉：短租房源真正在群里的那一半

## 为什么必须先做这一步

分类广告站上的长租广告多、短租少；**真正能谈 4–6 个月、能走 subentro 的房源，
一大半在群组里**，而且发出来几小时内就被抢掉。
所以"进群"不是社交，是**缩短你看到房源的时间差**。

但这一步有个硬边界：**社交平台的加群与发帖必须由本人做**（见 SKILL.md 红线 4）。
本技能只做三件事：列出该进哪些群、把申请理由写好、把发帖/私信文案写好。**点发送的是人。**

## 一、该进哪些群（按优先级）

| 优先级 | 群类型 | 怎么找 | 为什么 |
|---|---|---|---|
| 1 | **本校交换生/国际学生群** | 学校国际办公室、Erasmus 群、学联 | 大多是**要转租/找接手人**的人，短租最匹配 |
| 2 | **本校中国学生学者联谊会（CSSA/学联）** | 学校官网、学长介绍 | 中文沟通零障碍；学长手里常有二手房源和房东直连 |
| 3 | **目标城市租房群** | 搜"<城市> affitto stanze"、"<城市> 租房" | 房源量大，假消息也多（要靠核验层） |
| 4 | **同一城市的中国留学生群** | 微信/QQ 群、学长拉群 | 常有"我要走了，接手我的房"信息 |
| 5 | 泛欧/全国学生合租群 | 见 `assets/sources.json` 里 `social_group` 类 | 覆盖广，但转化率低，放最低优先 |

进群后**把群名登记进 `assets/sources.json`**（`python sources.py add ... --type social_group`），
这样下次换城市/换国家时，渠道清单是现成的，不用重新找。

## 二、加群申请：三个问题一次答清

几乎所有的群都会问类似的三件事。**不要只写"求加"，写清楚身份+租期+需求**，
管理员（往往就是房东或学长）看到就会拉你：

```
【申请加群文案 · 中文群】
你好，我是朱志祺（<委托人>），中国学生，2026 年秋季到特伦托大学（Università di Trento）
交换。想找 10 月起到明年 1 月底的房间（4 个月），单间或床位都可以。
已有税号，可以签正规合同、可以立刻付押金和首月租，全程住满不中断。
如果方便请拉我进群，谢谢！
```

```
【群申请 · 英文/意大利文群】
Hi, I'm Zhu Zhiqi (<委托人>), a Chinese exchange student at Università di Trento
from October to end of January. Looking for a single room or a bed for 4 months,
starting October. I already have the codice fiscale, can sign a regular contract
and pay deposit immediately. Could you add me to the group? Thank you!
```

**为什么要写"全程住满不中断"**：群管理员里坐着房东，他们最怕的是租一半人跑了。
你第一句就把这个顾虑消掉，通过率立刻不一样。

## 三、进群之后怎么发（发帖模板）

发帖的格式决定有没有人回。**不要写作文**，四行主体 + 一句行动号召：

```
【求租 · 中英双语一次发】

🇨🇳 中国交换生（女），特伦托大学，10 月 → 明年 1 月底，找单间/床位。
已有税号，可签正规合同、立刻付押金，全程住满不中断。预算可谈。
🇬🇧 Chinese exchange student (F), UniTrento, Oct → end of Jan, looking for a
single room or a bed. Codice fiscale ready, regular contract, deposit ready.
📩 有意请私信/回帖，我随时可以去看房。
```

发帖纪律（发错了会被踢 + 封号）：
- **同一个城市最多同时进 3 个群**，一条消息不要一次贴 10 个群（Facebook 判定为刷屏）
- **不要每天重复发同一条**。隔 3–4 天发一次，且换一句开头
- **先看群规**。很多群要求"只在周六发"或"必须带价格区间"，不看就被踢
- 帖子里的**链接要去掉 `?__cft__` 之类的追踪串**（抓取层同一条纪律）

## 四、看到别人发的房源：私信模板

群里房源是"先私信先得"，回复速度比措辞重要。**30 字以内，把决定性问题一次问全**：

```
【群内私信 · 意大利文】
Buongiorno! Sono Zhiqi, studentessa exchange alla UniTrento. Mi interessa la stanza.
Ancora disponibile? Va bene per 4 mesi (ottobre → fine gennaio)?
Ho il codice fiscale e posso pagare subito la caparra. Posso vederla oggi/domani?
Grazie!
```

```
【群内私信 · 中文】
你好！我是朱志祺，特伦托大学交换生。请问房间还在吗，能接受 4 个月（10 月到 1 月底）吗？
我有税号，可以马上付押金，今天明天都可以去看房。谢谢！
```

> 发之前先查台账（`python scripts/housing_db.py ... fresh`），**同一个人不要问第二遍**。

## 五、比起群，更该先动的是这两个免费资源

群里靠缘分，下面两个是靠制度，成本极低但很多人不用：

**1. 学校国际办公室 / 住房办公室（International / Housing Office）**

一封邮件能换来：官方房源清单、转租信息转发、合同帮你复核、担保问题给建议。
很多学校愿意**替你给房东发一封"这个学生是我们的人"的邮件**——这一封比你说十句都管用。

```
Subject: Exchange student looking for a room (Oct - end of Jan) - request for help

Dear International Office,

My name is Zhu Zhiqi, an exchange student at Università di Trento from October
to the end of January. I have been looking for a single room for four months
without success, mainly because most listings require a 12-month stay.

Could you please:
1) share any housing list or internal noticeboard you have;
2) forward my request to students who may be leaving and need a takeover;
3) confirm whether the university can provide a letter confirming my student
   status, which I could show to landlords as a guarantee.

I already have the codice fiscale and can pay the deposit immediately.
Thank you very much for your help.

Best regards,
Zhu Zhiqi
```

**2. 本校学联 / 已在读的学长学姐（中文渠道）**
- 直接问："有没有人要提前走的、能接手的房？"—— 这是最短路径
- 请学长在你去看房时陪同（见 checklist 阶段 2 `viewing_buddy`）
- 学长如果愿意给房东发一条"这人靠谱"，比任何文案都有效

## 六、安全底线（在群里最容易出事）

| 风险 | 表现 | 底线 |
|---|---|---|
| 假房东 | 群里发图很漂亮，催你付定金 | 不看房不付钱；核验房东身份与产权（见 checklist 阶段 3） |
| 个人信息泄露 | 群里让你上传护照/税号"登记" | **群里绝不发证件原图**，只在核实后的合同环节给 |
| 私下转账 | 让你转到某个"亲戚账户" | 跑 `scripts/iban_check.py`，只付合同主体 |
| 拉你进"投资/兼职"群 | 借租房名义套你 | 直接退，别再回 |
| 微信/QQ 私聊诈骗 | 不让你看房就要钱 | 同上：不看房不付钱 |

**一条总原则：在群里只做两件事——问和约看房。钱和信息都留到见面、核实、签合同之后。**

## 七、把这一步接进流程

```bash
# 1) 把要进的群登记成渠道（方便复用）
python sources.py add --id fb_trento_affitto --country IT --city Trento \
  --type social_group --url "https://www.facebook.com/groups/<群ID>" \
  --access login --notes "特伦托租房群，需管理员审核"

# 2) 出文案（不加 --send，只打印，人工粘贴）
python scripts/outreach.py --profile renter.json --stage group_post --lang it

# 3) 有人回复了 → 记台账，别重复问
python scripts/housing_db.py --db rental/housing.db contact \
  --listing 21 --channel fb_dm --target "<对方>" --questions "1,2,3,4"
```
