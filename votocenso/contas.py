"""Prestação de contas de campanha dos candidatos (TSE): despesas e receitas por candidato.

Fica em dados/contas/ (fora do cache do workflow), porque muda até a prestação final.
Arquivos esperados, por UF: despesas_contratadas_candidatos_<ano>_<UF>.csv e
receitas_candidatos_<ano>_<UF>.csv (CSV ';' em latin-1, valores com vírgula decimal).
"""
from __future__ import annotations

import sys

import pandas as pd

from . import config
from .tse import normalizar


def _arquivo(prefixo: str, ano: int, uf: str):
    achados = sorted((config.DADOS / "contas").glob(f"{prefixo}_{ano}_{uf}.csv"))
    return achados[0] if achados else None


def _ler(caminho, quer: list[str]) -> pd.DataFrame:
    cab = pd.read_csv(caminho, sep=";", encoding="latin-1", nrows=0).columns.tolist()
    valor = next((c for c in cab if c.startswith("VR_DESPESA") or c == "VR_RECEITA"), None)
    usar = [c for c in quer if c in cab] + ([valor] if valor else [])
    print(f"   {caminho.name}: valor em {valor}; colunas usadas {usar}", file=sys.stderr, flush=True)
    if valor is None or "NR_CANDIDATO" not in cab or "CD_CARGO" not in cab:
        raise ValueError(f"{caminho.name}: colunas inesperadas {cab[:40]}")
    df = pd.read_csv(caminho, sep=";", encoding="latin-1", dtype=str, usecols=usar, keep_default_na=False)
    bruto = df[valor].str.strip()
    # "1.234,56" ou "1234,56" (padrão TSE); se não houver vírgula, o ponto já é decimal
    com_virgula = bruto.str.contains(",", regex=False)
    txt = bruto.where(~com_virgula, bruto.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    df["valor"] = pd.to_numeric(txt, errors="coerce").fillna(0)
    for c in ("NR_CANDIDATO", "CD_CARGO"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df


def carregar(ano: int, uf: str):
    """Retorna (tabela por candidato, info) ou (None, motivo) se os arquivos não existem."""
    f_desp = _arquivo("despesas_contratadas_candidatos", ano, uf)
    f_rec = _arquivo("receitas_candidatos", ano, uf)
    if not f_desp and not f_rec:
        return None, "arquivos de prestação de contas não encontrados"
    partes, datas = [], []
    if f_desp:
        d = _ler(f_desp, ["CD_CARGO", "NR_CANDIDATO", "DT_GERACAO", "DT_DESPESA"])
        partes.append(d.groupby(["CD_CARGO", "NR_CANDIDATO"])["valor"].sum().rename("despesas"))
        datas += [x for x in d.get("DT_GERACAO", pd.Series(dtype=str)).unique()[:1]]
    if f_rec:
        r = _ler(f_rec, ["CD_CARGO", "NR_CANDIDATO", "DS_FONTE_RECEITA", "DT_GERACAO", "DT_RECEITA"])
        partes.append(r.groupby(["CD_CARGO", "NR_CANDIDATO"])["valor"].sum().rename("receitas"))
        if "DS_FONTE_RECEITA" in r:
            fonte = r["DS_FONTE_RECEITA"].map(normalizar)
            print(f"   fontes de receita: {fonte.value_counts().head(6).to_dict()}", file=sys.stderr, flush=True)
            publico = fonte.str.contains("FUNDO ESPECIAL|FUNDO PARTIDARIO|FEFC", regex=True)
            partes.append(r[publico].groupby(["CD_CARGO", "NR_CANDIDATO"])["valor"].sum().rename("publico"))
        datas += [x for x in r.get("DT_GERACAO", pd.Series(dtype=str)).unique()[:1]]
    tab = pd.concat(partes, axis=1).fillna(0).reset_index()
    info = {"referencia": next((d for d in datas if d), ""),
            "tem_despesas": f_desp is not None, "tem_receitas": f_rec is not None}
    return tab, info
