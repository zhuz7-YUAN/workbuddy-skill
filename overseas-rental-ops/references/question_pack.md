# 一次问全：标准问询包（杜绝同一问题反复问）

## 为什么必须"一次问全"

一问一答的往返是这个流程里最贵的东西：
- 跨时区，一轮往返就是 24 小时
- 房东/中介不爱回第二封
- 每封都要重新自我介绍一遍，浪费双方耐心
- 同一批房源几十条，逐条慢慢问根本不可能

**所以：一封问询里把所有决定性问题一次问完。** 房东回一次，信息就够做去留判断。

## 首轮问询包（8 个必问项）

发给房东 / 中介的第一封，必须包含下列全部问题。缺任何一个，都要靠第二轮补问——那就是浪费。

| # | 问题（中文） | 意大利语问法 | 为什么必问 |
|---|---|---|---|
| 0 | 自我介绍三张牌 | 见下方"身份段" | 房东只看这个决定回不回 |
| 1 | 房子**现在还空着吗** | `L'annuncio è ancora disponibile?` | 筛掉一半滞后信息，放第一个 |
| 2 | 最短租期能不能是 **4–6 个月** | `Il contratto richiede 12 mesi, ma a me servono solo 4 mesi e mezzo: è possibile?` | 核心错配 |
| 3 | 不行的话，**接受转租（subentro）吗** | `In alternativa, accettate un subentro? Posso trovare io un altro studente che subentri.` | 退一步的主攻方案 |
| 4 | **月总成本**：租金 + 杂费 + 押金 | `Qual è il canone e cosa è incluso? Quanto sono le spese extra? La cauzione?` | 只看租金会被坑 30–45% |
| 5 | **这周能看房吗**（给两个具体时间） | `Posso visitarla questa settimana? Sono disponibile <X> o <Y>.` | 能约看房 ≈ 房源真实存在 |
| 6 | 还有哪些硬性限制 | `Ci sono limitazioni (studenti/lavoratori, ragazze/ragazzi, fumatori, animali)?` | 性别/身份限制常藏在正文 |
| 7 | 合同类型与注册 | `Che tipo di contratto è? È registrato?` | 关系居留/签证材料，不能签私约 |

## 身份段（每封都放，别删）

房东决定回不回，靠的是三张牌：**身份可信 + 租期可连续 + 付得起**。

```
Sono <姓名>, studentessa/studente in exchange all'Università di <大学>
(Facoltà di <院系>). Cerco da subito fino a <结束日期> — posso restare
tutto il periodo senza interruzioni, quindi non dovrà cercare nessuno
a metà. Ho già il codice fiscale, posso firmare un contratto regolare
e pagare subito la caparra. Sono una ragazza/un ragazzo tranquillo,
non fumo, molto ordinato.
```

关键排序：**"我能连续住满整段"放最前面**——房东最怕中途空房。
如果是短租，一定把"我可以自己找接手的（subentro）"写出来，这一条经常直接谈成。

## 追问包（房东已回但信息不全时，一条消息补完）

```
Grazie della risposta. Prima di procedere, due cose:
1) <缺的那项>
2) <缺的那项>
Se tutto ok, possiamo fissare la visita? Preferirei <时间A> o <时间B>.
```

**不要问"还有别的吗"**——问具体缺的那几项。

## 看房确认包

```
Confermo la visita per <日期> alle <时间> a <地址>.
Il mio numero è <电话>. Avviso se dovessi ritardare.
```

看房后当天回一条，形成"已成事实"的印象，后面砍价和签约都好谈。

## 签约前确认包（8 项，缺一项就别签）

```
Prima di firmare, vorrei confermare:
1) Canone mensile e spese extra — importo esatto
2) Cauzione — importo e quando viene restituita
3) Durata e data di inizio/fine
4) Tipo di contratto (transitorio / concordato / libero) e registrazione
5) Cosa è incluso (utenze, wifi, riscaldamento, pulizie)
6) Arredamento e stato della stanza (foto)
7) Regole della casa (ospiti, silenzio, pulizie)
8) Chi è il proprietario e a chi si versa l'affitto
```

## 台账纪律：问过就不能再问

每发出一次问询、每收到一次回复，**都必须写进台账**（见 `scripts/housing_db.py`）。
发出前先查台账：这条房源**问过没有、问到第几轮、还缺哪项**。

判断规则：
- 已发出问询、48 小时内未回 → 可以发一次**简短追问**（不是重发首轮）
- 已问过同一项、对方已回 → **绝不再问**
- 已明确回复"不可租" → 标记排除，不再出现在任何清单里

## 各轮的时间节奏

| 时点 | 动作 |
|---|---|
| 收到房源当天 | 发首轮问询包（8 问全发） |
| +48 小时无回 | 发一次简短追问 |
| +5 天仍无回 | 标记"无响应"，不再占用精力 |
| 房东回信当天 | 回确认 + 约看房时间（给两个具体时段） |
| 看房后当天 | 回执 + 明确表态（要/不要），不要吊着 |
