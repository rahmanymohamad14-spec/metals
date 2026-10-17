# -*- coding: utf-8 -*-
"""اجرای دوره‌ای: قیمت جهانی، قیمت ایران، حباب صندوق‌های طلا، شاخص‌های کلان، خبر معتبر و تحلیل."""
import json, os, re, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).parent / "docs"
UA = {"User-Agent": "Mozilla/5.0"}
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
FUNDS = ["عیار", "مثقال", "لوتوس", "کهربا", "زر", "طلا", "گوهر", "تابش", "آلتون", "نفیس"]
FA_SITES = ["donya-e-eqtesad.com", "eghtesadonline.com", "isna.ir", "irna.ir", "tasnimnews.com", "mehrnews.com", "ecoiran.com", "tejaratnews.com"]
EN_SITES = ["reuters.com", "bloomberg.com", "kitco.com", "cnbc.com", "ft.com", "wsj.com"]
POS = ["افزایش", "صعود", "رشد", "جهش", "گران", "بالا رفت", "rise", "gain", "surge", "rally", "climb", "jump", "high"]
NEG = ["کاهش", "ریزش", "افت", "نزول", "ارزان", "پایین آمد", "fall", "drop", "slump", "slide", "decline", "tumble", "low"]

def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")

def yahoo(sym):
    r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1y&interval=1d"))["chart"]["result"][0]
    cl = r["indicators"]["quote"][0]["close"]
    return {datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"): round(c, 3) for t, c in zip(r["timestamp"], cl) if c}

def tgju(slug):
    html = get(f"https://www.tgju.org/profile/{slug}")
    m = re.search(r'data-col="info\.last_trade\.PDrCotVal"[^>]*>\s*([\d,]+)', html)
    if not m:
        raise ValueError("عدد قیمت پیدا نشد")
    return float(m.group(1).replace(",", ""))

def find(o, keys):
    if isinstance(o, dict):
        for k in keys:
            if isinstance(o.get(k), (int, float)) and o[k] > 0:
                return o[k]
        for v in o.values():
            r = find(v, keys)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find(v, keys)
            if r is not None:
                return r
    return None

def fund(name):
    base = "https://cdn.tsetmc.com/api/"
    j = json.loads(get(base + "Instrument/GetInstrumentSearch/" + urllib.parse.quote(name)))["instrumentSearch"]
    norm = lambda s: (s or "").replace("ي", "ی").replace("ك", "ک").strip()
    hits = [x for x in j if norm(x.get("lVal18AFC")) == name] or j
    code = hits[0]["insCode"]
    price = find(json.loads(get(base + f"ClosingPrice/GetClosingPriceInfo/{code}")), ["pDrCotVal", "pClosing"])
    nav = find(json.loads(get(base + f"Fund/GetETFByInsCode/{code}")), ["pRedTran"])
    if not price or not nav:
        raise ValueError("قیمت یا NAV پیدا نشد")
    return {"price": price, "nav": nav, "bubble": round((price / nav - 1) * 100, 2), "date": today}

def news(q, sites, hl, gl, ceid):
    qq = q + " (" + " OR ".join("site:" + s for s in sites) + ") when:2d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": qq, "hl": hl, "gl": gl, "ceid": ceid})
    out, seen = [], set()
    for i in ET.fromstring(get(url)).iter("item"):
        t = i.findtext("title") or ""
        if t in seen:
            continue
        seen.add(t)
        low = t.lower()
        p, n = sum(w in low for w in POS), sum(w in low for w in NEG)
        out.append({"t": t, "u": i.findtext("link"), "d": i.findtext("pubDate"), "src": i.findtext("source") or "",
                    "s": "+" if p > n else "-" if n > p else "0"})
        if len(out) >= 8:
            break
    return out

def analyze(data):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    last = {k: list(v.items())[-6:] for k, v in data["series"].items() if v}
    heads = {k: [n["t"] for n in v[:6]] for k, v in data["news"].items()}
    prompt = ("داده‌های اخیر (تاریخ، مقدار):\n" + json.dumps(last, ensure_ascii=False) +
              "\n\nحباب صندوق‌های طلا (درصد نسبت به NAV):\n" + json.dumps(data.get("funds", {}), ensure_ascii=False) +
              "\n\nتیتر خبرها:\n" + json.dumps(heads, ensure_ascii=False) +
              "\n\nبه فارسی، ساختارمند و کوتاه بنویس: ۱) وضعیت طلا (جهانی و ایران، حباب سکه و صندوق‌ها) ۲) نقره ۳) مس ۴) عوامل کلان (دلار، نرخ بهره آمریکا، VIX) "
              "۵) مهم‌ترین ریسک‌ها و موارد نامعلوم. اگر داده‌ای نیست، صریح بگو. هیچ توصیه‌ی خرید یا فروش و هیچ پیش‌بینی قطعی نده.")
    body = json.dumps({"model": "claude-sonnet-5-5", "max_tokens": 1800,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    r = json.loads(get("https://api.anthropic.com/v1/messages", body,
                       {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}))
    return "".join(b.get("text", "") for b in r["content"])

def main():
    OUT.mkdir(exist_ok=True)
    try:
        data = json.loads((OUT / "data.json").read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("series", {}); data.setdefault("news", {}); data.setdefault("funds", {})
    data["errors"] = []
    s, err = data["series"], data["errors"]
    for key, sym in [("g_gold", "GC=F"), ("g_silver", "SI=F"), ("g_copper", "HG=F"), ("g_plat", "PL=F"), ("g_oil", "CL=F"),
                     ("m_dxy", "DX-Y.NYB"), ("m_tnx", "^TNX"), ("m_vix", "^VIX"), ("m_spx", "^GSPC")]:
        try:
            s.setdefault(key, {}).update(yahoo(sym))
        except Exception as e:
            err.append(f"{key}: {e}")
    for key, slug in [("i_gold18", "geram18"), ("i_gold24", "geram24"), ("i_mesghal", "mesghal"), ("i_coin", "sekee"),
                      ("i_coin_old", "sekeb"), ("i_half", "nim"), ("i_quarter", "rob"), ("i_usd", "price_dollar_rl"), ("i_silver", "silver_999")]:
        try:
            s.setdefault(key, {})[today] = tgju(slug)
        except Exception as e:
            err.append(f"{key}: {e}")
    last = lambda k: (list(sorted(s.get(k, {}).items()))[-1][1] if s.get(k) else None)
    try:  # حباب طلا و سکه نسبت به قیمت جهانی
        g, usd, g18, coin = last("g_gold"), last("i_usd"), last("i_gold18"), last("i_coin")
        if g and usd and g18 and coin and s["i_usd"].get(today):
            gram24 = g * usd / 31.1035
            s.setdefault("x_b18", {})[today] = round((g18 / (gram24 * 0.75) - 1) * 100, 2)
            s.setdefault("x_bcoin", {})[today] = round((coin / (gram24 * 8.133 * 0.9) - 1) * 100, 2)
    except Exception as e:
        err.append(f"bubble calc: {e}")
    for name in FUNDS:
        try:
            f = fund(name)
            data["funds"][name] = f
            s.setdefault("b_" + name, {})[today] = f["bubble"]
        except Exception as e:
            err.append(f"fund {name}: {e}")
    for key, qfa, qen in [("gold", "قیمت طلا", "gold price"), ("silver", "قیمت نقره", "silver price"), ("copper", "قیمت مس", "copper price")]:
        for suf, q, sites, loc in [("_fa", qfa, FA_SITES, ("fa", "IR", "IR:fa")), ("_en", qen, EN_SITES, ("en-US", "US", "US:en"))]:
            try:
                data["news"][key + suf] = news(q, sites, *loc)
            except Exception as e:
                err.append(f"news {key}{suf}: {e}")
    try:
        a = analyze(data)
        if a:
            data["analysis"] = a
    except Exception as e:
        err.append(f"analysis: {e}")
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    txt = json.dumps(data, ensure_ascii=False)
    (OUT / "data.json").write_text(txt, encoding="utf-8")
    (OUT / "data.js").write_text("window.DATA=" + txt + ";", encoding="utf-8")
    print("updated", data["updated"], "| errors:", len(err))

if __name__ == "__main__":
    main()
