"""Download a stock's real history into `data/<TICKER>/` (run once; the engine never goes online).

    uv run python scripts/fetch_market_data.py AAPL --start 2015-01-01

Sources (free, no key):
* Daily prices: Yahoo Finance chart API, split- and dividend-adjusted closes, for the stock and
  for SPY (the market, used by the event study).
* Events: SEC EDGAR filings of the company (8-K with their item codes, 10-Q, 10-K), with the
  exact acceptance time.
* Fundamentals: SEC XBRL company facts (quarterly diluted EPS and revenue as reported), used as
  features known at the earnings announcement.

Writes prices.csv, market.csv (date, close, volume), filings.json, fundamentals.json and
SOURCES.md with the download date. Nothing personal is sent: requests carry a generic
User-Agent.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

UA = "marketsim-research/0.1 (open-source research tool)"
ROOT = Path(__file__).resolve().parents[1] / "data"
KEEP_FORMS = {"8-K", "8-K/A", "10-Q", "10-K"}


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    time.sleep(0.15)  # stay well under SEC's 10 requests / second
    return data


def prices(symbol: str, start: str) -> list[tuple[str, float, float]]:
    t0 = int(datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp())
    t1 = int(time.time())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={t0}&period2={t1}"
        "&interval=1d&events=div%2Csplit&includeAdjustedClose=true"
    )
    res = get_json(url)["chart"]["result"][0]
    tz = timezone(timedelta(seconds=res["meta"]["gmtoffset"]))
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    vol = res["indicators"]["quote"][0]["volume"]
    out = []
    for ts, c, v in zip(res["timestamp"], adj, vol, strict=True):
        if c is None:
            continue
        day = datetime.fromtimestamp(ts, tz).date().isoformat()
        out.append((day, round(float(c), 6), float(v or 0)))
    # Yahoo can repeat the last (live) day; keep the final value per date
    dedup = {d: (d, c, v) for d, c, v in out}
    return sorted(dedup.values())


def write_prices(path: Path, rows: list[tuple[str, float, float]]) -> None:
    path.write_text(
        "date,close,volume\n" + "".join(f"{d},{c},{int(v)}\n" for d, c, v in rows), encoding="utf-8"
    )


def cik_of(ticker: str) -> str:
    table = get_json("https://www.sec.gov/files/company_tickers.json")
    for row in table.values():
        if row["ticker"].upper() == ticker.upper():
            return f"{int(row['cik_str']):010d}"
    raise SystemExit(f"{ticker} not found in SEC's ticker list")


def filings(cik: str, start: str) -> tuple[str, list[dict]]:
    sub = get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    pages = [sub["filings"]["recent"]]
    for f in sub["filings"].get("files", []):
        pages.append(get_json(f"https://data.sec.gov/submissions/{f['name']}"))
    out = []
    for p in pages:
        for i, form in enumerate(p["form"]):
            if form not in KEEP_FORMS or p["filingDate"][i] < start:
                continue
            out.append(
                {
                    "form": form,
                    "filing_date": p["filingDate"][i],
                    # EDGAR acceptance time, UTC (converted to New York time by marketsim.realdata)
                    "accepted": p["acceptanceDateTime"][i][:19],
                    "items": [x for x in (p.get("items", [""] * len(p["form"]))[i] or "").split(",") if x],
                    "accession": p["accessionNumber"][i],
                    "description": p.get("primaryDocDescription", [""] * len(p["form"]))[i],
                }
            )
    return sub["name"], sorted(out, key=lambda r: r["accepted"])


def fundamentals(cik: str) -> dict[str, list[dict]]:
    facts = get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")["facts"].get("us-gaap", {})
    wanted = {
        "eps_diluted": ["EarningsPerShareDiluted"],
        "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    }
    out: dict[str, list[dict]] = {}
    for key, tags in wanted.items():
        rows: dict[tuple[str, str], dict] = {}
        for tag in tags:
            for unit_rows in facts.get(tag, {}).get("units", {}).values():
                for r in unit_rows:
                    if "start" not in r or r.get("form") not in ("10-Q", "10-K"):
                        continue
                    k = (r["start"], r["end"])
                    # keep the first filing of each period (as originally reported)
                    if k not in rows or r["filed"] < rows[k]["filed"]:
                        rows[k] = {
                            "start": r["start"],
                            "end": r["end"],
                            "value": r["val"],
                            "filed": r["filed"],
                        }
        out[key] = sorted(rows.values(), key=lambda r: (r["end"], r["start"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ticker")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--market", default="SPY")
    args = ap.parse_args()
    out = ROOT / args.ticker.upper()
    out.mkdir(parents=True, exist_ok=True)
    print(f"prices {args.ticker} / {args.market} …")
    write_prices(out / "prices.csv", prices(args.ticker, args.start))
    write_prices(out / "market.csv", prices(args.market, args.start))
    print("SEC filings …")
    cik = cik_of(args.ticker)
    name, rows = filings(cik, args.start)
    (out / "filings.json").write_text(
        json.dumps({"cik": cik, "name": name, "filings": rows}, indent=1), "utf-8"
    )
    print("SEC fundamentals …")
    (out / "fundamentals.json").write_text(json.dumps(fundamentals(cik), indent=1), "utf-8")
    today = datetime.now(UTC).date().isoformat()
    (out / "SOURCES.md").write_text(
        f"# {args.ticker.upper()} ({name})\n\nDownloaded {today} by `scripts/fetch_market_data.py`.\n\n"
        f"- `prices.csv`, `market.csv` ({args.market}): Yahoo Finance daily adjusted closes from {args.start}.\n"
        f"- `filings.json`: SEC EDGAR submissions for CIK {cik} (8-K with item codes, 10-Q, 10-K).\n"
        "- `fundamentals.json`: SEC XBRL company facts (diluted EPS, revenue) as first reported.\n",
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(rows)} filings)")


if __name__ == "__main__":
    main()
