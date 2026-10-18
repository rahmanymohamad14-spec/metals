# -*- coding: utf-8 -*-
"""جمع‌آوری: قیمت و حجم جهانی، ETFها، کلان (FRED)، موقعیت صندوق‌ها (CFTC COT)، قیمت ایران، حباب، خبر و تحلیل."""
import csv, io, json, os, re, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).parent / "docs"
UA = {"User-Agent": "Mozilla/5.0"}
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
FA_SITES = ["donya-e-eqtesad.com", "eghtesadonline.com", "isna.ir", "irna.ir", "tasnimnews.com", "mehrnews.com", "ecoiran.com", "tejaratnews.com"]
EN_SITES = ["reuters.com", "bloomberg.com", "kitco.com", "cnbc.com", "ft.com", "wsj.com"]
POS = ["افزایش", "صعود", "رشد", "جهش", "گران", "بالا رفت", "rise", "gain", "surge", "rally", "climb", "jump", "high"]
NEG = ["کاهش", "ریزش", "افت", "نزول", "ارزان", "پایین آمد", "fall", "drop", "slump", "slide", "decline", "tumble", "low"]

def get(url, data=None, headers=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def yahoo(sym):
    r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1y&interval=1d"))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    px, vol = {}, {}
    for t, c, v in zip(r["timestamp"], q["close"], q.get("volume") or [None] * len(r["timestamp"])):
        if c:
            d = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
            px[d], vol[d] = round(c, 3), int(v or 0)
    return px, vol

def fred(sid):
    rows = list(csv.reader(io.StringIO(get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"))))[1:]
    return {d: float(v) for d, v in rows[-300:] if v not in (".", "")}

def cot():
    names = {"088691": "gold", "084691": "silver", "085692": "copper"}
    where = "cftc_contract_market_code in('" + "','".join(names) + "')"
    url = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json?" + urllib.parse.urlencode(
        {"$where": where, "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": "480"})
    out = {n: [] for n in names.values()}
    for r in json.loads(get(url, timeout=30)):
        n = names.get(r.get("cftc_contract_market_code"))
        if n:
            out[n].append({"d": r["report_date_as_yyyy_mm_dd"][:10], "ml": float(r["m_money_positions_long_all"]),
                           "ms": float(r["m_money_positions_short_all"]), "oi": float(r["open_interest_all"]),
                           "pl": float(r.get("prod_merc_positions_long", 0)), "ps": float(r.get("prod_merc_positions_short", 0))})
    return {n: sorted(v, key=lambda x: x["d"]) for n, v in out.items()}

def tgju(slug):
    html = get(f"https://www.tgju.org/profile/{slug}")
    m = re.search(r'data-col="info\.last_trade\.PDrCotVal"[^>]*>\s*([\d,]+)', html)
    if not m:
        raise ValueError("عدد قیمت پیدا نشد")
    return float(m.group(1).replace(",", ""))

def num(rec, pats, bad=()):
    for k, v in rec.items():
        kl = k.lower()
        if isinstance(v, (int, float)) and v > 0 and any(p in kl for p in pats) and not any(b in kl for b in bad):
            return v

def funds_fipiran():
    j = json.loads(get("https://www.fipiran.ir/services/fund/fundcompare", b"{}", {"Content-Type": "application/json"}, 25))
    if isinstance(j, dict):
        j = next((v for v in j.values() if isinstance(v, list)), [])
    out = {}
    for r in j:
        if not isinstance(r, dict) or not any("طلا" in str(v) for v in r.values() if isinstance(v, str)):
            continue
        name = next((str(r[k]) for k in r if "name" in k.lower() and isinstance(r[k], str)), None)
        nav = num(r, ["nav"], ["issu", "sub", "chg", "chang", "percent", "eff", "date"])
        px = num(r, ["lastprice", "finalprice", "closeprice", "price"], ["nav", "issu", "sub", "chg"])
        if name and nav and px:
            out[name] = {"price": px, "nav": nav, "bubble": round((px / nav - 1) * 100, 2), "date": today}
    if not out:
        k = list(j[0].keys())[:25] if j and isinstance(j[0], dict) else []
        raise ValueError("ساختار پاسخ شناخته نشد؛ کلیدها: " + ",".join(k))
    return out

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
    last = {k: list(v.items())[-6:] for k, v in data["series"].items() if v and not k.startswith("v_")}
    cotl = {k: v[-3:] for k, v in data.get("cot", {}).items()}
    heads = {k: [n["t"] for n in v[:6]] for k, v in data["news"].items()}
    prompt = ("داده‌های اخیر:\n" + json.dumps(last, ensure_ascii=False) + "\n\nموقعیت صندوق‌ها (COT):\n" + json.dumps(cotl) +
              "\n\nحباب صندوق‌ها:\n" + json.dumps(data.get("funds", {}), ensure_ascii=False) +
              "\n\nتیتر خبرها:\n" + json.dumps(heads, ensure_ascii=False) +
              "\n\nمثل یک تحلیلگر کالا به فارسی و ساختارمند بنویس: ۱) طلا ۲) نقره ۳) مس (روند، حجم، موقعیت صندوق‌ها، کلان، حباب ایران) ۴) سناریوی صعودی و نزولی هر کدام با نشانه‌ی ابطال ۵) رویدادها و ریسک‌های پیش‌رو. "
              "اگر داده‌ای نیست صریح بگو. هیچ توصیه‌ی خرید یا فروش و پیش‌بینی قطعی نده.")
    body = json.dumps({"model": "claude-sonnet-5-5", "max_tokens": 2200, "messages": [{"role": "user", "content": prompt}]}).encode()
    r = json.loads(get("https://api.anthropic.com/v1/messages", body,
                       {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, 90))
    return "".join(b.get("text", "") for b in r["content"])

def main():
    OUT.mkdir(exist_ok=True)
    try:
        data = json.loads((OUT / "data.json").read_text(encoding="utf-8"))
    except Exception:
        data = {}
    for k in ("series", "news", "funds", "cot"):
        data.setdefault(k, {})
    data["errors"] = []
    s, err = data["series"], data["errors"]
    for key, sym, vol in [("g_gold", "GC=F", 1), ("g_silver", "SI=F", 1), ("g_copper", "HG=F", 1), ("g_plat", "PL=F", 0), ("g_oil", "CL=F", 0),
                          ("m_dxy", "DX-Y.NYB", 0), ("m_vix", "^VIX", 0), ("m_spx", "^GSPC", 0),
                          ("e_gld", "GLD", 1), ("e_slv", "SLV", 1), ("e_cper", "CPER", 1), ("e_gdx", "GDX", 1), ("e_copx", "COPX", 1)]:
        try:
            px, v = yahoo(sym)
            s.setdefault(key, {}).update(px)
            if vol:
                s.setdefault("v_" + key, {}).update(v)
        except Exception as e:
            err.append(f"{key}: {e}")
    for key, sid in [("r_real10", "DFII10"), ("r_be10", "T10YIE"), ("r_y10", "DGS10"), ("r_y2", "DGS2"), ("r_fed", "DFF")]:
        try:
            s.setdefault(key, {}).update(fred(sid))
        except Exception as e:
            err.append(f"{key}: {e}")
    try:
        data["cot"] = cot()
    except Exception as e:
        err.append(f"cot: {e}")
    for key, slug in [("i_gold18", "geram18"), ("i_gold24", "geram24"), ("i_mesghal", "mesghal"), ("i_coin", "sekee"),
                      ("i_coin_old", "sekeb"), ("i_half", "nim"), ("i_quarter", "rob"), ("i_usd", "price_dollar_rl"), ("i_silver", "silver_999")]:
        try:
            s.setdefault(key, {})[today] = tgju(slug)
        except Exception as e:
            err.append(f"{key}: {e}")
    last = lambda k: (sorted(s[k].items())[-1][1] if s.get(k) else None)
    try:
        g, usd, g18, coin = last("g_gold"), last("i_usd"), last("i_gold18"), last("i_coin")
        if g and usd and g18 and coin and s["i_usd"].get(today):
            gram24 = g * usd / 31.1035
            s.setdefault("x_b18", {})[today] = round((g18 / (gram24 * 0.75) - 1) * 100, 2)
            s.setdefault("x_bcoin", {})[today] = round((coin / (gram24 * 8.133 * 0.9) - 1) * 100, 2)
    except Exception as e:
        err.append(f"bubble calc: {e}")
    try:
        data["funds"] = funds_fipiran()
        for n, f in data["funds"].items():
            s.setdefault("b_" + n, {})[today] = f["bubble"]
    except Exception as e:
        err.append(f"funds: {e}")
    for key, qfa, qen in [("gold", "قیمت طلا", "gold price"), ("silver", "قیمت نقره", "silver price"), ("copper", "قیمت مس", "copper price"),
                          ("macro", "قیمت دلار", "Fed interest rate dollar inflation")]:
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
