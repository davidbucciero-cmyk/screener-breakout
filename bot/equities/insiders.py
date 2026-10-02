"""Achats d'initiés en bourse (code de transaction P) depuis les jeux de donnees SEC Form 3/4/5.

Chaque achat est date a la PUBLICATION du formulaire (FILING_DATE), pas a la transaction : c'est le
premier moment ou le marche, et donc nous, pouvons le connaitre.
"""
import io
import logging
import zipfile

import pandas as pd

from bot.equities.sec import get

log = logging.getLogger(__name__)
URL = 'https://www.sec.gov/files/structureddata/data/form-345-data-sets/{y}q{q}_form345.zip'


def _tsv(z, name):
    match = [n for n in z.namelist() if n.upper().endswith(name)]
    if not match:
        raise KeyError(f'{name} absent de l\'archive ({z.namelist()})')
    return pd.read_csv(z.open(match[0]), sep='\t', dtype=str, low_memory=False)


def parse_quarter(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    sub = _tsv(z, 'SUBMISSION.TSV')[['ACCESSION_NUMBER', 'FILING_DATE', 'ISSUERCIK', 'ISSUERTRADINGSYMBOL']]
    tr = _tsv(z, 'NONDERIV_TRANS.TSV')
    tr = tr[tr['TRANS_CODE'] == 'P'][['ACCESSION_NUMBER', 'TRANS_SHARES', 'TRANS_PRICEPERSHARE']]
    own = _tsv(z, 'REPORTINGOWNER.TSV')[['ACCESSION_NUMBER', 'RPTOWNERCIK']].drop_duplicates('ACCESSION_NUMBER')
    df = tr.merge(sub, on='ACCESSION_NUMBER').merge(own, on='ACCESSION_NUMBER', how='left')
    df['value'] = pd.to_numeric(df['TRANS_SHARES'], errors='coerce') * pd.to_numeric(df['TRANS_PRICEPERSHARE'], errors='coerce')
    df['filing_date'] = pd.to_datetime(df['FILING_DATE'], format='mixed', dayfirst=True, errors='coerce')
    out = pd.DataFrame({'filing_date': df['filing_date'], 'cik': pd.to_numeric(df['ISSUERCIK'], errors='coerce'),
                        'ticker': df['ISSUERTRADINGSYMBOL'].str.upper().str.strip(),
                        'owner': df['RPTOWNERCIK'], 'value': df['value']})
    return out.dropna(subset=['filing_date', 'cik', 'value'])


def purchases(first_year=2009, last_year=None):
    last_year = last_year or pd.Timestamp.now().year
    parts = []
    for y in range(first_year, last_year + 1):
        for q in range(1, 5):
            r = get(URL.format(y=y, q=q))
            if r is None:
                log.info(f'Form 345 {y}T{q} pas encore publie')
                continue
            df = parse_quarter(r.content)
            log.info(f'Form 345 {y}T{q} : {len(df)} achats')
            parts.append(df)
    return pd.concat(parts, ignore_index=True)
