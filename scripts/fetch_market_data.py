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


_TICKERS: dict | None = None


def cik_of(ticker: str) -> str:
    global _TICKERS
    if _TICKERS is None:
        _TICKERS = get_json("https://www.sec.gov/files/company_tickers.json")
    for row in _TICKERS.values():
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


# a broad, liquid cross-section: every sector, mega to large caps
UNIVERSE = [
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "TSLA",
    "JPM",
    "BAC",
    "WFC",
    "GS",
    "MS",
    "JNJ",
    "PFE",
    "MRK",
    "ABBV",
    "UNH",
    "LLY",
    "XOM",
    "CVX",
    "KO",
    "PEP",
    "PG",
    "WMT",
    "COST",
    "HD",
    "MCD",
    "NKE",
    "DIS",
    "NFLX",
    "INTC",
    "AMD",
    "CSCO",
    "ORCL",
    "CRM",
    "ADBE",
    "IBM",
    "QCOM",
    "BA",
    "CAT",
    "GE",
    "MMM",
    "HON",
    "UPS",
    "T",
    "VZ",
    "CMCSA",
    "SBUX",
    "TGT",
    "LOW",
]


def fetch_one(ticker: str, start: str, market_rows: list[tuple[str, float, float]], market: str) -> int:
    out = ROOT / ticker.upper()
    out.mkdir(parents=True, exist_ok=True)
    write_prices(out / "prices.csv", prices(ticker, start))
    write_prices(out / "market.csv", market_rows)
    cik = cik_of(ticker)
    name, rows = filings(cik, start)
    (out / "filings.json").write_text(
        json.dumps({"cik": cik, "name": name, "filings": rows}, indent=1), "utf-8"
    )
    (out / "fundamentals.json").write_text(json.dumps(fundamentals(cik), indent=1), "utf-8")
    today = datetime.now(UTC).date().isoformat()
    (out / "SOURCES.md").write_text(
        f"# {ticker.upper()} ({name})\n\nDownloaded {today} by `scripts/fetch_market_data.py`.\n\n"
        f"- `prices.csv`, `market.csv` ({market}): Yahoo Finance daily adjusted closes from {start}.\n"
        f"- `filings.json`: SEC EDGAR submissions for CIK {cik} (8-K with item codes, 10-Q, 10-K).\n"
        "- `fundamentals.json`: SEC XBRL company facts (diluted EPS, revenue) as first reported.\n",
        encoding="utf-8",
    )
    return len(rows)


def intraday(ticker: str) -> Path:
    from marketsim.realdata import utc_to_new_york

    """The last 60 days of 15-minute bars (Yahoo keeps no more at this interval), New York time,
    regular hours: `data/<T>/intraday_15m.csv` for `marketsim.intraday_fit`."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=15m&range=60d"
    d = get_json(url)["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    out = ROOT / ticker.upper() / "intraday_15m.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        f.write("time,close,volume\n")
        for t, c, v in zip(d["timestamp"], q["close"], q["volume"], strict=True):
            if c is None:
                continue
            ny = utc_to_new_york(datetime.fromtimestamp(t, UTC).replace(tzinfo=None))  # EST / EDT
            f.write(f"{ny.isoformat(timespec='minutes')},{c:.4f},{v or 0}\n")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tickers", nargs="*", help="tickers to fetch (default: the built-in universe)")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--market", default="SPY")
    ap.add_argument("--force", action="store_true", help="re-download tickers already in data/")
    ap.add_argument("--intraday", action="store_true", help="only fetch the last 60 days of 15-min bars")
    args = ap.parse_args()
    if args.intraday:
        for t in args.tickers or ["AAPL"]:
            print(f"wrote {intraday(t.upper())}")
        return
    tickers = [t.upper() for t in (args.tickers or UNIVERSE)]
    print(f"prices {args.market} …")
    market_rows = prices(args.market, args.start)
    failed = []
    for t in tickers:
        if (ROOT / t / "filings.json").exists() and not args.force:
            print(f"{t}: already there (use --force to refresh)")
            continue
        try:
            n = fetch_one(t, args.start, market_rows, args.market)
            print(f"{t}: {n} filings")
        except (Exception, SystemExit) as e:  # keep going: one bad ticker should not stop the batch
            failed.append(t)
            print(f"{t}: FAILED ({e})")
    if failed:
        print("failed:", " ".join(failed))


if __name__ == "__main__":
    main()
