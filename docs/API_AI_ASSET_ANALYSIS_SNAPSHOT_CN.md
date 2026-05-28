# AI 资产分析首页快照接口（不含自选股）

## 1. 接口目标

提供一个聚合接口，一次性返回 Web 登录后首页 `/#/ai-asset-analysis` 所需的主要数据（**不包含用户自选股列表及其价格**）。

- 路径：`GET /api/global-market/ai-asset-analysis/snapshot`
- 鉴权：必须登录（`Authorization: Bearer <token>` 或有效会话）
- 设计原则：
  - 所有模块数据都通过缓存层返回，避免直连上游数据源
  - 请求必须依赖后台已配置的凭据（至少一个市场数据提供方 API Key）

---

## 2. 鉴权与凭据要求

### 2.1 登录凭据（必需）

接口使用 `@login_required`，未登录或 token/session 无效会被拒绝。

### 2.2 后台数据源凭据（必需）

若后台未配置任何市场数据提供方密钥，接口将返回 `503`。

当前检查的凭据类型：

- `FINNHUB_API_KEY`
- `TWELVE_DATA_API_KEY`
- `TIINGO_API_KEY`
- `COINGLASS_API_KEY`
- `CRYPTOQUANT_API_KEY`
- `ADANOS_API_KEY`

> 说明：凭据可来自环境变量或后台配置（addon config）。

---

## 3. 缓存策略

接口为聚合返回，但每个数据块都走缓存，避免“直接拉取”。

- `user_info`: 60 秒（按 `user_id` 分桶）
- `market_types`: 600 秒
- `hot_symbols`: 1800 秒
- `opportunities`: 使用既有 `trading_opportunities` 缓存（默认 3600 秒）
- `market_sentiment`: 使用既有 `market_sentiment` 缓存（默认 21600 秒）
- `market_overview`: 使用既有 `market_overview` 缓存（默认 120 秒）
- `market_heatmap`: 使用既有 `market_heatmap` 缓存（默认 120 秒）
- `economic_calendar`: 使用既有 `economic_calendar` 缓存（默认 3600 秒）

支持 `force=true` 强制刷新：

`GET /api/global-market/ai-asset-analysis/snapshot?force=true`

---

## 4. 请求示例

```bash
curl -X GET "http://localhost:5000/api/global-market/ai-asset-analysis/snapshot" \
  -H "Authorization: Bearer <YOUR_TOKEN>"
```

---

## 5. 返回结构

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "user_info": {
      "id": 1,
      "username": "admin",
      "nickname": "Admin",
      "email": "admin@example.com",
      "avatar": "/avatar2.jpg",
      "timezone": "Asia/Shanghai",
      "role": "admin"
    },
    "market_types": [
      { "value": "USStock", "i18nKey": "dashboard.analysis.market.USStock" }
    ],
    "hot_symbols": {
      "USStock": [{ "market": "USStock", "symbol": "AAPL", "name": "Apple Inc." }]
    },
    "opportunities": [],
    "market_sentiment": {},
    "market_overview": {},
    "market_heatmap": {},
    "economic_calendar": [],
    "timestamp": 1760000000
  }
}
```

---

## 6. 错误码说明

- `401`：未登录或登录态失效
- `503`：后台未配置可用市场数据凭据（至少需配置一个 provider API Key）
- `500`：服务内部错误

---

## 7. 与“自选股”边界

本接口**明确不返回**以下数据：

- `watchlist`（用户自选股列表）
- `watchlist prices`（自选股实时价格）

如需自选股数据，继续使用原有接口：

- `GET /api/market/watchlist/get`
- `GET /api/market/watchlist/prices`

