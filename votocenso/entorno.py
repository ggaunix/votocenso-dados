"""Perfil censitário do entorno de cada local de votação, em três níveis.

  setor  : o setor censitário onde fica o local (grão mais fino, ~200-400 domicílios)
  raio   : soma dos setores cujo centroide está a até R metros do local
  bairro : bairro do IBGE onde fica o local (ou distrito, se o município não tem bairros)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.spatial import cKDTree

from . import censo

R_TERRA = 6_371_008.8


def _unitario(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def perfil_locais(locais: pd.DataFrame, setores: pd.DataFrame, centroides: pd.DataFrame,
                  setor_contem: pd.Series | None, raio_m: float,
                  niveis=("setor", "raio", "bairro")) -> pd.DataFrame:
    st = setores.merge(centroides, on="CD_SETOR", how="inner").reset_index(drop=True)
    arvore = cKDTree(_unitario(st["lat"].values, st["lon"].values))
    pos_setor = pd.Series(st.index, index=st["CD_SETOR"])

    tem = locais[["lat", "lon"]].notna().all(axis=1).values
    idx = np.flatnonzero(tem)
    pts = _unitario(locais["lat"].values[idx], locais["lon"].values[idx])

    # setor do local: contenção exata se disponível, senão centroide mais próximo
    _, mais_proximo = arvore.query(pts, k=1)
    setor_pos = mais_proximo.copy()
    if setor_contem is not None:
        exato = setor_contem.iloc[idx].map(pos_setor).values
        ok = ~pd.isna(exato)
        setor_pos[ok] = exato[ok].astype(int)

    out = pd.DataFrame(index=locais.index)
    out["cd_setor"] = pd.Series(st["CD_SETOR"].values[setor_pos], index=locais.index[idx])
    out["bairro_ibge"] = pd.Series(st["nome_bairro"].values[setor_pos], index=locais.index[idx])

    somaveis = censo.colunas_somaveis(st)
    M = st[somaveis].fillna(0).to_numpy()
    presente = st[somaveis].notna().to_numpy().astype(float)

    def anexar(prefixo, soma_df):
        ind = censo.indicadores(soma_df)
        ind.index = locais.index[idx]
        for c in ind.columns:
            out[f"{prefixo}_{c}"] = ind[c]

    if "setor" in niveis:
        anexar("setor", st[somaveis].iloc[setor_pos].reset_index(drop=True))
        for c in [c for c in st.columns if c.startswith("renda_mediana")]:
            out[f"setor_{c}"] = pd.Series(st[c].values[setor_pos], index=locais.index[idx])

    if "raio" in niveis:
        corda = 2 * np.sin(raio_m / (2 * R_TERRA))
        vizinhos = arvore.query_ball_point(pts, r=corda)
        linhas, colunas = [], []
        for i, viz in enumerate(vizinhos):
            viz = viz or [setor_pos[i]]  # área rural: nenhum centroide no raio -> o próprio setor
            linhas.extend([i] * len(viz))
            colunas.extend(viz)
        W = sparse.csr_matrix((np.ones(len(linhas)), (linhas, colunas)), shape=(len(idx), len(st)))
        soma = W @ M
        # coluna que só tinha NaN no raio deve continuar NaN (não zero)
        soma[(W @ presente) == 0] = np.nan
        anexar("raio", pd.DataFrame(soma, columns=somaveis))
        out["raio_n_setores"] = pd.Series(np.diff(W.indptr), index=locais.index[idx])

    if "bairro" in niveis:
        por_bairro = censo.somar_por(st, "unidade_bairro")
        chaves = st["unidade_bairro"].values[setor_pos]
        anexar("bairro", por_bairro.loc[chaves].reset_index(drop=True))

    return out
