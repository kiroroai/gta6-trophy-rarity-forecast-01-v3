"""Refresh-inversion forecaster v3 for gta6-trophy-rarity-forecast-01.

Two regimes, chosen by the case's own history:

FROZEN PAGE (every read identical — the launch-night practice shape).
The frozen page's rates times its players_tracked are exact per-trophy
earner counts. A refresh recomputes each rate as earners / new pool, so
the refreshed rate is the old count plus new earners, divided by the new
pool. We invert that arithmetic instead of scaling rates: recover the
counts, model new earners per trophy as a global growth factor (lognormal
grid) times a per-trophy velocity (tier/secret prior, lognormal grid)
times the count, plus small count jitter, and mix over the answer pool:
the first refresh's 3,868 players, or — for targets after it — a possible
second refresh with a larger pool and a second, smaller growth step. A
trophy already earned by the whole pool stays at 100%. A wide robust
mixture component (15%) keeps the intervals honest if the growth is
noisier than the central model. Quantiles come from the exact CDF of the
rounded refreshed rate.

MOVING PAGE (the final's shape). Distinct pages only; per trophy a
duration-weighted linear fit of logit(rate) on ln(1 + hours/24) over the
last 24 hours of pages. The fitted slope is shrunk toward the
precision-weighted mean slope of the trophy's tier (empirical Bayes),
damped to 70%, extrapolated to the answer-effective time (the target
minus the expected refresh staleness E[g^2]/(2E[g]) over the observed
refresh gaps, since the answer is the page as of Exophase's last
refresh before the target), with the total move capped.
Spread is the fit's residual sd plus a slope-uncertainty term and a
floor, calibrated on synthetic launch dynamics.

Deterministic, standard library only.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
ZS = [-1.6448536269514722, -0.6744897501960817, 0.0,
      0.6744897501960817, 1.6448536269514722]
RELEASE = "2026-11-19T00:00:00Z"

# ---------------- frozen-regime constants ----------------
FIRST_REFRESH_AT = "2026-11-19T04:30:00Z"
P_FIRST = 3868.0            # players_tracked at the first refresh
G_MED = 0.20                # median global earner growth over the horizon
G2_MED = 0.10               # growth of a second refresh step
S_ETA = 0.20                # count jitter sd (earners)
PSEC_TAU = 200.0            # minutes scale for a second refresh's odds
ROBUST_W = 0.15             # weight of the wide robust mixture component
P2_MULTS = [(1.15, 0.35), (1.28, 0.35), (1.42, 0.30)]

# ---------------- moving-regime constants ----------------
WINDOW_H = 24.0
DAMP = 0.7
CAL = 0.9
CAP_MOVE = 2.2
TAU_SLOPE = 0.55
SLOPE_UNC = 0.2
SPREAD_FLOOR = 0.12


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _logit(pct):
    p = min(max(pct, 0.01), 99.99) / 100.0
    return math.log(p / (1.0 - p))


def _inv_logit(l):
    return 100.0 / (1.0 + math.exp(-l))


def _lognorm_grid(sd):
    """(multiplier, weight) points discretising a median-1 lognormal."""
    zs = [-1.2816, -0.5244, 0.0, 0.5244, 1.2816]
    ws = [0.10, 0.22, 0.30, 0.22, 0.16]
    return [(math.exp(sd * z), w) for z, w in zip(zs, ws)]


# ================= frozen regime =================

def _velocity_hat(trophy):
    tier = trophy["tier"]
    if tier == "platinum":
        v = 0.20
    elif tier == "gold":
        v = 0.82
    elif tier == "silver":
        v = 0.90
    else:
        v = 1.00
    if trophy.get("secret"):
        v *= 1.28
    return v


def _growth_dist(E, g, vhat, vgrid, eta):
    """{count: prob} for count = E + max(0, round(g * v * E + jitter)),
    with v integrated over the velocity grid and jitter ~ N(0, eta)."""
    out = {}
    base = max(E, 0.35)
    for vm, vw in vgrid:
        mu = g * vhat * vm * base
        lo = max(0, int(math.floor(mu - 5 * eta)) - 1)
        hi = int(math.ceil(mu + 5 * eta)) + 1
        for n in range(lo, hi + 1):
            p = 0.5 * (math.erf((n + 0.5 - mu) / (eta * math.sqrt(2.0)))
                       - math.erf((n - 0.5 - mu) / (eta * math.sqrt(2.0))))
            if p > 1e-10:
                out[E + n] = out.get(E + n, 0.0) + vw * p
    return out


def _apply_second(dist, g2, vhat, vgrid, eta):
    out = {}
    for K, p in dist.items():
        sub = _growth_dist(K, g2, vhat, vgrid, eta)
        for K2, p2 in sub.items():
            out[K2] = out.get(K2, 0.0) + p * p2
    return out


def _quantiles_from_dist(ydist):
    ys = sorted(ydist)
    cdf = []
    acc = 0.0
    for y in ys:
        acc += ydist[y]
        cdf.append(acc)
    qs = []
    for tau in LEVELS:
        q = ys[-1]
        for y, c in zip(ys, cdf):
            if c >= tau:
                q = y
                break
        qs.append(q)
    return qs


def forecast_frozen(case):
    last = case["history"][-1]
    P0 = last["players_tracked"]
    m_after = (_ts(case["target"]) - _ts(FIRST_REFRESH_AT)) / 60.0
    p_second = 0.0 if m_after <= 0 else 1.0 - math.exp(-m_after / PSEC_TAU)
    comps = [
        (1.0 - ROBUST_W, _lognorm_grid(0.28), _lognorm_grid(0.27), S_ETA),
        (ROBUST_W, _lognorm_grid(0.55), _lognorm_grid(1.05), 1.0),
    ]
    out = {}
    for trophy, r in zip(case["trophies"], last["rates"]):
        r = 0.01 if r is None else r
        E = int(round(r * P0 / 100.0))
        if r >= 99.99 or (P0 and E >= P0):
            # earned by the whole tracked pool: stays at 100% on refresh
            out[trophy["id"]] = [99.90, 99.95, 99.98, 99.99, 99.99]
            continue
        vhat = _velocity_hat(trophy)
        ydist = {}
        for cw, ggrid, vgrid, eta in comps:
            for gm, gw in ggrid:
                dist = _growth_dist(E, gm * G_MED, vhat, vgrid, eta)
                for K, p in dist.items():
                    y = round(100.0 * K / P_FIRST, 2)
                    ydist[y] = ydist.get(y, 0.0) + cw * (1.0 - p_second) * gw * p
                if p_second > 0:
                    for pm, pw in P2_MULTS:
                        dist2 = _apply_second(dist, gm * G2_MED, vhat, vgrid, eta)
                        P2 = P_FIRST * pm
                        for K, p in dist2.items():
                            y = round(100.0 * K / P2, 2)
                            ydist[y] = ydist.get(y, 0.0) + cw * p_second * gw * pw * p
        out[trophy["id"]] = _quantiles_from_dist(ydist)
    return out


# ================= moving regime =================

def _distinct_pages(case):
    pages = []
    for rd in case["history"]:
        if (not pages or rd["rates"] != pages[-1][2]
                or rd["players_tracked"] != pages[-1][1]):
            pages.append((_ts(rd["at"]), rd["players_tracked"], rd["rates"]))
    return pages


def forecast_moving(case, pages):
    t0 = _ts(RELEASE)
    times = [(p[0] - t0) / 3600.0 for p in pages]
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    med_gap = sorted(gaps)[len(gaps) // 2] if gaps else 3.0
    t_last = times[-1]
    t_tgt = (_ts(case["target"]) - t0) / 3600.0
    # Expected age of the page the target read shows: for a renewal
    # refresh process the staleness at a fixed time is E[g^2] / (2 E[g])
    # over the observed refresh gaps (length-biased), not half a gap.
    if gaps:
        staleness = sum(g * g for g in gaps) / (2.0 * sum(gaps))
    else:
        staleness = 0.5 * med_gap
    t_ans = max(t_tgt - staleness, t_last + 0.05)

    def xof(t):
        return math.log1p(t / 24.0)

    dx = xof(t_ans) - xof(t_last)
    keep = [i for i, t in enumerate(times) if t >= t_last - WINDOW_H]
    if len(keep) < 3:
        keep = list(range(max(0, len(times) - 3), len(times)))
    xs = [xof(times[i]) for i in keep]
    ws = []
    for i in keep:
        g = gaps[i] if i < len(gaps) else med_gap
        ws.append(min(max(g, 0.05), 12.0))
    fits = []
    for j, trophy in enumerate(case["trophies"]):
        ys = [_logit(0.01 if pages[i][2][j] is None else pages[i][2][j])
              for i in keep]
        sw = sum(ws)
        mx = sum(w * v for v, w in zip(xs, ws)) / sw
        my = sum(w * v for v, w in zip(ys, ws)) / sw
        sxx = sum(w * (v - mx) ** 2 for v, w in zip(xs, ws))
        sxy = sum(w * (a - mx) * (b - my) for a, b, w in zip(xs, ys, ws))
        slope = sxy / sxx if sxx > 1e-12 else 0.0
        resid = [y - (my + slope * (v - mx)) for v, y in zip(xs, ys)]
        dof = max(len(ys) - 2, 1)
        sd = math.sqrt(sum(w * r * r for r, w in zip(resid, ws)) / sw
                       * (len(ys) / dof))
        b_se = sd / math.sqrt(sxx) if sxx > 1e-12 else 1.0
        fits.append(dict(tier=trophy["tier"], slope=slope, sd=sd,
                         b_se=max(b_se, 0.05), ylast=ys[-1]))
    cats = {}
    for f in fits:
        cats.setdefault(f["tier"], []).append(f)
    cat_slope = {}
    for tier, fs in cats.items():
        wp = sum(1.0 / (f["b_se"] ** 2) for f in fs)
        cat_slope[tier] = sum(f["slope"] / (f["b_se"] ** 2) for f in fs) / wp
    out = {}
    for trophy, f in zip(case["trophies"], fits):
        prec = 1.0 / (f["b_se"] ** 2)
        prec_cat = 1.0 / (TAU_SLOPE ** 2)
        slope = (f["slope"] * prec + cat_slope[f["tier"]] * prec_cat) \
            / (prec + prec_cat)
        move = max(-CAP_MOVE, min(CAP_MOVE, DAMP * slope * dx))
        med = f["ylast"] + move
        s = CAL * (f["sd"] + SLOPE_UNC * f["b_se"] + SPREAD_FLOOR)
        out[trophy["id"]] = [_inv_logit(med + z * s) for z in ZS]
    return out


# ================= driver =================

def forecast(case):
    pages = _distinct_pages(case)
    if len(pages) <= 1:
        return forecast_frozen(case)
    return forecast_moving(case, pages)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        fc = forecast(case)
        rows = []
        for trophy in case["trophies"]:
            qs = []
            prev = 0.0
            for q in fc[trophy["id"]]:
                v = min(100.0, max(0.0, round(float(q), 4)))
                v = max(v, prev)  # keep quantiles non-decreasing
                qs.append(v)
                prev = v
            rows.append({"id": trophy["id"], "q": qs})
        out_path = OUTPUT_DIR / (path.stem + ".out")
        out_path.write_text(json.dumps({"trophies": rows}),
                            encoding="utf-8")


if __name__ == "__main__":
    main()
