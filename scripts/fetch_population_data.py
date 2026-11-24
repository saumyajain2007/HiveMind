"""Build the agent population's real-data inputs: `data/population/us.json` (run once).

    uv run --with pandas python scripts/fetch_population_data.py

Sources (free, no key; requests carry a generic User-Agent):

* **US Census Bureau, Vintage 2024 national population estimates by single year of age**
  (nc-est2024-agesex-res.csv): the age distribution of adults (18+).
* **Federal Reserve Survey of Consumer Finances 2022, summary extract** (rscfp2022.dta,
  22,975 records = 4,595 households x 5 implicates, with survey weights): the distribution of
  household financial assets (FIN, "investable wealth"), the 0-10 self-rated financial
  knowledge (KNOWL), willingness to take financial risk (YESFINRISK / NOFINRISK), direct stock
  ownership (HSTOCKS), and the correlations between them and age, estimated on normal scores
  (the Gaussian-copula correlation the population generator uses), plus a weighted logistic
  regression of stock ownership on those traits (the investor logit).

Everything is weighted by the survey weights. The SCF describes households (age = the head's
age); it is used for wealth, knowledge, risk and ownership, while age itself comes from the
Census. pandas is only needed here, not by the engine.
"""

from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

UA = "marketsim-research/0.1 (open-source research tool)"
OUT = Path(__file__).resolve().parents[1] / "data" / "population"
CENSUS = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/national/asrh/nc-est2024-agesex-res.csv"
SCF = "https://www.federalreserve.gov/econres/files/scfp2022s.zip"
GRID = 201  # quantile grid points


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def wquantiles(x: np.ndarray, w: np.ndarray, n: int = GRID) -> list[float]:
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = (np.cumsum(w) - 0.5 * w) / w.sum()
    return np.interp(np.linspace(0, 1, n), c, x).tolist()


def normal_scores(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Weighted mid-ranks -> standard normal scores (ties share a score)."""
    from scipy.stats import norm

    o = np.argsort(x, kind="stable")
    xs, ws = x[o], w[o]
    c = np.cumsum(ws)
    # mid-rank of each tie block
    _, start, counts = np.unique(xs, return_index=True, return_counts=True)
    mid = np.empty_like(c)
    for s, k in zip(start, counts, strict=True):
        lo = c[s - 1] if s > 0 else 0.0
        mid[s : s + k] = (lo + c[s + k - 1]) / 2
    u = np.empty_like(mid)
    u[o] = mid / c[-1]
    return norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))


def wcorr(a: np.ndarray, b: np.ndarray, w: np.ndarray) -> float:
    ma, mb = np.average(a, weights=w), np.average(b, weights=w)
    cov = np.average((a - ma) * (b - mb), weights=w)
    return float(cov / np.sqrt(np.average((a - ma) ** 2, weights=w) * np.average((b - mb) ** 2, weights=w)))


def wlogit(X: np.ndarray, y: np.ndarray, w: np.ndarray, iters: int = 50) -> np.ndarray:
    A = np.c_[np.ones(len(y)), X]
    beta = np.zeros(A.shape[1])
    w = w / w.mean()
    for _ in range(iters):
        p = 1 / (1 + np.exp(-A @ beta))
        g = A.T @ (w * (y - p))
        H = (A * (w * p * (1 - p))[:, None]).T @ A + 1e-6 * np.eye(A.shape[1])
        step = np.linalg.solve(H, g)
        beta += step
        if np.abs(step).max() < 1e-8:
            break
    return beta


def census_ages() -> tuple[list[float], dict]:
    import pandas as pd

    df = pd.read_csv(io.BytesIO(get(CENSUS)))
    df = df[(df["SEX"] == 0) & (df["AGE"] >= 18) & (df["AGE"] <= 85)]
    ages = df["AGE"].to_numpy(float)
    n = df["POPESTIMATE2024"].to_numpy(float)
    # spread each single year uniformly over [a, a+1); the 85+ bucket over [85, 95)
    pts = np.concatenate([a + np.linspace(0.05, 0.95, 10) * (10 if a == 85 else 1) for a in ages])
    wts = np.repeat(n / 10, 10)
    return wquantiles(pts, wts), {"adults": float(n.sum()), "median_age": float(wquantiles(pts, wts, 3)[1])}


def scf() -> dict:
    import pandas as pd

    z = zipfile.ZipFile(io.BytesIO(get(SCF)))
    name = next(n for n in z.namelist() if n.endswith(".dta"))
    d = pd.read_stata(io.BytesIO(z.read(name)), convert_categoricals=False)
    w = d["wgt"].to_numpy(float)
    age = d["age"].to_numpy(float)
    fin = np.maximum(d["fin"].to_numpy(float), 100.0)  # floor: log scale, no zero wealth
    knowl = d["knowl"].to_numpy(float)
    knowl = np.where(knowl < 0, np.nan, knowl)
    ok = ~np.isnan(knowl)
    risk = np.where(d["yesfinrisk"].to_numpy() == 1, 2.0, np.where(d["nofinrisk"].to_numpy() == 1, 0.0, 1.0))
    hstocks = (d["hstocks"].to_numpy() == 1).astype(float)
    hfunds = ((d["hstocks"].to_numpy() == 1) | (d["hnmmf"].to_numpy() == 1)).astype(float)
    a, w2 = age[ok], w[ok]
    z_age, z_w = normal_scores(a, w2), normal_scores(fin[ok], w2)
    z_k, z_r = normal_scores(knowl[ok], w2), normal_scores(risk[ok], w2)
    corr = {
        "age,wealth": wcorr(z_age, z_w, w2),
        "age,knowledge": wcorr(z_age, z_k, w2),
        "age,risk_tolerance": wcorr(z_age, z_r, w2),
        "wealth,knowledge": wcorr(z_w, z_k, w2),
        "wealth,risk_tolerance": wcorr(z_w, z_r, w2),
        "knowledge,risk_tolerance": wcorr(z_k, z_r, w2),
    }
    beta = wlogit(np.c_[z_w, z_k, z_r], hstocks[ok], w2)
    return {
        "wealth_quantiles": wquantiles(fin, w),
        "knowledge_quantiles": (np.array(wquantiles(knowl[ok], w2)) / 10.0).tolist(),
        "investor_share": float(np.average(hstocks, weights=w)),
        "stock_or_fund_share": float(np.average(hfunds, weights=w)),
        "correlations": corr,
        "investor_logit": {
            "wealth": float(beta[1]),
            "knowledge": float(beta[2]),
            "risk_tolerance": float(beta[3]),
        },
        "summary": {
            "households": float(w.sum() / 5),
            "median_financial_assets": float(wquantiles(fin, w, 3)[1]),
            "median_net_worth": float(wquantiles(d["networth"].to_numpy(float), w, 3)[1]),
            "share_willing_above_average_risk": float(np.average(risk == 2, weights=w)),
            "share_no_risk": float(np.average(risk == 0, weights=w)),
            "median_knowledge_0_10": float(wquantiles(knowl[ok], w2, 3)[1]),
        },
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("Census age distribution …")
    ages, census = census_ages()
    print("Survey of Consumer Finances 2022 …")
    s = scf()
    doc = {
        "country": "US",
        "downloaded": datetime.now(UTC).date().isoformat(),
        "sources": {
            "age": f"US Census Bureau, Vintage 2024 population estimates by single year of age ({CENSUS})",
            "wealth, knowledge, risk, ownership, correlations": f"Federal Reserve SCF 2022 summary extract ({SCF})",
        },
        "age_quantiles": ages,
        "census": census,
        **s,
    }
    (OUT / "us.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in doc.items() if not k.endswith("quantiles")}, indent=1))
    print(f"wrote {OUT / 'us.json'}")


if __name__ == "__main__":
    main()
