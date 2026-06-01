# 国内数据跳板部署指南（df.belltrip.cn）

海外 QuantDinger 无法直连东方财富时，可在**国内 Ubuntu** 上部署 HTTP 正向代理，海外 backend 通过 `CN_DATA_PROXY_URL` 拉取 AkShare / 东财数据。

> 单域名 Nginx 反代只适合腾讯 `qt.gtimg.cn` 这类固定主机；东财有多个子域（`push2.eastmoney.com`、`data.eastmoney.com` 等），必须用 **HTTP 代理（Squid）**。

---

## 架构

```text
海外 QuantDinger ──CN_DATA_PROXY_URL──► df.belltrip.cn:3128 (Squid)
                                              │
                                              ▼
                                        东方财富 / 腾讯等
```

---

## 一、DNS

在域名服务商添加：

| 类型 | 主机记录 | 值 |
|------|----------|-----|
| A | `df` | 国内服务器公网 IP |

验证：`ping df.belltrip.cn`

---

## 二、国内 Ubuntu 安装 Squid

```bash
sudo apt update
sudo apt install -y squid apache2-utils
```

### 1. 创建代理账号

```bash
sudo htpasswd -c /etc/squid/passwd quantdinger
# 按提示输入密码，记下 USER / PASS
```

### 2. 写入配置

```bash
sudo cp /etc/squid/squid.conf /etc/squid/squid.conf.bak
sudo tee /etc/squid/squid.conf <<'EOF'
visible_hostname df.belltrip.cn

http_port 3128

auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
auth_param basic realm CN-Data-Relay
acl authenticated proxy_auth REQUIRED

acl SSL_ports port 443
acl Safe_ports port 80 443 21 1025-65535
acl CONNECT method CONNECT

acl china_fin dstdomain .eastmoney.com .gtimg.cn .ifzq.gtimg.cn .qq.com .tencent.com .sina.com.cn .sinajs.cn .10jqka.com.cn .cninfo.com.cn .hexun.com .szse.cn .ssec.com.cn

http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports
http_access allow authenticated china_fin
http_access deny all

access_log /var/log/squid/access.log
EOF
```

> 若 AkShare 报其它国内域名失败，把域名后缀追加到 `china_fin` 的 `dstdomain` 列表。

### 3. 初始化并启动

```bash
sudo squid -k parse
sudo systemctl enable --now squid
sudo systemctl status squid
```

### 4. 防火墙（仅允许海外 backend IP）

```bash
# 示例：只允许海外机 1.2.3.4 访问 3128
sudo ufw allow from 1.2.3.4 to any port 3128 proto tcp
sudo ufw reload
```

---

## 三、在国内机自测

```bash
curl -x http://quantdinger:你的密码@127.0.0.1:3128 -sS --max-time 15 \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" \
  | head -c 200
```

有 JSON 返回即 Squid 正常。

---

## 四、在海外 backend 服务器上测试

```bash
curl -x http://quantdinger:你的密码@df.belltrip.cn:3128 -sS --max-time 20 \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" \
  | head -c 200
```

通过后再配置 QuantDinger。

---

## 五、海外 QuantDinger 配置

`backend_api_python/.env`（或 Docker 挂载的 env）增加：

```env
# 海外访问 Binance / Yahoo 等（若已有可保留）
# PROXY_URL=socks5h://...

# 仅 AkShare / 东财 / A 股相关走国内跳板
CN_DATA_PROXY_URL=http://quantdinger:你的密码@df.belltrip.cn:3128
```

重启 backend 后：

```bash
curl -sS "https://你的海外域名/api/agent/v1/markets/ai-asset-snapshot?force=1" \
  -H "Authorization: Bearer YOUR_TOKEN" | jq '.data.cn_value_picks | length'
```

---

## 六、安全建议

1. **务必开密码**（`htpasswd`），不要裸奔 `3128`。
2. **防火墙白名单**仅放行海外 backend 公网 IP。
3. 可选：改用非默认端口，或再加 IP 限速。
4. `df.belltrip.cn` 仅作代理，不必部署网站证书（HTTP 代理端口 3128 即可）。

---

## 七、故障排查

| 现象 | 处理 |
|------|------|
| 海外 curl 超时 | 查国内防火墙 / 安全组是否放行 3128 |
| `407 Proxy Authentication Required` | 检查用户名密码 |
| `403` / `DENIED` | Squid `access.log`，补 `china_fin` 域名 |
| 代理通但 `cn_value_picks` 仍空 | 确认代码已支持 `CN_DATA_PROXY_URL` 并 `git pull` 后重启 |
| 仍走直连东财 | 未设置 `CN_DATA_PROXY_URL` 或 env 未挂载进容器 |

查看 Squid 日志：

```bash
sudo tail -f /var/log/squid/access.log
```
