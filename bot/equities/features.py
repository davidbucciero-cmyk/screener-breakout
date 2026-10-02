"""Panel mensuel : une ligne par (fin de mois, action de l'univers > 2 Md$), chaque feature datee a sa
disponibilite reelle, et la cible = rendement du mois suivant.
"""
import math

import numpy as np
import pandas as pd

MIN_CAP = 2e9
SHARES_LAG = pd.Timedelta(days=15)   # page de garde -> publication
STALE = pd.Timedelta(days=450)       # comptes plus vieux que ~15 mois ignores
INSIDER_WINDOW = pd.Timedelta(days=90)
FEATURES = ['A1_initie_acheteurs_90j', 'A1_initie_montant_pct_cap', 'A2_croissance_ca_1an', 'A6_sma50_sup_sma200',
            'B1_momentum_12_1', 'B2_proximite_plus_haut_52s', 'B3_volatilite_12m', 'B4_rendement_1m',
            'C1_marge_brute_sur_actifs', 'C2_variation_actions_1an', 'C6_accruals']


def month_ends(idx):
    s = pd.Series(idx, index=idx)
    return pd.DatetimeIndex(s.groupby([idx.year, idx.month]).max().to_numpy())


def asof_wide(df, key, value, avail, dates, stale=None):
    """Valeur connue a chaque date (derniere disponible), en largeur (dates x key)."""
    d = df[[key, value, avail]].dropna().copy()
    d[avail] = pd.to_datetime(d[avail]).astype('datetime64[ns]')
    d = d.sort_values(avail)
    wide = d.pivot_table(index=avail, columns=key, values=value, aggfunc='last')
    idx = wide.index.union(dates)
    out = wide.reindex(idx).ffill().reindex(dates)
    if stale is not None:
        # Age calcule en nanosecondes : robuste aux colonnes avec des trous.
        d['_t'] = d[avail].astype('int64').astype('float64')
        seen = d.pivot_table(index=avail, columns=key, values='_t', aggfunc='last').reindex(idx).ffill().reindex(dates)
        now = pd.Series(pd.DatetimeIndex(dates).astype('datetime64[ns]').astype('int64').astype('float64'), index=dates)
        age = -seen.sub(now, axis=0)
        out = out.where(age <= float(stale.value))
    return out


def to_price_basis(shares, splits, cik_to_ticker):
    """Ramene le nombre d'actions declare a la SEC sur la base des prix Yahoo (ajustes des splits futurs).

    Un split de ratio r (2.0 pour 2 pour 1, 0.1 pour un regroupement 1 pour 10) posterieur a la date du
    nombre d'actions multiplie ce nombre par r ; le prix Yahoo de l'epoque est, lui, divise par r.
    """
    out = shares.copy()
    if splits is None or len(splits) == 0:
        return out
    tick = out['cik'].map(cik_to_ticker)
    factor = np.ones(len(out))
    for t, g in splits[splits['ticker'].isin(set(tick.dropna()))].groupby('ticker'):
        m = (tick == t).to_numpy()
        ends = out.loc[m, 'end'].to_numpy(dtype='datetime64[ns]')
        f = np.ones(m.sum())
        for d, r in zip(pd.to_datetime(g['date']).to_numpy(dtype='datetime64[ns]'), g['ratio'].to_numpy(float)):
            f *= np.where(ends < d, r, 1.0)
        factor[m] = f
    out['val'] = out['val'] * factor
    return out


def build_panel(close, tickers, shares, fund, purch, splits=None):
    t2c = tickers.drop_duplicates('cik').set_index('ticker')['cik']  # une classe d'action par entreprise
    cols = [t for t in close.columns if t in t2c.index]
    close = close[cols]
    cik_of = t2c.reindex(cols)
    dates = month_ends(close.index)
    dates = dates[dates >= close.index[0] + pd.Timedelta(days=380)]

    ret = close.pct_change(fill_method=None)
    daily = {
        'B1_momentum_12_1': close.shift(21) / close.shift(252) - 1,
        'B2_proximite_plus_haut_52s': close / close.rolling(252, min_periods=200).max(),
        'B3_volatilite_12m': ret.rolling(252, min_periods=200).std() * math.sqrt(252),
        'B4_rendement_1m': close / close.shift(21) - 1,
        'A6_sma50_sup_sma200': (close.rolling(50).mean() > close.rolling(200).mean()).astype(float)
        .where(close.rolling(200).count() >= 200),
    }
    m_close = close.loc[dates]
    fwd = m_close.shift(-1) / m_close - 1

    def by_ticker(wide_cik):
        return pd.DataFrame(wide_cik.reindex(columns=cik_of.to_numpy()).to_numpy(), index=dates, columns=cols)

    sh = to_price_basis(shares, splits, pd.Series(cols, index=cik_of.to_numpy()))
    sh = sh.assign(avail=sh['end'] + SHARES_LAG)
    sh_now = by_ticker(asof_wide(sh, 'cik', 'val', 'avail', dates, stale=STALE))
    sh_1y = by_ticker(asof_wide(sh, 'cik', 'val', 'avail', dates - pd.Timedelta(days=365), stale=STALE)
                      .set_axis(dates))
    mcap = sh_now * m_close

    f = fund.sort_values(['cik', 'year']).copy()
    prev = f.groupby('cik')[['revenue', 'year']].shift(1)
    f['A2_croissance_ca_1an'] = (f['revenue'] / prev['revenue'] - 1).where(prev['year'] == f['year'] - 1)
    f['C1_marge_brute_sur_actifs'] = f['gross_profit'] / f['assets']
    f['C6_accruals'] = (f['net_income'] - f['cfo']) / f['assets']
    fund_feats = {k: by_ticker(asof_wide(f, 'cik', k, 'available', dates, stale=STALE))
                  for k in ('A2_croissance_ca_1an', 'C1_marge_brute_sur_actifs', 'C6_accruals')}

    ins_n = pd.DataFrame(0.0, index=dates, columns=cols)
    ins_v = pd.DataFrame(0.0, index=dates, columns=cols)
    p = purch[['filing_date', 'cik', 'owner', 'value']].copy()
    p['filing_date'] = pd.to_datetime(p['filing_date']).dt.normalize()
    c2t = pd.Series(cols, index=cik_of.to_numpy())
    for d in dates:
        w = p[(p['filing_date'] <= d) & (p['filing_date'] > d - INSIDER_WINDOW) & p['cik'].isin(c2t.index)]
        if w.empty:
            continue
        g = w.groupby('cik').agg(n=('owner', 'nunique'), v=('value', 'sum'))
        tick = c2t.reindex(g.index)
        ins_n.loc[d, tick.to_numpy()] = g['n'].to_numpy()
        ins_v.loc[d, tick.to_numpy()] = g['v'].to_numpy()

    wide = {k: v.loc[dates] for k, v in daily.items()}
    wide.update(fund_feats)
    wide['A1_initie_acheteurs_90j'] = ins_n
    wide['A1_initie_montant_pct_cap'] = ins_v / mcap
    wide['C2_variation_actions_1an'] = sh_now / sh_1y - 1
    wide['mcap'] = mcap
    wide['fwd_ret'] = fwd

    panel = pd.concat({k: v.stack(future_stack=True) for k, v in wide.items()}, axis=1)
    panel.index.names = ['date', 'ticker']
    panel = panel[panel['mcap'] > MIN_CAP]
    return panel.reset_index()


def information_coefficients(panel, end_dev='2018-12-31', features=FEATURES, start=None):
    """IC de rang mensuel de chaque feature vs rendement du mois suivant, entre `start` et `end_dev`."""
    end_dev = pd.Timestamp(end_dev)
    p = panel.dropna(subset=['fwd_ret'])
    if start is not None:
        p = p[p['date'] >= pd.Timestamp(start)]
    # Le rendement cible du mois d doit se terminer avant la fin de la periode de dev.
    month_after = p['date'] + pd.offsets.MonthEnd(1)
    p = p[month_after <= end_dev]
    rows = []
    for feat in features:
        ics = p.groupby('date').apply(
            lambda g: g[feat].rank().corr(g['fwd_ret'].rank()) if g[feat].notna().sum() >= 30
            and g[feat].nunique() > 1 else np.nan, include_groups=False).dropna()
        if ics.empty:
            rows.append({'feature': feat, 'mois': 0})
            continue
        t = ics.mean() / ics.std() * math.sqrt(len(ics)) if ics.std() > 0 else np.nan
        by_year = ics.groupby(ics.index.year).mean()
        same = int((np.sign(by_year) == np.sign(ics.mean())).sum())
        rows.append({'feature': feat, 'mois': len(ics), 'ic_moyen': ics.mean(), 't_stat': t,
                     'mois_ic_positif': (ics > 0).mean(), 'annees_meme_signe': f'{same}/{len(by_year)}',
                     **{str(y): v for y, v in by_year.items()}})
    return pd.DataFrame(rows).sort_values('t_stat', key=lambda s: s.abs(), ascending=False)


def insider_cluster_spread(panel, end_dev='2018-12-31', min_insiders=2):
    """Rendement du mois suivant des actions avec >= 2 initiés acheteurs, moins la moyenne de l'univers."""
    end_dev = pd.Timestamp(end_dev)
    p = panel.dropna(subset=['fwd_ret'])
    p = p[p['date'] + pd.offsets.MonthEnd(1) <= end_dev]
    mean_all = p.groupby('date')['fwd_ret'].mean()
    flagged = p[p['A1_initie_acheteurs_90j'] >= min_insiders]
    spread = (flagged.groupby('date')['fwd_ret'].mean() - mean_all).dropna()
    n = flagged.groupby('date').size()
    t = spread.mean() / spread.std() * math.sqrt(len(spread)) if len(spread) > 2 else np.nan
    return {'mois': len(spread), 'actions_signalees_par_mois': float(n.mean()) if len(n) else 0.0,
            'surperformance_mensuelle': float(spread.mean()) if len(spread) else np.nan, 't_stat': float(t)}
