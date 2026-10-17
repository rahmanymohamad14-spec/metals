# -*- coding: utf-8 -*-
import json, os, re, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).parent / "docs"
UA = {"User-Agent": "Mozilla/5.0"}
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")

def yahoo(sym):
    r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=3mo&interval=1d"))["chart"]["result"][0]
    cl = r["indicators"]["quote"][0]["close"]
    return {datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"): round(c, 3)
            for t, c in zip(r["timestamp"], cl) if c}

def tgju(slug):
    html = get(f"https://www.tgju.org/profile/{slug}")
    m = re.search(r'data-col="info\.last_trade\.PDrCotVal"[^>]*>\s*([\d,]+)', html)
    if not m:
        raise ValueError("عدد قیمت در صفحه پیدا نشد")
    return float(m.group(1).replace(",", ""))

def news(q):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q + " when:2d", "hl": "fa", "gl": "IR", "ceid": "IR:fa"})
    return [{"t": i.findtext("title"), "u": i.findtext("link"), "d": i.findtext("pubDate")}
            for i in ET.fromstring(get(url)).iter("item")][:8]

def analyze(data):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    last = {k: list(v.items())[-5:] for k, v in data["series"].items() if v}
    heads = {k: [n["t"] for n in v] for k, v in data["news"].items()}
    prompt = ("قیمت‌های اخیر (تاریخ، قیمت):\n" + json.dumps(last, ensure_ascii=False) +
              "\n\nتیترهای خبر:\n" + json.dumps(heads, ensure_ascii=False) +
              "\n\nبه فارسی و کوتاه برای طلا، نقره و مس جداگانه بنویس: روند اخیر، عوامل خبری مهم، ریسک‌ها و نکات نامعلوم. "
              "هیچ توصیه‌ی خرید یا فروش نده و پیش‌بینی قطعی نکن.")
    body = json.dumps({"model": "claude-sonnet-5-5", "max_tokens": 1200,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    r = json.loads(get("https://api.anthropic.com/v1/messages", body,
                       {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}))
    return "".join(b.get("text", "") for b in r["content"])

def main():
    OUT.mkdir(exist_ok=True)
    try:
        data = json.loads((OUT / "data.json").read_text(encoding="utf-8"))
    except Exception:
        data = {"series": {}, "news": {}}
    data["errors"] = []
    s = data["series"]
    for key, sym in [("g_gold", "GC=F"), ("g_silver", "SI=F"), ("g_copper", "HG=F")]:
        try:
            s.setdefault(key, {}).update(yahoo(sym))
        except Exception as e:
            data["errors"].append(f"{key}: {e}")
    for key, slug in [("i_gold18", "geram18"), ("i_coin", "sekee"), ("i_usd", "price_dollar_rl"), ("i_silver", "silver_999")]:
        try:
            s.setdefault(key, {})[today] = tgju(slug)
        except Exception as e:
            data["errors"].append(f"{key}: {e}")
    for key, q in [("gold", "قیمت طلا"), ("silver", "قیمت نقره"), ("copper", "قیمت مس")]:
        try:
            data["news"][key] = news(q)
        except Exception as e:
            data["errors"].append(f"news {key}: {e}")
    try:
        a = analyze(data)
        if a:
            data["analysis"] = a
    except Exception as e:
        data["errors"].append(f"analysis: {e}")
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    txt = json.dumps(data, ensure_ascii=False)
    (OUT / "data.json").write_text(txt, encoding="utf-8")
    (OUT / "data.js").write_text("window.DATA=" + txt + ";", encoding="utf-8")
    print("updated", data["updated"], "| errors:", len(data["errors"]))

if __name__ == "__main__":
    main()
