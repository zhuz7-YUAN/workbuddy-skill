# 通勤层：一条房源"值不值"，一半看它到你每天要去的地方多远

## 为什么单列一层

核验层只回答"这条房源**能不能租**"（真假、新旧、性别、租期）。
但"能不能租"是**及格线**，不是**选择依据**。同一座城市里两套都"在 Trento"的房子：

- A：到大学主楼 **步行 8 分钟 / 0.6 km**，最近公交站 120 m
- B：在地图上是同一个城市，实际 **步行 43 分钟 / 3.4 km**，最近火车站 2.1 km

只报"城市 Trento"，这两套看起来一样。学生每天要往返的，是**第二个数字**。
所以**每一条进入主推的房源，都必须带通勤距离与时间**——这是排序的最后一列，也是最关键一列。

## 用法

```bash
# 单点自测：某地址到底在哪
python scripts/commute.py geocode --address "Via Sommarive 9" --city Trento

# 两点之间：步行/骑行/驾车耗时
python scripts/commute.py route --from "Via Sommarive 9, Trento" --to "Via Verdi 8, Trento"

# 批量：给台账里所有房源算通勤并写回
python scripts/commute.py enrich --db rental/housing.db \
    --to "Via Sommarive 9, Trento" --to-city Trento

# 按通勤分排序列出
python scripts/commute.py show --db rental/housing.db
python scripts/commute.py show --db rental/housing.db --links   # 额外给每条房源的导航链接

# 生成整张通勤地图（自包含 HTML，浏览器打开即用）
python scripts/commute.py map --db rental/housing.db --out commute_map.html

# 缓存管理（命中的地址会缓存，避免反复请求）
python scripts/commute.py cache            # 看缓存
python scripts/commute.py cache --clear    # 清空
```

`--to` 就是初始化访谈里问到的 **工作/学习地点**（`_target.work_place`）——
先有它，才谈得上通勤。

## 地图连接器（房源页面本身不给地图，我们补一个）

房源站不会告诉你"这房子离学校多远、长在哪"。所以本层除了数字，还给**两种地图**：

### ① 每条一条导航链接（最轻）

`show --links` 会为每条房源输出一个 Google 地图导航 URL（按地址文本拼装，**不需要坐标、不联网**）：

```
#2    Camera via Verdi
      https://www.google.com/maps/dir/?api=1&origin=Via%20Verdi%208%2C%20Trento&destination=Via%20Sommarive%209%2C%20Trento&travelmode=walking
```

复制到浏览器/手机就能看路线，也可以直接发给家人。

### ② 一张整图（最直观）

```bash
python scripts/commute.py map --db rental/housing.db --out commute_map.html
```

生成的是一张**自包含 HTML**，浏览器打开即为：

- **蓝点** = 工作/学习地；**绿/橙/灰点** = 各条房源（按步行时长分档）
- 每个房源到目标地画一条**虚线**，一眼看出谁近谁远
- 左侧按通勤分排序的清单，点条目地图定位到该房源
- 每个点弹窗里有：月总成本、步行/骑行时间、最近站点、**导航链接**

**离线/网络受限时的行为**（已实测）：
- Leaflet 库与地图瓦片都走公开 CDN。脚本内置**多路兜底**：Leaflet 依次尝试
  unpkg → jsdelivr → bootcdn；瓦片依次尝试 osm.de → osm.fr-hot → osm.org → Esri。
- 即便瓦片全部加载失败，**点、虚线、左侧清单仍然可用**，页面上会给出提示，
  告诉你可直接把地址复制到手机地图 App。
- 实测提示：**国内网络下 osm.de / osm.fr-hot / Esri 直连可用**，而官方
  `tile.openstreetmap.org` 直连常超时、走代理反而被重置；所以**不要**给地图页面硬套代理。

## 数据来源（全部免费、无需 API Key）

| 用途 | 服务 | 说明 |
|---|---|---|
| 地址 → 经纬度 | **Photon**（komoot，基于 OSM） | 首选，快、对街道级地址友好 |
| 地址 → 经纬度（备） | **Nominatim**（OSM 官方） | Photon 未命中时兜底；**限速 1.1 s/次**（官方使用政策） |
| 距离与驾车耗时 | **OSRM** 公共实例 | 只认**驾车路网**，故只用于取"路网距离"与驾车时间 |
| 最近公交/火车站 | **Overpass API**（OSM） | 取房源周边站点名称与距离 |

**网络路由**：与本技能其它抓取层一致——**直连优先，直连不通才降级走代理**。

## 三条硬边界（必须如实告知用户，不许含糊）

1. **不算真实公交/地铁的乘车时长。** 那需要运营方的 **GTFS 时刻表**，本工具不接入。
   所以它给的是**步行时间、骑行时间、驾车时间** + **最近站点有多远**，
   而不是"坐 12 路车 18 分钟"。想更准，把最近站点告诉用户，由用户在本地地图 App 复核。
2. **骑行/步行时间是估算，不是实测。** OSRM 公共实例只有驾车路网，直接拿它算步行会得出
   "25 公里走 23 分钟"这种荒谬结果。本工具改为**按路网距离 ÷ 速度**估算
   （步行 4.5 km/h、骑行 15 km/h），并标 `est`。它够用来**排序**，不够用来承诺到达时间。
3. **地址必须做城市校验。** 同名街道跨城很常见（"Via Verdi"在意大利几乎每个城市都有），
   而省名里常含城市名（`Provincia di Trento` 含 `Trento`），会导致把 25 公里外的房子
   误判成"同城"。本工具的做法是：**只取结构化结果里的 `city/town/village` 字段**，
   匹配用**全等或前缀**（不是子串包含），并允许地址变形（去掉门牌号、补 "Italia"）。
   若校验不通过，该条标为跨城，而不是硬算出一个漂亮但错的数字。

## 输出字段（写回台账）

| 字段 | 含义 |
|---|---|
| `lat` / `lon` | 房源坐标 |
| `commute_km` | 到目标地的路网距离（km） |
| `walk_min` | 步行估算时长（分钟） |
| `bike_min` | 骑行估算时长（分钟） |
| `stop_name` / `stop_dist_m` | 最近公交/火车站名与距离（米） |
| `commute_score` | 综合分（越近越高），`show` 按它排序 |
| `commute_to` | 计算时用的目标地（换地点后据此判断需不需要重算） |

## 怎么呈现给用户

在房源卡片里给 **"通勤"一行**，例如：

```
通勤：步行 8 分钟（0.6 km）｜骑行 3 分钟｜最近公交站 Povo Centro 120 m
```

**排序建议**：先按核验档位（只有 `direct` 进主推），再按 `commute_score` 排。
把"步行超过 25 分钟"的单独归到"偏远可考虑"，不要混在步行可达的那批里。
