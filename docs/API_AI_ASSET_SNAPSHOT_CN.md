# AI 资产分析快照接口说明

聚合全球市场首页所需数据（市场类型、热门标的、机会扫描、情绪、总览、热力图、经济日历、A 股价值精选等）。数据经缓存层提供，避免每次请求都打满外部行情源。

---

## 1. 接口一览

| 场景 | 方法 | 路径 | 鉴权 |
|------|------|------|------|
| **Agent / 外部自动化（推荐）** | `GET` | `/api/agent/v1/markets/ai-asset-snapshot` | `Authorization: Bearer qd_agent_xxx`，需 `R` scope |
| **Web 登录态** | `GET` | `/api/global-market/ai-asset-analysis/snapshot` | 用户 JWT / 会话（与前端登录一致） |

- Content-Type：请求/响应均为 `application/json`
- 两套接口 **`data` 内业务字段基本一致**；外层 envelope 不同（见下文）

---

## 2. 请求

### 2.1 查询参数

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `force` | boolean | 否 | `false` | `true` 或 `1` 时跳过缓存，强制重新计算各数据块 |

### 2.2 Agent 调用示例

```bash
curl -sS "https://your-host/api/agent/v1/markets/ai-asset-snapshot?force=false" \
  -H "Authorization: Bearer qd_agent_xxxxxxxx"
```

### 2.3 登录态调用示例

```bash
curl -sS "https://your-host/api/global-market/ai-asset-analysis/snapshot" \
  -H "Authorization: Bearer <USER_JWT>"
```

---

## 3. 响应 Envelope

### 3.1 Agent Gateway（`/api/agent/v1/...`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 成功为 **`0`**；业务/鉴权错误为非 0 |
| `message` | string | 如 `"ok"` 或错误描述 |
| `data` | object \| null | 业务数据；失败时常为 `null` |

错误时可能额外包含：`details`、`retriable`（是否建议重试）。

### 3.2 登录态（`/api/global-market/...`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 成功为 **`1`**；失败为 `0` |
| `msg` | string | 如 `"success"` |
| `data` | object \| null | 业务数据；含 `timestamp`（Unix 秒） |

---

## 4. `data` 字段总览

| 字段 | 类型 | 说明 |
|------|------|------|
| `market_types` | array | 当前部署可见的市场类型 |
| `hot_symbols` | object | 各市场热门标的，key 为市场编码 |
| `opportunities` | array | 多市场机会扫描结果 |
| `market_sentiment` | object | 宏观情绪（恐惧贪婪、VIX、DXY 等） |
| `market_overview` | object | 指数 / 外汇 / 加密 / 商品总览 |
| `market_heatmap` | object | 热力图（美股、港股、加密、行业等） |
| `economic_calendar` | array | 经济日历（本地生成示例事件） |
| `cn_value_picks` | array | **A 股价值精选**：低市盈率 + 高股息率 Top20 |
| `timestamp` | number | **仅登录态接口**返回，响应生成时间（Unix 秒） |

> Agent 接口会按 Token 的 `markets` 白名单过滤 `market_types`、`hot_symbols`、`opportunities`；`CNStock` 未授权时 `cn_value_picks` 为 `[]`。

---

## 5. 响应示例（Agent）

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "market_types": [
      { "value": "CNStock", "i18nKey": "dashboard.analysis.market.CNStock" },
      { "value": "USStock", "i18nKey": "dashboard.analysis.market.USStock" }
    ],
    "hot_symbols": {
      "CNStock": [
        { "market": "CNStock", "symbol": "600519", "name": "贵州茅台" }
      ]
    },
    "opportunities": [],
    "market_sentiment": {
      "fear_greed": { "value": 50, "classification": "Neutral", "timestamp": 0, "source": "N/A" },
      "vix": { "value": 18, "change": 0, "level": "low" },
      "dxy": { "value": 104, "change": 0, "level": "moderate_strong" },
      "yield_curve": { "spread": 0.2, "level": "normal" },
      "vxn": { "value": 0, "level": "very_low" },
      "gvz": { "value": 0, "level": "very_low" },
      "vix_term": { "value": 1.0, "level": "normal" },
      "timestamp": 1780210851
    },
    "market_overview": {
      "indices": [{ "symbol": "^GSPC", "name_cn": "标普500", "price": 5800.1, "change": 0.5 }],
      "forex": [{ "symbol": "EUR/USD", "price": 1.08, "change": 0.1 }],
      "crypto": [{ "symbol": "BTC", "price": 98000, "change_24h": 2.1 }],
      "commodities": [{ "symbol": "GC=F", "name_cn": "黄金", "price": 2650, "change": 0.3 }],
      "timestamp": 1780210851
    },
    "market_heatmap": {
      "us_stocks": [],
      "hk_stocks": [],
      "crypto": [{ "name": "BTC", "fullName": "Bitcoin", "value": 2.1, "price": 98000 }],
      "commodities": [],
      "forex": [],
      "sectors": [{ "name": "科技", "name_en": "Technology", "etf": "XLK", "value": 1.2 }],
      "indices": []
    },
    "economic_calendar": [
      {
        "id": 1,
        "name": "美国非农就业数据",
        "name_en": "US Non-Farm Payrolls",
        "country": "US",
        "date": "2026-05-26",
        "time": "08:30",
        "importance": "high",
        "forecast": "180K",
        "previous": "175K",
        "is_released": true
      }
    ],
    "cn_value_picks": [
      {
        "market": "CNStock",
        "symbol": "600036",
        "name": "招商银行",
        "pe_ratio": 6.2,
        "dividend_yield_pct": 5.1,
        "score": 0.822581,
        "rank": 1
      }
    ]
  }
}
```

---

## 6. 子结构字段说明

### 6.1 `market_types[]`

| 字段 | 类型 | 说明 |
|------|------|------|
| `value` | string | 市场编码：`USStock`、`CNStock`、`HKStock`、`Crypto`、`Forex`、`Futures`、`MOEX` |
| `i18nKey` | string | 前端国际化键 |

### 6.2 `hot_symbols.<market>[]`

| 字段 | 类型 | 说明 |
|------|------|------|
| `market` | string | 市场编码 |
| `symbol` | string | 标的代码（A 股为 6 位数字；Crypto 如 `BTC/USDT`） |
| `name` | string | 显示名称 |

### 6.3 `opportunities[]`

| 字段 | 类型 | 说明 |
|------|------|------|
| `market` | string | 市场编码 |
| `symbol` | string | 标的 |
| `signal` | string | 信号类型，如 `bullish_momentum` |
| `price` | number | 参考价 |
| `change_24h` | number | 24h 涨跌幅（%） |
| `change_7d` | number | 7d 涨跌幅（%） |
| `reason` | string | 原因描述 |
| `impact` | string | 影响等级：`low` / `medium` / `high` |

### 6.4 `market_sentiment`

| 字段 | 类型 | 说明 |
|------|------|------|
| `fear_greed` | object | 恐惧贪婪指数；`source` 为 `alternative.me` 或失败时 `N/A` |
| `vix` | object | CBOE 波动率 |
| `dxy` | object | 美元指数 |
| `yield_curve` | object | 收益率曲线 |
| `vxn` | object | 纳指波动率 |
| `gvz` | object | 黄金波动率 |
| `vix_term` | object | VIX 期限结构代理 |
| `timestamp` | number | Unix 秒 |

子对象通常含 `value`、`change`、`level`、`interpretation` / `interpretation_en` 等，具体以外部源返回为准。

### 6.5 `market_overview`

| 字段 | 类型 | 说明 |
|------|------|------|
| `indices` | array | 全球主要指数 |
| `forex` | array | 主要外汇对 |
| `crypto` | array | 主流加密货币（最多约 12 条） |
| `commodities` | array | 大宗商品 |
| `timestamp` | number | Unix 秒 |

指数/外汇等条目常见字段：`symbol`、`name` / `name_cn` / `name_en`、`price`、`change`（%）。

加密条目常见：`symbol`、`name`、`price`、`change_24h`、`market_cap`、`volume_24h`。

### 6.6 `market_heatmap`

| 字段 | 类型 | 说明 |
|------|------|------|
| `us_stocks` | array | 美股热力单元 |
| `hk_stocks` | array | 港股热力单元 |
| `crypto` | array | 加密热力单元 |
| `commodities` | array | 商品热力单元 |
| `forex` | array | 外汇热力单元 |
| `sectors` | array | 美股行业 ETF 板块 |
| `indices` | array | 全球指数热力单元 |

单元常见字段：`name`、`value`（涨跌幅 %）、`price`；加密另有 `marketCap`、`volume` 等。

### 6.7 `economic_calendar[]`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | number | 事件 ID |
| `name` / `name_en` | string | 中/英文名称 |
| `country` | string | 国家/地区代码 |
| `date` / `time` | string | 日期、时间 |
| `importance` | string | `high` / `medium` / `low` |
| `forecast` / `previous` / `actual` | string | 预期 / 前值 / 公布值 |
| `is_released` | boolean | 是否已公布 |
| `expected_impact` / `actual_impact` | string | 预期/实际影响方向 |

> 日历为服务端按模板生成的展示数据，非实时财经日历 API。

### 6.8 `cn_value_picks[]`（A 股价值精选）

按 **市盈率低 + 股息率高** 从全 A 股筛选，默认取前 **20** 名。数据源：东方财富 `push2delay.eastmoney.com` clist（动态市盈率 f9）+ AkShare `stock_fhps_em`（现金分红-股息率）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `market` | string | 固定 `CNStock` |
| `symbol` | string | **证券编码**，6 位 A 股代码，如 `600036` |
| `name` | string | **证券名称** |
| `pe_ratio` | number | **市盈率**（动态 PE） |
| `dividend_yield_pct` | number | **股息率（%）**，如 `5.1` 表示 5.1% |
| `score` | number | 综合得分，越高排名越靠前 |
| `rank` | number | 名次，1～20 |

筛选规则（可通过环境变量调整）：

- 剔除名称含 ST / *ST
- `0 < pe_ratio ≤ CN_VALUE_PICKS_MAX_PE`（默认 25）
- `dividend_yield_pct ≥ CN_VALUE_PICKS_MIN_DIVIDEND_PCT`（默认 2.0）

拉取失败或 AkShare 不可用时为 **`[]`**，不影响其它字段。

---

## 7. 错误响应

### 7.1 Agent

| HTTP | `code` | 典型 `message` |
|------|--------|----------------|
| 401 | 非 0 | `Missing or malformed agent token` / `Unknown agent token` / `Token expired` |
| 403 | 非 0 | `Token lacks required scope: R` |
| 429 | 非 0 | `Rate limit exceeded for this token` |
| 503 | 非 0 | `No backend market-data credential configured...` |
| 500 | 非 0 | `Internal server error` |

示例：

```json
{
  "code": 401,
  "message": "Missing or malformed agent token",
  "details": null,
  "retriable": false,
  "data": null
}
```

### 7.2 登录态

| HTTP | `code` | 说明 |
|------|--------|------|
| 401 | 0 | 未登录 |
| 503 | 0 | 未配置行情 API Key |
| 500 | 0 | 服务异常 |

---

## 8. 缓存策略

| 数据块 | 缓存键（内部） | 硬 TTL | 说明 |
|--------|----------------|--------|------|
| `market_types` | `ai_asset_snapshot_market_types` | 600s | 10 分钟 |
| `hot_symbols` | `ai_asset_snapshot_hot_symbols` | 1800s | 30 分钟 |
| `opportunities` | `trading_opportunities` | 3600s | 1 小时 |
| `market_sentiment` | `market_sentiment` | 21600s | 6 小时 |
| `market_overview` | `market_overview` | 120s | 2 分钟 |
| `market_heatmap` | `market_heatmap` | 120s | 2 分钟 |
| `economic_calendar` | `economic_calendar` | 3600s | 1 小时 |
| `cn_value_picks` | `ai_asset_snapshot_cn_value_picks` | **864000s** | **10 天** |

- `force=true` 会绕过缓存触发重算。
- 部分块支持 stale-while-revalidate：软过期后仍可能先返回旧数据并在后台刷新。

---

## 9. 服务端前置条件

1. **行情凭据**：至少配置一种市场数据 Key（如 `FINNHUB_API_KEY`、`TWELVE_DATA_API_KEY`、`TIINGO_API_KEY` 等），否则返回 **503**。
2. **Agent Token**：前缀 `qd_agent_`，且 scopes 含 **`R`**；可选 `markets` 白名单限制可见市场。
3. **`cn_value_picks`**：A 股 PE 走东方财富 **`push2delay.eastmoney.com`** clist（`EASTMONEY_CLIST_HOST` / `EASTMONEY_UT`）；股息率仍用 AkShare `stock_fhps_em`。PE 请求**不走** `CN_DATA_PROXY_URL`（该代理常导致 clist 502）。海外机房一般无需国内跳板即可拉 PE。服务器自检：`python3 scripts/diagnose_cn_value_picks.py`。可选环境变量见 `backend_api_python/env.example`：
   - `CN_VALUE_PICKS_MAX_PE`（默认 25）
   - `CN_VALUE_PICKS_MIN_DIVIDEND_PCT`（默认 2.0）
   - `CN_VALUE_PICKS_TOP_N`（默认 20）

---

## 10. 相关代码

| 说明 | 路径 |
|------|------|
| Agent 路由 | `backend_api_python/app/routes/agent_v1/markets.py` |
| 登录态路由 | `backend_api_python/app/routes/global_market.py` |
| A 股精选算法 | `backend_api_python/app/data_providers/cn_value_picks.py` |
| 缓存 TTL | `backend_api_python/app/data_providers/__init__.py` |

---

## 11. 版本说明

- 文档对应仓库功能：`cn_value_picks`、Agent audit JSON 安全写入、腾讯行情镜像环境变量 `TENCENT_QUOTE_BASE_URL` 等。
- 若 OpenAPI 机器可读契约需同步，请更新 `docs/agent/agent-openapi.json` 中 `/markets/ai-asset-snapshot` 定义。
