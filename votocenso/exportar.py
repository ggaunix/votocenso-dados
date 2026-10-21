"""Gera os arquivos de dados do portal para uma UF e um ano.

Saída em portal_dados/<ano>_<UF>/:
  meta.json            candidatos de todos os cargos, indicadores, fontes, avisos
  locais.json.gz       locais de votação com coordenadas, válidos por cargo e censo do entorno
  limites.json.gz      contornos simplificados de municípios e distritos (para o mapa)
  cand/<cargo>_<nr>.json.gz  votos do candidato por local e por seção

Uso: python -m votocenso.exportar --ano 2022 --uf SP
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import censo, config, entorno, tse

NOMES_CARGO = {5: "Senador", 6: "Deputado federal", 7: "Deputado estadual", 8: "Deputado distrital"}
NAO_ELEITOS = {5: 5, 6: 30, 7: 30, 8: 15}  # mais votados não eleitos que também ganham detalhe

INDICADORES = [  # chave, rótulo, unidade, casas decimais
    ("renda_media_responsavel", "Renda média do responsável", "R$", 0),
    ("pct_alfabetizados_15_mais", "Alfabetizados, 15 anos ou mais", "%", 1),
    ("pct_branca", "Brancos", "%", 1),
    ("pct_preta", "Pretos", "%", 1),
    ("pct_parda", "Pardos", "%", 1),
    ("pct_preta_parda", "Pretos e pardos", "%", 1),
    ("pct_amarela", "Amarelos", "%", 1),
    ("pct_indigena", "Indígenas", "%", 1),
    ("pct_0_14", "0 a 14 anos", "%", 1),
    ("pct_15_24", "15 a 24 anos", "%", 1),
    ("pct_25_39", "25 a 39 anos", "%", 1),
    ("pct_40_59", "40 a 59 anos", "%", 1),
    ("pct_60_mais", "60 anos ou mais", "%", 1),
    ("pct_pop_favela", "Em favela ou comunidade urbana", "%", 1),
    ("pct_pop_rural", "Em setor rural", "%", 1),
    ("densidade_hab_km2", "Densidade", "hab/km²", 0),
    ("pop", "População", "pessoas", 0),
    ("domicilios", "Domicílios", "domicílios", 0),
]
NIVEIS = ("raio", "bairro", "setor")


def log(m):
    print(m, file=sys.stderr, flush=True)


def lista(valores, casas=None):
    out = []
    for x in valores:
        if x is None or (isinstance(x, float) and math.isnan(x)) or x is pd.NA:
            out.append(None)
        elif casas is None:
            out.append(x.item() if hasattr(x, "item") else x)
        elif casas == 0:
            out.append(int(round(float(x))))
        else:
            out.append(round(float(x), casas))
    return out


def textos(serie):
    return [None if pd.isna(x) else str(x) for x in serie]


def gravar(caminho: Path, obj, comprimir=True):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    dados = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if comprimir:
        caminho.write_bytes(gzip.compress(dados, 9, mtime=0))
    else:
        caminho.write_bytes(dados)
    return len(dados)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--ano", type=int, required=True)
    p.add_argument("--uf", required=True, type=str.upper)
    p.add_argument("--raio", type=float, default=config.RAIO_PADRAO_M)
    p.add_argument("--saida", type=Path, default=None)
    a = p.parse_args(argv)
    destino = a.saida or (config.RAIZ / "portal_dados" / f"{a.ano}_{a.uf}")
    cargos = [5, 6, 8] if a.uf == "DF" else [5, 6, 7]

    log("candidatos (consulta_cand)...")
    cands = tse.carregar_candidatos(a.ano, a.uf)

    def escolher(totais):
        t = totais[totais["NR_VOTAVEL"] >= 100].merge(
            cands, left_on=["CD_CARGO", "NR_VOTAVEL"], right_on=["CD_CARGO", "NR_CANDIDATO"], how="left")
        sit = t["DS_SIT_TOT_TURNO"].fillna("").str.upper()
        eleito = sit.str.startswith("ELEITO")
        sel = set(zip(t.loc[eleito, "CD_CARGO"], t.loc[eleito, "NR_VOTAVEL"]))
        for cargo in cargos:
            resto = t[(t["CD_CARGO"] == cargo) & ~eleito].nlargest(
                NAO_ELEITOS[cargo] * (1 if eleito.any() else 4), "votos")
            sel |= set(zip(resto["CD_CARGO"], resto["NR_VOTAVEL"]))
        return {(int(c), int(n)) for c, n in sel}

    log("votos por seção (passadas 1 e 2)...")
    votos, validos, totais = tse.votos_varios_cargos(a.ano, a.uf, cargos, escolher)
    escolhidos = set(zip(votos["CD_CARGO"], votos["NR_VOTAVEL"]))

    log("locais de votação...")
    secoes, locais = tse.carregar_locais(a.ano, a.uf)
    locais = locais.reset_index(drop=True)

    log("censo por setor...")
    setores = censo.carregar_setores(a.uf)
    from . import geo
    try:
        centroides = geo.centroides_setores(a.uf)
        contem = geo.setor_que_contem(a.uf, locais)
    except ImportError:
        centroides, contem = pd.read_csv(config.CACHE / f"centroides_{a.uf}.csv", dtype={"CD_SETOR": str}), None
    perfil = entorno.perfil_locais(locais, setores, centroides, contem, a.raio, NIVEIS)

    # seção -> índice do local
    sec = secoes.merge(locais[tse.CHAVE_LOCAL].reset_index().rename(columns={"index": "li"}),
                       on=tse.CHAVE_LOCAL, how="left")[tse.CHAVE_SECAO + ["li"]]

    log("montando arquivos...")
    val_sec = validos.merge(sec, on=tse.CHAVE_SECAO, how="left")
    val_sec = val_sec.dropna(subset=["li"]).astype({"li": int})
    val_local = val_sec.groupby(["CD_CARGO", "li"])["validos"].sum()

    muns = sorted(locais["NM_MUNICIPIO"].dropna().unique().tolist())
    pos_mun = {m: i for i, m in enumerate(muns)}
    L = {
        "n": len(locais),
        "mun": [pos_mun.get(m) for m in locais["NM_MUNICIPIO"]],
        "zona": lista(locais["NR_ZONA"]),
        "nr": lista(locais["NR_LOCAL_VOTACAO"]),
        "nome": locais["NM_LOCAL_VOTACAO"].fillna("").tolist(),
        "end": locais["endereco"].fillna("").tolist(),
        "bairro": locais["bairro_tse"].fillna("").tolist(),
        "bairro_ibge": textos(perfil["bairro_ibge"]),
        "setor": textos(perfil["cd_setor"]),
        "lat": lista(locais["lat"], 5), "lon": lista(locais["lon"], 5),
        "eleit": lista(locais["eleitores"], 0),
        "val": {str(c): lista((val_local.xs(c) if c in val_local.index.get_level_values(0) else pd.Series(dtype=float))
                              .reindex(locais.index).fillna(0), 0) for c in cargos},
        "ind": {},
    }
    for nivel in NIVEIS:
        L["ind"][nivel] = {k: lista(perfil[f"{nivel}_{k}"], casas)
                           for k, _, _, casas in INDICADORES if f"{nivel}_{k}" in perfil}
    if "setor_renda_mediana_responsavel" in perfil:
        L["ind"]["setor"]["renda_mediana_responsavel"] = lista(perfil["setor_renda_mediana_responsavel"], 0)
    tam = gravar(destino / "locais.json.gz", L)
    log(f"   locais.json: {len(locais)} locais, {tam / 1e6:.1f} MB antes de comprimir")

    # candidatos
    v = votos.merge(sec, on=tse.CHAVE_SECAO, how="left")
    sem_local = int(v.loc[v["li"].isna(), "QT_VOTOS"].sum())
    v = v.dropna(subset=["li"])
    v["li"] = v["li"].astype(int)
    v = v.merge(validos, on=["CD_CARGO"] + tse.CHAVE_SECAO, how="left")
    for (cargo, nr), g in v.groupby(["CD_CARGO", "NR_VOTAVEL"]):
        por_local = g.groupby("li")["QT_VOTOS"].sum()
        g = g.sort_values(["li", "NR_SECAO"])
        gravar(destino / "cand" / f"{cargo}_{nr}.json.gz", {
            "id": f"{cargo}_{nr}",
            "li": por_local.index.tolist(), "v": lista(por_local.values),
            "s_li": g["li"].tolist(), "s_sec": lista(g["NR_SECAO"]),
            "s_v": lista(g["QT_VOTOS"]), "s_val": lista(g["validos"]),
        })

    t = totais[totais["NR_VOTAVEL"] >= 100].merge(
        cands, left_on=["CD_CARGO", "NR_VOTAVEL"], right_on=["CD_CARGO", "NR_CANDIDATO"], how="left")
    t = t.sort_values(["CD_CARGO", "votos"], ascending=[True, False])
    lista_cand = [{
        "id": f"{c}_{n}", "cargo": int(c), "nr": int(n),
        "nome": (u if isinstance(u, str) and u else nm),
        "partido": pt if isinstance(pt, str) else "",
        "situacao": s if isinstance(s, str) and s != "#NULO#" else "",
        "votos": int(vt), "detalhe": (int(c), int(n)) in escolhidos,
    } for c, n, vt, nm, u, pt, s in zip(t["CD_CARGO"], t["NR_VOTAVEL"], t["votos"], t["NM_VOTAVEL"],
                                         t.get("NM_URNA_CANDIDATO", [None] * len(t)),
                                         t.get("SG_PARTIDO", [None] * len(t)),
                                         t.get("DS_SIT_TOT_TURNO", [None] * len(t)))]

    tem_limites = False
    try:
        lim = geo.limites(a.uf, setores)
        gravar(destino / "limites.json.gz", lim)
        tem_limites = True
    except ImportError:
        log("   geopandas ausente: limites.json não gerado")

    meta = {
        "ano": a.ano, "uf": a.uf, "turno": 1, "raio_m": a.raio,
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "municipios": muns,
        "cargos": {str(c): {"nome": NOMES_CARGO[c],
                            "validos_uf": int(validos.loc[validos["CD_CARGO"] == c, "validos"].sum())}
                   for c in cargos},
        "candidatos": lista_cand,
        "indicadores": [{"chave": k, "rotulo": r, "unidade": u, "casas": c} for k, r, u, c in INDICADORES],
        "niveis": {"raio": f"Entorno de {a.raio:.0f} m", "bairro": "Bairro do IBGE (ou distrito)", "setor": "Setor censitário"},
        "limites": tem_limites,
        "avisos": {
            "locais_sem_coordenada": int(locais["lat"].isna().sum()),
            "locais_total": len(locais),
            "votos_sem_local": sem_local,
        },
        "fontes": [
            f"TSE, votação por seção {a.ano} ({config.URL_TSE}/votacao_secao/votacao_secao_{a.ano}_{a.uf}.zip)",
            f"TSE, eleitorado por local de votação {a.ano}",
            f"TSE, candidatos {a.ano} (consulta_cand)",
            "IBGE, Censo 2022, agregados por setores censitários e malha de setores",
            "IBGE, Censo 2022, rendimento do responsável por setor",
        ],
    }
    gravar(destino / "meta.json", meta, comprimir=False)
    log(f"pronto: {destino} ({len(escolhidos)} candidatos detalhados)")
    return destino


if __name__ == "__main__":
    main()
