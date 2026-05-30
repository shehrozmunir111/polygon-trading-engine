# Telegram bot — 100% free (Pakistan, bina PC VPN)

Pakistan mein `api.telegram.org` block hai. **Free** tareeqe jo **paise** nahi mangte:

| Option | Paisa | PC par install | 24/7 bot |
|--------|-------|----------------|----------|
| Google Cloud Shell (browser) | $0 | Nahi | Nahi (session band ho sakti hai) |
| Google Colab (browser) | $0 | Nahi | Nahi |
| GitHub Codespaces | $0* | Nahi | Limited hours/month |
| Oracle Cloud Free VM | $0 | Nahi (sirf browser/SSH) | Haan** |
| Free SOCKS5 proxy in `.env` | $0 | Nahi | Haan agar proxy chale |

\* GitHub account free  
\** Card sirf verify ke liye kabhi kabhi mangta hai, charge nahi hota agar sirf Always Free use karo

---

## 1) Google Cloud Shell — sab se aasaan (card nahi, browser)

Yeh Google ka free Linux machine hai — **browser** se chalta hai, Pakistan block bypass (Google ka network).

### Steps

1. Gmail se login: https://shell.cloud.google.com/
2. Pehli dafa thodi der wait karo jab machine baney.
3. Project upload karo (ya git clone):

```bash
git clone https://github.com/YOUR_USER/polygon-trading-engine.git
cd polygon-trading-engine
```

Agar GitHub par repo nahi, **Cloud Shell** mein "Upload" se zip upload karo.

4. `.env` banao:

```bash
cp .env.example .env
nano .env
```

`POLYGON_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` likho.  
`TELEGRAM_PROXY` **khali** chhoro — Cloud Shell par zaroorat nahi.

5. Install + test:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/test_telegram_proxy.py
```

`OK` aana chahiye.

6. Engine:

```bash
python main.py
```

7. Phone par bot ko `/start` bhejo.

**Note:** 20–30 minute idle par session band ho sakti hai. Dubara `python main.py` chalao.  
24/7 ke liye Option 3 ya Oracle VM.

---

## 2) GitHub Codespaces (free hours)

1. Repo GitHub par push karo (private free).
2. Repo page → **Code** → **Codespaces** → **Create codespace**.
3. Terminal:

```bash
cp .env.example .env
# .env edit — TELEGRAM token/chat id
pip install -r requirements.txt
python scripts/test_telegram_proxy.py
python main.py
```

Har mahine limited free hours — learning + testing ke liye theek.

---

## 3) Oracle Cloud — free forever VM (24/7)

- Website: https://www.oracle.com/cloud/free/
- Kabhi kabhi **card verify** mangta hai lekin Always Free tier par **charge nahi** hota agar sirf free shape use karo.
- Ubuntu VM banao → SSH → `docker compose up` (detail: `telegram-without-local-vpn.md`).

Agar card bilkul nahi hai → Option 1 (Cloud Shell) use karo.

---

## 4) Free public proxy (PC par, bina VPN app)

Koi bhi **free SOCKS5 list** se proxy lo, `.env` mein:

```env
TELEGRAM_PROXY=socks5://IP:PORT
```

Phir PC par:

```powershell
pip install aiohttp-socks
python scripts/test_telegram_proxy.py
```

- **$0** lekin aksar **slow / band** hota hai — 10–20 proxy try karo.
- Password wale trusted free trials bhi kabhi milte hain.
- Kabhi token/proxy sites par mat daalo — sirf `.env` local.

---

## Kya possible nahi (sach)

- Sirf mobile VPN + PC par program **bina proxy/cloud** — kaam nahi karega.
- Hamesha online bot **bilkul bina kisi account/server** — possible nahi; koi na koi free cloud chahiye.

---

## Recommendation (paise zero)

1. Abhi test: **https://shell.cloud.google.com/** → clone → `.env` → `python main.py`
2. Baad mein 24/7: Oracle free VM **ya** GitHub Codespaces jab chaho
