# Squid 跳板 curl:56 排查（CONNECT 200 后 SSL EOF）

## 1. 先确认：不经过代理是否正常

```bash
curl -sS --max-time 15 \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" \
  | head -c 200
```

- **有 JSON** → 本机到东财正常，问题在 Squid。
- **也失败** → 先修本机网络/DNS，与 Squid 无关。

## 2. 禁用 Ubuntu 自带 conf.d（常见根因）

默认 `/etc/squid/conf.d/*.conf` 可能含 `ssl_bump` 或与 CONNECT 冲突的规则。

```bash
sudo mkdir -p /etc/squid/conf.d.bak
sudo mv /etc/squid/conf.d/*.conf /etc/squid/conf.d.bak/ 2>/dev/null || true
```

`squid.conf` **不要**再 `include conf.d`（或保持注释掉 include）。

## 3. 使用最小可用 squid.conf

```bash
sudo tee /etc/squid/squid.conf <<'EOF'
visible_hostname df.belltrip.cn

http_port 3128

auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
auth_param basic realm CN-Data-Relay
acl authenticated proxy_auth REQUIRED

acl SSL_ports port 443
acl CONNECT method CONNECT
acl Safe_ports port 80 443 1025-65535
acl china_fin dstdomain .eastmoney.com .gtimg.cn .qq.com .tencent.com .sina.com.cn .sinajs.cn .10jqka.com.cn

via off
forwarded_for delete
dns_v4_first on

connect_timeout 3 minutes
read_timeout 3 minutes
request_timeout 3 minutes

cache deny all

http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports
http_access allow authenticated CONNECT SSL_ports
http_access allow authenticated china_fin
http_access deny all

access_log /var/log/squid/access.log
EOF

sudo squid -k parse && sudo systemctl restart squid
```

## 4. 测试（强制 HTTP/1.1）

```bash
curl --http1.1 -v -x http://quantdinger:你的密码@127.0.0.1:3128 \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" \
  2>&1 | tail -20

curl --http1.1 -x http://quantdinger:你的密码@127.0.0.1:3128 -sS --max-time 20 \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" \
  | head -c 300
```

## 5. 看 access.log

```bash
sudo tail -5 /var/log/squid/access.log
```

应类似：`TCP_TUNNEL/200` 而不是 `TCP_DENIED` / `ERR`。

## 6. 仍失败：改用 3proxy（推荐备选）

```bash
sudo apt install -y 3proxy

sudo tee /etc/3proxy/3proxy.cfg <<'EOF'
daemon
nserver 223.5.5.5
nscache 65536
timeouts 1 5 30 60 180 1800 15 60

users quantdinger:CL:你的密码
auth strong
allow quantdinger
proxy -p3128
EOF

sudo systemctl enable --now 3proxy
# 若需手动：sudo 3proxy /etc/3proxy/3proxy.cfg
```

先停 Squid 避免抢端口：

```bash
sudo systemctl stop squid
```

测试：

```bash
curl --http1.1 -x http://quantdinger:你的密码@127.0.0.1:3128 -sS \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" | head -c 200
```

海外 `.env` 仍用：

```env
CN_DATA_PROXY_URL=http://quantdinger:密码@df.belltrip.cn:3128
```

## 7. 8443 + Certbot（HTTP 代理通后再做）

```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d df.belltrip.cn --http-01-port 80
# 80 被占用则：certbot certonly --nginx 或临时停 nginx
```

Squid 增加（证书路径按实际）：

```conf
https_port 8443 tls-cert=/etc/letsencrypt/live/df.belltrip.cn/fullchain.pem tls-key=/etc/letsencrypt/live/df.belltrip.cn/privkey.pem
```

```bash
sudo usermod -aG ssl-cert proxy
sudo chmod 755 /etc/letsencrypt/live /etc/letsencrypt/archive
sudo chgrp ssl-cert /etc/letsencrypt/live/df.belltrip.cn/*.pem
sudo chmod 640 /etc/letsencrypt/live/df.belltrip.cn/privkey.pem
sudo systemctl restart squid
```

测试：

```bash
curl --http1.1 -x https://quantdinger:密码@127.0.0.1:8443 -sS \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&fs=m:0+t:6" | head -c 200
```

.env：

```env
CN_DATA_PROXY_URL=https://quantdinger:密码@df.belltrip.cn:8443
```
