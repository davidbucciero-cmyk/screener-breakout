"""Transport de distributions entre regimes : prevoit-il mieux les rendements a 5 jours ?

Idee testee (vue sur un graphique "Price Forecast") : la distribution des rendements
d'un regime est transportee vers celle du regime suivant "en lignes droites".
En 1D, le transport optimal en ligne droite revient a moyenner les fonctions
quantiles : Q(u) = somme_k P(k | regime actuel) * Q_k(u)  (barycentre de Wasserstein).

Regimes (memes que le test Jev) : sens x volatilite de la fenetre de 5 seances.
Toutes les estimations a la date D n'utilisent que des rendements deja connus en D.

Modeles compares, tous en quantiles du rendement log a 5 seances :
  - Inconditionnel      : quantiles des rendements 5j passes
  - Vol EWMA            : quantiles des rendements normalises, remis a l'echelle de la vol du jour
  - Regime (melange)    : rendements passes qui ont suivi le meme regime qu'aujourd'hui
  - Transport           : barycentre des distributions des regimes suivants (lignes droites)
  - Transport + vol     : idem sur rendements normalises, remis a l'echelle de la vol du jour
Scores : CRPS (plus bas = mieux), couverture des intervalles 50 % et 80 %, Brier du sens.
"""
import os
import sys

import numpy as np
import pandas as pd

REGIMES = ["haussier_calme", "haussier_volatil", "baissier_calme", "baissier_volatil"]
H = 5
U = np.linspace(0.01, 0.99, 99)       # grille de quantiles
TRAIN = 1000                          # fenetre d'estimation max (observations)
MIN_TRAIN = 250
LAMBDA = 0.94                         # EWMA RiskMetrics


def features(close):
    """Regime courant, rendement futur a 5j, regime de la fenetre future, vol EWMA."""
    lr = np.log(close).diff()
    vol5 = lr.rolling(H).std()
    ref = vol5.rolling(60, min_periods=40).median()
    past = np.log(close / close.shift(H))
    reg = pd.Series(np.where(past >= 0, 0, 2) + np.where(vol5 > ref, 1, 0), index=close.index, dtype=float)
    reg[past.isna() | vol5.isna() | ref.isna()] = np.nan
    sig = np.sqrt((lr ** 2).ewm(alpha=1 - LAMBDA, min_periods=20).mean())
    return pd.DataFrame({
        "reg": reg,
        "fwd": np.log(close.shift(-H) / close),
        "next": reg.shift(-H),
        "sig": sig * np.sqrt(H),
    }).dropna(subset=["reg", "sig"])


def forecasts(tr, reg, sig):
    """Quantiles des 5 modeles a partir de l'historique connu `tr`."""
    fwd, nxt, cur = tr["fwd"].to_numpy(), tr["next"].to_numpy(), tr["reg"].to_numpy()
    z = fwd / tr["sig"].to_numpy()
    out = {"Inconditionnel": np.quantile(fwd, U),
           "Vol EWMA": sig * np.quantile(z, U)}

    same = cur == reg
    out["Regime (melange)"] = np.quantile(fwd[same], U) if same.sum() >= 30 else out["Inconditionnel"]

    # probabilites de transition regime actuel -> regime suivant (lissage +1)
    counts = np.array([(nxt[same] == k).sum() for k in range(4)], float) + 1
    p = counts / counts.sum()
    for name, x, scale in [("Transport", fwd, 1.0), ("Transport + vol", z, sig)]:
        q = np.zeros_like(U)
        for k in range(4):
            xk = x[nxt == k]
            q += p[k] * (np.quantile(xk, U) if len(xk) >= 10 else np.quantile(x, U))
        out[name] = scale * q
    return out, p


def crps(q, y):
    """CRPS approche par la perte pinball moyenne sur la grille de quantiles."""
    return 2 * np.mean(np.maximum(U * (y - q), (U - 1) * (y - q)))


def p_up(q):
    return 1 - np.interp(0.0, q, U, left=0.0, right=1.0)


def run_asset(ticker, close, n_test):
    f = features(close)
    rows = []
    idx = f.index
    test_pos = [i for i in range(len(f)) if not np.isnan(f["fwd"].iat[i])][-n_test:]
    for i in test_pos:
        # historique connu en D : fenetres futures closes au plus tard en D
        lo = max(0, i - H - TRAIN)
        tr = f.iloc[lo:i - H + 1].dropna(subset=["fwd", "next"])
        if len(tr) < MIN_TRAIN:
            continue
        reg, sig, y = f["reg"].iat[i], f["sig"].iat[i], f["fwd"].iat[i]
        fc, p = forecasts(tr, reg, sig)
        for name, q in fc.items():
            q = np.maximum.accumulate(q)
            rows.append({"ticker": ticker, "date": idx[i], "modele": name, "realise": y,
                         "regime": REGIMES[int(reg)], "crps": crps(q, y),
                         "in50": q[24] <= y <= q[74], "in80": q[9] <= y <= q[89],
                         "brier_sens": (p_up(q) - (y > 0)) ** 2,
                         "q10": q[9], "q50": q[49], "q90": q[89]})
    return pd.DataFrame(rows)


def block_bootstrap(d, block=20, n=2000, seed=0):
    """IC 90 % de la moyenne d'une serie autocorrelee (blocs mobiles)."""
    rng = np.random.default_rng(seed)
    d = np.asarray(d)
    nb = int(np.ceil(len(d) / block))
    starts = rng.integers(0, len(d) - block + 1, size=(n, nb))
    means = np.array([np.concatenate([d[s:s + block] for s in row])[:len(d)].mean() for row in starts])
    return np.percentile(means, [5, 95])


def report(res):
    lines = []
    ref = "Vol EWMA"
    agg = res.groupby("modele").agg(crps=("crps", "mean"), cov50=("in50", "mean"),
                                    cov80=("in80", "mean"), brier_sens=("brier_sens", "mean"))
    agg["gain_vs_vol_ewma"] = 1 - agg["crps"] / agg.at[ref, "crps"]
    agg = agg.sort_values("crps")
    n = res[res.modele == ref].shape[0]
    lines.append(f"=== {n} previsions a {H} seances, {res.ticker.nunique()} actifs ===")
    lines.append("CRPS et Brier : plus bas = mieux. Couverture ideale : 50 % et 80 %.")
    lines.append("gain_vs_vol_ewma > 0 = meilleur que la reference Vol EWMA.\n")
    lines.append(agg.to_string(float_format=lambda v: f"{v:.4f}"))

    piv = res.pivot_table(index=["ticker", "date"], columns="modele", values="crps")
    lines.append(f"\nEcart de CRPS vs {ref} (negatif = mieux), IC 90 % par bootstrap en blocs :")
    for m in agg.index:
        if m == ref:
            continue
        d = (piv[m] - piv[ref]).dropna()
        lo, hi = block_bootstrap(d.to_numpy())
        verdict = "mieux" if hi < 0 else ("moins bien" if lo > 0 else "pas de difference nette")
        lines.append(f"  {m:18s} {d.mean():+.5f}  [{lo:+.5f} ; {hi:+.5f}]  -> {verdict}")

    lines.append("\nGain de CRPS vs Vol EWMA par actif :")
    by = res.groupby(["ticker", "modele"])["crps"].mean().unstack()
    lines.append((1 - by.div(by[ref], axis=0)).drop(columns=ref).to_string(float_format=lambda v: f"{v:+.1%}"))

    lines.append("\nCRPS par regime du jour :")
    lines.append(res.pivot_table(index="regime", columns="modele", values="crps").to_string(
        float_format=lambda v: f"{v:.4f}"))
    return "\n".join(lines)


def load(ticker):
    import yfinance as yf
    c = yf.download(ticker, period="10y", auto_adjust=True, progress=False)["Close"].squeeze()
    c.index = pd.to_datetime(c.index).tz_localize(None)
    return c.dropna()


def main():
    tickers = sys.argv[1].split(",") if len(sys.argv) > 1 else ["BTC-USD", "AMZN", "NVDA", "TSLA", "SPY", "GLD", "TLT"]
    n_test = int(sys.argv[2]) if len(sys.argv) > 2 else 750
    res = []
    for t in tickers:
        r = run_asset(t, load(t), n_test)
        print(f"{t} : {r.date.nunique()} dates testees", flush=True)
        res.append(r)
    res = pd.concat(res, ignore_index=True)
    os.makedirs("output", exist_ok=True)
    res.to_csv("output/regime_transport.csv", index=False)
    txt = report(res)
    print("\n" + txt)
    open("output/regime_transport.txt", "w").write(txt)


if __name__ == "__main__":
    main()
