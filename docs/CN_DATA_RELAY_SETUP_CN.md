# 国内数据跳板（df.belltrip.cn）— Nginx + Certbot + Squid

海外 backend 通过 **`CN_DATA_PROXY_URL`** 访问 AkShare / 东方财富。  
东财有多个子域，需 **Squid 正向代理**；Nginx 负责 **证书（Certbot）**，可选把 **HTTPS 代理** 挂在 443 或 8443。

---

## 一、端口规划（避免和现有网站冲突）

| 端口 | 用途 |
|------|------|
| **3128** | HTTP 代理（明文，仅内网/调试） |
| **8443** | **HTTPS 代理（推荐海外用）**，证书 `df.belltrip.cn` |
| 80 / 443 | 若已有网站占用，**不要**让 Squid 和 Nginx 同时抢 443 |

若 `df.belltrip.cn` **专用于跳板**、无其它站点，可把 HTTPS 代理改为 **443**（下文把 `8443` 换成 `443` 即可）。

---

## 二、DNS

| 类型 | 主机 | 值 |
|------|------|-----|
| A | `df` | 国内服务器公网 IP |

---

## 三、安装 Squid

```bash
sudo apt update
sudo apt install -y squid apache2-utils
```

代理账号：

```bash
sudo htpasswd -c /etc/squid/passwd quantdinger
```

---

## 四、Squid 配置（修复 CONNECT / SSL 错误）

```bash
sudo cp /etc/squid/squid.conf /etc/squid/squid.conf.bak
sudo nano /etc/squid/squid.conf
```

**整文件可替换为：**

```conf
visible_hostname df.belltrip.cn

# HTTP 代理（本机调试）
http_port 3128

# HTTPS 代理（Certbot 证书，海外 backend 连这个）
# 若 8443 无冲突；专机可改为 https_port 443
https_port 8443 tls-cert=/etc/letsencrypt/live/df.belltrip.cn/fullchain.pem tls-key=/etc/letsencrypt/live/df.belltrip.cn/privkey.pem

# 认证
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
auth_param basic realm CN-Data-Relay
acl authenticated proxy_auth REQUIRED

# HTTPS 隧道（缺了会报 curl:56 SSL unexpected eof）
acl SSL_ports port 443
acl CONNECT method CONNECT
acl Safe_ports port 80 443 21 1025-65535

acl china_fin dstdomain .eastmoney.com .gtimg.cn .ifzq.gtimg.cn .qq.com .tencent.com .sina.com.cn .sinajs.cn .10jqka.com.cn .cninfo.com.cn

# 顺序重要
http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports
http_access allow authenticated CONNECT SSL_ports
http_access allow authenticated china_fin
http_access deny all

access_log /var/log/squid/access.log cache.log /var/log/squid/cache.log
```

> Ubuntu 若提示找不到 `basic_ncsa_auth`，执行：  
> `sudo find /usr -name basic_ncsa_auth 2>/dev/null`  
> 把路径写进 `auth_param basic program`。

**不要用 `ssl_bump`**，东财只需 CONNECT 隧道，解密 HTTPS 会导致 EOF。

---

## 五、Certbot 证书（已有 Nginx 时）

### 方式 A：Nginx 只占 80，证书给 Squid 用 8443

```bash
sudo certbot certonly --nginx -d df.belltrip.cn
# 或：sudo certbot certonly --webroot -w /var/www/html -d df.belltrip.cn
```

### 让 Squid 能读证书

```bash
sudo apt install -y ssl-cert
sudo usermod -aG ssl-cert proxy
sudo chmod 755 /etc/letsencrypt/live /etc/letsencrypt/archive
sudo chgrp ssl-cert /etc/letsencrypt/live/df.belltrip.cn/*.pem
sudo chmod 640 /etc/letsencrypt/live/df.belltrip.cn/privkey.pem
```

### Nginx 仅用于续期（可选 `server` 块）

```nginx
server {
    listen 80;
    server_name df.belltrip.cn;
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    location / {
        return 200 'CN data relay';
        add_header Content-Type text/plain;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 六、启动 Squid

```bash
sudo squid -k parse
sudo systemctl restart squid
sudo systemctl status squid
```

确认监听：

```bash
sudo ss -lntp | grep -E '3128|8443'
```

---

## 七、防火墙 / 安全组

放行（仅海外 backend IP 更佳）：

- **8443**（HTTPS 代理，生产）
- 3128（可选，调试）

```bash
sudo ufw allow from 海外BACKEND公网IP to any port 8443 proto tcp
```

---

## 八、自测（先 HTTP 3128）

```bash
# 1) 不走代理（应成功）
curl -sS --max-time 10 "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" | head -c 100

# 2) 走代理 — 必须带 -v 看 CONNECT 是否 200
curl -v -x http://quantdinger:你的密码@127.0.0.1:3128 \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" \
  2>&1 | head -40
```

日志里应有：`CONNECT ... 200 Connection established`，然后才有 JSON。

若仍 `curl: (56)`：

```bash
sudo tail -30 /var/log/squid/access.log
sudo tail -30 /var/log/squid/cache.log
```

常见：`TCP_DENIED/403` → ACL 顺序或密码错；`swap_timeout` → 上游问题。

### HTTPS 代理端口自测（8443）

```bash
curl -v -x https://quantdinger:你的密码@127.0.0.1:8443 \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" \
  2>&1 | head -40
```

---

## 九、海外 backend 测试

```bash
curl -v -x https://quantdinger:你的密码@df.belltrip.cn:8443 \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" \
  2>&1 | head -30
```

`.env`：

```env
CN_DATA_PROXY_URL=https://quantdinger:你的密码@df.belltrip.cn:8443
```

密码含 `@#` 等需 URL 编码。重启 backend 后：

```bash
curl -sS "https://海外域名/api/agent/v1/markets/ai-asset-snapshot?force=1" \
  -H "Authorization: Bearer TOKEN" | jq '.data.cn_value_picks | length'
```

---

## 十、Nginx 与 Squid 分工（总结）

| 组件 | 作用 |
|------|------|
| **Certbot + Nginx** | 申请/续期 `df.belltrip.cn` 证书 |
| **Squid 8443** | TLS 加密的 **正向代理**（海外连这里） |
| **Squid 3128** | 明文代理，仅调试 |

Nginx **不能**用普通 `proxy_pass https://push2.eastmoney.com` 代替 Squid 反代东财（子域太多）。  
可选：Nginx `stream {}` 把 443 原样转给 Squid，但不如 Squid 直接 `https_port` 简单。

---

## 十一、续期

```bash
sudo certbot renew --dry-run
```

续期后重启 Squid：

```bash
sudo systemctl restart squid
```
