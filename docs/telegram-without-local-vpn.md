# Telegram bot without VPN on your PC (Pakistan)

Pakistan blocks `api.telegram.org`. Your Python program must reach that server somehow.
You do **not** need a VPN app on Windows if you use one of these:

---

## Option A — Run the engine on a free cloud server (recommended)

The server is outside Pakistan, so Telegram works with no proxy and no PC VPN.

### Oracle Cloud (always-free VM)

1. Create a free account at https://www.oracle.com/cloud/free/
2. Create an **Ubuntu** VM (Always Free tier).
3. SSH into the VM from your PC (one-time setup, not a VPN).
4. On the VM:

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
git clone <your-repo-url> polygon-trading-engine
cd polygon-trading-engine
cp .env.example .env
nano .env   # add POLYGON_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
sudo docker compose up -d --build
sudo docker compose logs -f
```

5. On your phone, message your bot — `/start` should reply.

Your PC only needs SSH for setup; daily use is Telegram on mobile.

### Other hosts

Same idea: any VPS in EU/US (Hetzner, DigitalOcean, etc.) + `docker compose up`.

---

## Option B — Remote proxy URL only (no VPN app)

Some providers sell **HTTP/SOCKS5 proxy** as a URL. You only paste it into `.env`:

```env
TELEGRAM_PROXY=socks5://user:pass@proxy-host:port
```

Then on your PC:

```powershell
pip install aiohttp-socks
python scripts/test_telegram_proxy.py
python main.py
```

Use a **paid/trusted** provider. Free public proxies are often slow, logged, or unsafe.

---

## What does NOT work

| Method | Why |
|--------|-----|
| Browser VPN extension | Only the browser; `python main.py` is not proxied |
| Mobile VPN only | Phone apps work; your PC program still blocked |
| No proxy and no cloud | Python cannot reach Telegram from Pakistan |

---

## Quick test on PC (with proxy in `.env`)

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/test_telegram_proxy.py
```

`OK` = proxy or network path works. Then run `python main.py`.
