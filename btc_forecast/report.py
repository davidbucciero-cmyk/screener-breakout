import html
import json

# 3 premiers slots de la palette categorielle de reference (valides en all-pairs, clair et sombre).
SERIES = [('--s1', '#2a78d6', '#3987e5'), ('--s2', '#eb6834', '#d95926'), ('--s3', '#1baf7a', '#199e70')]

PCT_COLS = {'taux_reussite', 'rendement_brut', 'rendement_net', 'max_drawdown_net',
            'freq_hausse_reelle', 'p_up_moyenne', 'freq_hausse'}


def _fmt(col, v):
    if isinstance(v, float):
        if col in PCT_COLS:
            return f'{v:.2%}'
        return f'{v:.4f}'
    return html.escape(str(v))


def _table(df, index=False):
    if index:
        df = df.reset_index()
    head = ''.join(f'<th>{html.escape(str(c))}</th>' for c in df.columns)
    body = ''.join('<tr>' + ''.join(f'<td>{_fmt(c, r[c])}</td>' for c in df.columns) + '</tr>'
                   for _, r in df.iterrows())
    return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def build_html(calib, perf, reliability, curves, meta, fee_bps):
    chosen = [perf['strategie'].iloc[0], 'Buy & hold', 'Momentum (meme sens que la bougie precedente)']
    equity = (1 + curves[chosen]).cumprod()
    step = max(1, len(equity) // 600)
    equity = equity.iloc[::step]
    data = {
        't': [ts.strftime('%Y-%m-%d %H:%M') for ts in equity.index],
        'series': [{'name': n, 'var': SERIES[i][0], 'y': [round(v, 5) for v in equity[n]]}
                   for i, n in enumerate(chosen)],
    }
    css_light = ''.join(f'{v}:{l};' for v, l, _ in SERIES)
    css_dark = ''.join(f'{v}:{d};' for v, _, d in SERIES)
    legend = ''.join(f'<span class="lg"><i style="background:var({s["var"]})"></i>{html.escape(s["name"])}</span>'
                     for s in data['series'])
    calib_rows = ''.join(f'<tr><td>{k}</td><td>{_fmt(k, v)}</td></tr>' for k, v in calib.items())

    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>BTC 1h Chronos</title>
<style>
:root{{color-scheme:light;--bg:#fcfcfb;--fg:#0b0b0b;--fg2:#52514e;--grid:#e6e5e0;{css_light}}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{color-scheme:dark;--bg:#1a1a19;--fg:#fff;--fg2:#c3c2b7;--grid:#383835;{css_dark}}}}}
:root[data-theme="dark"]{{color-scheme:dark;--bg:#1a1a19;--fg:#fff;--fg2:#c3c2b7;--grid:#383835;{css_dark}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}}
h1{{font-size:20px}} h2{{font-size:16px;margin-top:28px}} .muted{{color:var(--fg2)}}
.tw{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:4px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}}
.lg{{margin-right:16px;color:var(--fg2)}} .lg i{{display:inline-block;width:12px;height:2px;vertical-align:middle;margin-right:6px}}
#chart{{position:relative}} svg{{width:100%;height:320px;display:block}}
#tip{{position:absolute;pointer-events:none;background:var(--bg);border:1px solid var(--grid);padding:6px 8px;font-size:12px;display:none;white-space:nowrap}}
</style></head><body>
<h1>BTC/USDT 1h &mdash; direction de la prochaine bougie (Chronos, zero-shot)</h1>
<p class="muted">Modele {html.escape(meta["model"])} &middot; {calib["n_previsions"]} previsions walk-forward
du {html.escape(meta["start"])} au {html.escape(meta["end"])} &middot; contexte {meta["context_len"]}h
&middot; frais {fee_bps} bps par cote. Chaque prevision n'utilise que les bougies deja cloturees.</p>

<h2>Calibration des probabilites</h2>
<p class="muted">Un Brier inferieur a la frequence constante indique une information reelle sur la direction.</p>
<div class="tw"><table><tbody>{calib_rows}</tbody></table></div>

<h2>Strategies vs baselines</h2>
<p class="muted">p-value : probabilite d'obtenir ce taux de reussite par hasard (pile ou face). Au-dessus de 0.05, rien de significatif.</p>
{_table(perf)}

<h2>Courbe de capital (net de frais)</h2>
<div>{legend}</div>
<div id="chart"><svg id="svg" role="img" aria-label="Courbe de capital des strategies"></svg><div id="tip"></div></div>

<h2>Fiabilite par tranche de P(hausse)</h2>
{_table(reliability, index=True)}

<script>
const D={json.dumps(data)};
const svg=document.getElementById('svg'),tip=document.getElementById('tip');
function draw(){{
  const W=svg.clientWidth,H=320,m={{l:48,r:12,t:10,b:24}},n=D.t.length;
  const all=D.series.flatMap(s=>s.y),lo=Math.min(...all),hi=Math.max(...all);
  const x=i=>m.l+i/(n-1)*(W-m.l-m.r),y=v=>m.t+(hi-v)/(hi-lo||1)*(H-m.t-m.b);
  let g='';
  for(let k=0;k<=4;k++){{const v=lo+(hi-lo)*k/4;g+=`<line x1="${{m.l}}" x2="${{W-m.r}}" y1="${{y(v)}}" y2="${{y(v)}}" stroke="var(--grid)"/><text x="${{m.l-6}}" y="${{y(v)+4}}" text-anchor="end" font-size="11" fill="var(--fg2)">${{v.toFixed(2)}}</text>`;}}
  [0,Math.floor(n/2),n-1].forEach((i,k)=>g+=`<text x="${{x(i)}}" y="${{H-6}}" font-size="11" fill="var(--fg2)" text-anchor="${{['start','middle','end'][k]}}">${{D.t[i].slice(0,10)}}</text>`);
  D.series.forEach(s=>g+=`<polyline fill="none" stroke="var(${{s.var}})" stroke-width="2" points="${{s.y.map((v,i)=>x(i)+','+y(v)).join(' ')}}"/>`);
  g+=`<line id="xh" y1="${{m.t}}" y2="${{H-m.b}}" stroke="var(--fg2)" visibility="hidden"/>`;
  svg.innerHTML=g;
  svg.onmousemove=e=>{{const r=svg.getBoundingClientRect(),i=Math.max(0,Math.min(n-1,Math.round((e.clientX-r.left-m.l)/(W-m.l-m.r)*(n-1))));
    const xh=document.getElementById('xh');xh.setAttribute('x1',x(i));xh.setAttribute('x2',x(i));xh.setAttribute('visibility','visible');
    tip.innerHTML=`<b>${{D.t[i]}}</b><br>`+D.series.map(s=>`<i style="display:inline-block;width:10px;height:2px;background:var(${{s.var}});vertical-align:middle"></i> ${{s.name}} : ${{((s.y[i]-1)*100).toFixed(2)}} %`).join('<br>');
    tip.style.display='block';tip.style.left=Math.min(x(i)+12,W-tip.offsetWidth)+'px';tip.style.top='10px';}};
  svg.onmouseleave=()=>{{tip.style.display='none';const xh=document.getElementById('xh');if(xh)xh.setAttribute('visibility','hidden');}};
}}
draw();addEventListener('resize',draw);
</script></body></html>'''
