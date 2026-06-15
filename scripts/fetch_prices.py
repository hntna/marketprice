#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch dữ liệu "chậm" cho bảng giá:
  - Vàng Bảo Tín Mạnh Hải (qua giavang.org - trang BTMH chính thức chặn bot)
  - Tỷ giá USD/VND Vietcombank (pXML chính, API portal mới làm fallback)
  - Dầu Brent/WTI (Yahoo Finance chính, Stooq làm fallback)
Ghi kết quả ra prices.json ở thư mục gốc repo, kèm history rolling.

Nguyên tắc: nguồn nào lỗi thì giữ giá trị cũ và đánh dấu stale=true,
không bao giờ bịa số. Tất cả giá vàng lưu ở VND/lượng (số tuyệt đối).
"""

import json
import re
import sys
import datetime
import pathlib
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) bang-gia-dashboard/1.0 "
                  "(personal dashboard; low frequency)"
}
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "prices.json"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")
HISTORY_MAX = 3500  # ~36 ngày với chu kỳ 15 phút


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=25, **kw)
    r.raise_for_status()
    return r


def ci_get(d, *names):
    """Lấy key không phân biệt hoa thường (phòng API đổi casing)."""
    low = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


# ---------------------------------------------------------------- BTMH gold
def parse_kvnd(s):
    """'133.300' (x1000đ/lượng) -> 133_300_000 VND. '-' -> None."""
    s = (s or "").strip()
    if not s or s in {"-", "–", "—"}:
        return None
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    v = int(digits)
    # Bảng giavang.org niêm yết theo nghìn đồng; nếu nguồn đổi sang VND
    # tuyệt đối (>10 triệu) thì không nhân 1000 nữa.
    return v * 1000 if v < 10_000_000 else v


def parse_btmh_html(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        name = cells[0]
        if not name or "loại" in name.lower():
            continue
        buy, sell = parse_kvnd(cells[1]), parse_kvnd(cells[2])
        if buy or sell:
            rows.append({"name": name, "buy": buy, "sell": sell})
    m = re.search(r"[Cc]ập nhật(?:\s+mới)?(?:\s+nhất)?\s+lúc\s*([\d:]+\s+[\d/]+)",
                  soup.get_text(" ", strip=True))
    return rows, (m.group(1) if m else None)


def pick_row(rows, keywords, need_sell=False):
    for kw in keywords:
        for r in rows:
            n = r["name"].lower()
            ok = r["sell"] is not None if need_sell else (r["buy"] or r["sell"])
            if kw in n and ok:
                return r
    return None


def fetch_btmh():
    html = get("https://giavang.org/trong-nuoc/bao-tin-manh-hai/").text
    rows, src_time = parse_btmh_html(html)
    gold_rows = [r for r in rows if "bạc" not in r["name"].lower()]
    sjc = pick_row(gold_rows, ["vàng miếng sjc", "sjc"])
    ring = pick_row(
        gold_rows,
        ["kim gia bảo 24k", "nhẫn tròn", "nhẫn ép vỉ", "trang sức 24k (999.9)"],
        need_sell=True,
    ) or pick_row(gold_rows, ["nhẫn", "kim gia bảo"])
    if not (sjc or ring):
        raise ValueError("không parse được dòng vàng nào")
    return {
        "source": "giavang.org (Bảo Tín Mạnh Hải)",
        "source_time": src_time,
        "unit": "VND/lượng",
        "sjc": sjc,
        "ring": ring,
    }


# ---------------------------------------------------------------- VCB USD
def _num(v):
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def fetch_vcb_usd():
    # Nguồn 1: feed XML cổ điển (chuẩn de facto nhiều năm nay)
    try:
        r = get("https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx?b=68")
        root = ET.fromstring(r.content)
        for ex in root.iter("Exrate"):
            if (ex.get("CurrencyCode") or "").upper() == "USD":
                return {
                    "source": "Vietcombank (pXML)",
                    "source_time": root.findtext("DateTime"),
                    "buy_cash": _num(ex.get("Buy")),
                    "buy_transfer": _num(ex.get("Transfer")),
                    "sell": _num(ex.get("Sell")),
                }
        raise ValueError("không thấy USD trong XML")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] VCB pXML lỗi: {e}", file=sys.stderr)

    # Nguồn 2: API của portal mới
    r = get("https://www.vietcombank.com.vn/api/exchangerates", params={"date": "now"})
    data = r.json()
    items = ci_get(data, "Data", "results", "items") or []
    for it in items:
        code = (ci_get(it, "currencyCode", "currency") or "").upper()
        if code == "USD":
            return {
                "source": "Vietcombank (API)",
                "source_time": ci_get(data, "UpdatedDate", "Date", "date"),
                "buy_cash": _num(ci_get(it, "cash", "buy_cash", "muaTienMat")),
                "buy_transfer": _num(ci_get(it, "transfer", "buy_transfer", "muaChuyenKhoan")),
                "sell": _num(ci_get(it, "sell", "banRa")),
            }
    raise ValueError("VCB: cả hai nguồn đều lỗi")


# ---------------------------------------------------------------- Oil
def yahoo_quote(symbol):
    r = get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": "1d", "interval": "15m"},
    )
    meta = r.json()["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    if price is None:
        raise ValueError(f"{symbol}: thiếu regularMarketPrice")
    return {
        "price": price,
        "prev_close": meta.get("chartPreviousClose") or meta.get("previousClose"),
    }


def stooq_quotes():
    # cb.f = Brent, cl.f = WTI; CSV: Symbol,Date,Time,Open,High,Low,Close,Volume
    r = get("https://stooq.com/q/l/?s=cb.f,cl.f&f=sd2t2ohlcv&h&e=csv")
    out = {}
    for line in r.text.strip().splitlines()[1:]:
        p = line.split(",")
        if len(p) >= 7:
            try:
                out[p[0].lower()] = {"price": float(p[6]), "prev_close": None}
            except ValueError:
                pass
    return out


def fetch_oil():
    try:
        return {
            "source": "Yahoo Finance",
            "unit": "USD/thùng",
            "brent": yahoo_quote("BZ=F"),
            "wti": yahoo_quote("CL=F"),
        }
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Yahoo lỗi: {e}", file=sys.stderr)
    q = stooq_quotes()
    if q.get("cb.f") or q.get("cl.f"):
        return {
            "source": "Stooq",
            "unit": "USD/thùng",
            "brent": q.get("cb.f"),
            "wti": q.get("cl.f"),
        }
    raise ValueError("dầu: cả hai nguồn đều lỗi")


# ---------------------------------------------------------------- Indices
def fetch_indices():
    out = {"source": "CafeF / Yahoo", "vnindex": None, "spx": None}
    
    # VNINDEX from CafeF
    try:
        r = get("https://banggia.cafef.vn/stockhandler.ashx?index=true")
        data = r.json()
        for idx in data:
            if idx.get("name") == "VNINDEX":
                out["vnindex"] = {
                    "price": float(idx["index"].replace(",", "")),
                    "change": float(idx["change"].replace(",", "")),
                    "percent": float(idx["percent"].replace(",", ""))
                }
                break
    except Exception as e:
        print(f"[warn] CafeF VNINDEX lỗi: {e}", file=sys.stderr)

    # SPX from Yahoo
    try:
        out["spx"] = yahoo_quote("^GSPC")
    except Exception as e:
        print(f"[warn] Yahoo SPX lỗi: {e}", file=sys.stderr)
        
    if not out["vnindex"] and not out["spx"]:
        raise ValueError("Cả VNINDEX và SPX đều lỗi")
    return out


# ---------------------------------------------------------------- main
def main():
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass

    now = datetime.datetime.now(TZ)
    data = {"updated_at": now.isoformat(timespec="seconds")}
    ok = 0
    for key, fn in (("gold_btmh", fetch_btmh),
                    ("usd_vnd", fetch_vcb_usd),
                    ("oil", fetch_oil),
                    ("indices", fetch_indices)):
        try:
            data[key] = fn()
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {key} lỗi: {e}", file=sys.stderr)
            if prev.get(key):
                data[key] = {**prev[key], "stale": True}

    # Fetch chart data directly from Binance to avoid client-side AdBlockers
    try:
        btc_res = get("https://api.binance.com/api/v3/klines", params={"symbol": "BTCUSDT", "interval": "1h", "limit": 120}).json()
        xau_res = get("https://api.binance.com/api/v3/klines", params={"symbol": "PAXGUSDT", "interval": "1h", "limit": 120}).json()
        data["chart_btc"] = [[c[0], float(c[4])] for c in btc_res]
        data["chart_xau"] = [[c[0], float(c[4])] for c in xau_res]
        data["btc_price"] = data["chart_btc"][-1][1] if data["chart_btc"] else None
        data["xau_price"] = data["chart_xau"][-1][1] if data["chart_xau"] else None
        ok += 1
    except Exception as e:
        print(f"[warn] binance klines lỗi: {e}", file=sys.stderr)
        if prev.get("chart_btc"): data["chart_btc"] = prev["chart_btc"]
        if prev.get("chart_xau"): data["chart_xau"] = prev["chart_xau"]
        data["btc_price"] = data["chart_btc"][-1][1] if data.get("chart_btc") else None
        data["xau_price"] = data["chart_xau"][-1][1] if data.get("chart_xau") else None

    if ok == 0 and prev:
        print("Tất cả nguồn đều lỗi — giữ nguyên prices.json cũ.", file=sys.stderr)
        return 0

    # History rolling để sau này vẽ sparkline nếu muốn
    hist = list(prev.get("history") or [])
    point = {"t": data["updated_at"]}
    try: point["usd_sell"] = data["usd_vnd"].get("sell")
    except Exception: pass
    try: point["gold_ring_sell"] = (data["gold_btmh"].get("ring") or {}).get("sell")
    except Exception: pass
    try: point["gold_sjc_sell"] = (data["gold_btmh"].get("sjc") or {}).get("sell")
    except Exception: pass
    try: point["brent"] = (data["oil"].get("brent") or {}).get("price")
    except Exception: pass
    try: point["wti"] = (data["oil"].get("wti") or {}).get("price")
    except Exception: pass
    try: point["vnindex"] = (data.get("indices") or {}).get("vnindex", {}).get("price")
    except Exception: pass
    try: point["spx"] = (data.get("indices") or {}).get("spx", {}).get("price")
    except Exception: pass
    try: point["btc"] = data.get("btc_price")
    except Exception: pass
    try: point["xau"] = data.get("xau_price")
    except Exception: pass
    
    # Tính chênh lệch vàng SJC - Thế giới
    try:
        sjc_sell = point.get("gold_sjc_sell")
        xau = point.get("xau")
        usd = point.get("usd_sell")
        if sjc_sell and xau and usd:
            world = xau * usd * 1.20565
            point["spread"] = sjc_sell - world
    except Exception: pass
    
    hist.append(point)
    data["history"] = hist[-HISTORY_MAX:]

    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Đã ghi {OUT.name} ({ok}/5 nguồn thành công, {now:%H:%M %d/%m/%Y})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
