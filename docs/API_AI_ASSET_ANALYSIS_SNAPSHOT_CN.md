# AI 资产分析首页快照接口

## 1. 基本信息

- 接口名称：AI 资产分析首页快照
- 请求方法：`GET`
- 请求路径：`/api/global-market/ai-asset-analysis/snapshot`
- Content-Type：`application/json`
- 鉴权方式：登录态鉴权（Bearer Token 或有效会话）

## 2. 查询参数

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `force` | `boolean` | 否 | `false` | 是否强制刷新缓存；`true/1` 表示强制刷新 |

请求示例：

```bash
curl -X GET "http://localhost:5000/api/global-market/ai-asset-analysis/snapshot?force=false" \
  -H "Authorization: Bearer <YOUR_TOKEN>"
```

## 3. 成功响应

### 3.1 响应示例

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "market_types": [
      { "value": "USStock", "i18nKey": "dashboard.analysis.market.USStock" },
      { "value": "Crypto", "i18nKey": "dashboard.analysis.market.Crypto" }
    ],
    "hot_symbols": {
      "USStock": [
        { "market": "USStock", "symbol": "AAPL", "name": "Apple Inc." }
      ],
      "Crypto": [
        { "market": "Crypto", "symbol": "BTC/USDT", "name": "Bitcoin" }
      ]
    },
    "opportunities": [
      {
        "market": "Crypto",
        "symbol": "BTC/USDT",
        "signal": "bullish_momentum",
        "price": 68000.12,
        "change_24h": 2.35,
        "change_7d": 5.42,
        "reason": "Momentum strengthening",
        "impact": "medium"
      }
    ],
    "market_sentiment": {
      "fear_greed": { "value": 63, "classification": "Greed" },
      "vix": { "value": 14.8, "level": "low" },
      "dxy": { "value": 104.2, "level": "neutral" },
      "yield_curve": { "spread": -0.32, "level": "inverted" },
      "vxn": { "value": 19.5, "level": "medium" },
      "gvz": { "value": 16.1, "level": "low" },
      "vix_term": { "value": 0.94, "level": "normal" },
      "timestamp": 1760000000
    },
    "market_overview": {
      "indices": [],
      "forex": [],
      "crypto": [],
      "commodities": [],
      "timestamp": 1760000000
    },
    "market_heatmap": {
      "crypto": [],
      "sectors": [],
      "commodities": [],
      "forex": []
    },
    "economic_calendar": [],
    "timestamp": 1760000000
  }
}
```

### 3.2 顶层字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | `number` | 业务状态码，`1` 表示成功，`0` 表示失败 |
| `msg` | `string` | 响应消息 |
| `data` | `object` | 业务数据主体 |

### 3.3 `data` 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market_types` | `array<object>` | 可用市场类型列表 |
| `hot_symbols` | `object<string, array<object>>` | 各市场的热门标的 |
| `opportunities` | `array<object>` | AI 机会扫描结果列表 |
| `market_sentiment` | `object` | 市场情绪指标集合 |
| `market_overview` | `object` | 市场总览（指数/外汇/加密/商品） |
| `market_heatmap` | `object` | 热力图数据（按板块分类） |
| `economic_calendar` | `array<object>` | 经济日历事件列表 |
| `timestamp` | `number` | 本次聚合响应生成时间戳（Unix 秒） |

### 3.4 关键子对象字段说明

#### 3.4.1 `market_types[]`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `value` | `string` | 市场类型编码，如 `USStock`、`Crypto` |
| `i18nKey` | `string` | 前端国际化键 |

#### 3.4.2 `hot_symbols.<market>[]`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market` | `string` | 市场类型 |
| `symbol` | `string` | 标的代码/交易对 |
| `name` | `string` | 标的名称 |

#### 3.4.3 `opportunities[]`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market` | `string` | 市场类型 |
| `symbol` | `string` | 标的代码/交易对 |
| `signal` | `string` | 信号类型（如 `bullish_momentum`） |
| `price` | `number` | 当前价格 |
| `change_24h` | `number` | 24 小时涨跌幅（%） |
| `change_7d` | `number` | 7 天涨跌幅（%） |
| `reason` | `string` | 信号原因描述 |
| `impact` | `string` | 信号影响等级（如 `low/medium/high`） |

#### 3.4.4 `market_sentiment`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `fear_greed` | `object` | 恐惧贪婪指数 |
| `vix` | `object` | VIX 波动率指数 |
| `dxy` | `object` | 美元指数 |
| `yield_curve` | `object` | 收益率曲线状态 |
| `vxn` | `object` | 纳指波动率指数 |
| `gvz` | `object` | 黄金波动率指数 |
| `vix_term` | `object` | VIX 期限结构指标 |
| `timestamp` | `number` | 情绪数据时间戳（Unix 秒） |

#### 3.4.5 `market_overview`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `indices` | `array<object>` | 全球主要指数列表 |
| `forex` | `array<object>` | 外汇对列表 |
| `crypto` | `array<object>` | 加密资产报价列表 |
| `commodities` | `array<object>` | 商品报价列表 |
| `timestamp` | `number` | 总览数据时间戳（Unix 秒） |

#### 3.4.6 `market_heatmap`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `crypto` | `array<object>` | 加密市场热力图单元 |
| `sectors` | `array<object>` | 股票行业热力图单元 |
| `commodities` | `array<object>` | 商品热力图单元 |
| `forex` | `array<object>` | 外汇热力图单元 |

## 4. 错误响应

### 4.1 错误码

| HTTP 状态码 | `code` | 说明 |
| --- | --- | --- |
| `401` | `0` | 未登录或登录态失效 |
| `503` | `0` | 未配置可用市场数据凭据 |
| `500` | `0` | 服务内部异常 |

### 4.2 错误响应示例

```json
{
  "code": 0,
  "msg": "No backend market-data credential configured. Configure at least one provider API key first.",
  "data": null
}
```

## 5. 缓存说明

- `market_types`：600 秒
- `hot_symbols`：1800 秒
- `opportunities`：复用 `trading_opportunities` 缓存
- `market_sentiment`：复用 `market_sentiment` 缓存
- `market_overview`：复用 `market_overview` 缓存
- `market_heatmap`：复用 `market_heatmap` 缓存
- `economic_calendar`：复用 `economic_calendar` 缓存
- `force=true` 时会跳过缓存进行刷新

