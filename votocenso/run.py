"""Votos por seção de candidatos + perfil do Censo 2022 no entorno de cada local de votação.

Exemplo:
  python -m votocenso.run --ano 2022 --uf SP --cargo "deputado federal" --candidatos "FULANO,1234"
  python -m votocenso.run --ano 2022 --uf SP --cargo senador --top 3 --raio 800
"""
from __future__ import annotations

import argparse
import re
import sys

import numpy as np
import pandas as pd

from . import censo, config, entorno, tse

INDICADORES_RESUMO = [
    "renda_media_responsavel", "pct_alfabetizados_15_mais", "pct_branca", "pct_preta_parda",
    "pct_0_14", "pct_15_24", "pct_25_39", "pct_40_59", "pct_60_mais",
    "pct_pop_favela", "pct_pop_rural", "densidade_hab_km2",
]


def slug(txt: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", tse.normalizar(txt).lower()).strip("_")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def obter_geo(uf: str, locais: pd.DataFrame):
    from . import geo

    cache = config.CACHE / f"centroides_{uf}.csv"
    try:
        centroides = geo.centroides_setores(uf)
        contem = geo.setor_que_contem(uf, locais)
        return centroides, contem
    except ImportError:
        if cache.exists():
            log("geopandas ausente: usando centroides em cache e setor mais próximo (sem contenção exata).")
            return pd.read_csv(cache, dtype={"CD_SETOR": str}), None
        raise SystemExit("Instale geopandas (pip install -r requirements.txt) para o primeiro processamento da UF.")


def media_ponderada(df: pd.DataFrame, col: str, peso: str) -> float:
    m = df[col].notna() & df[peso].gt(0)
    return float(np.average(df.loc[m, col], weights=df.loc[m, peso])) if m.any() else np.nan


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, required=True)
    p.add_argument("--uf", required=True, type=str.upper, choices=sorted(config.UF_IBGE))
    p.add_argument("--cargo", required=True, type=str.lower, choices=sorted(config.CARGOS))
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--candidatos", default="", help="números ou trechos de nome, separados por vírgula")
    p.add_argument("--top", type=int, default=0, help="incluir os N mais votados do cargo na UF")
    p.add_argument("--raio", type=float, default=config.RAIO_PADRAO_M, help="raio do entorno em metros")
    p.add_argument("--niveis", default="raio,bairro,setor", help="quais níveis do censo anexar")
    a = p.parse_args(argv)
    niveis = tuple(x.strip() for x in a.niveis.split(",") if x.strip())

    pasta = config.SAIDA / f"{a.ano}_{a.uf}_{slug(a.cargo)}"
    pasta.mkdir(parents=True, exist_ok=True)

    log("1/5 votos por seção (TSE)...")
    votos, validos, totais = tse.carregar_votos(a.ano, a.uf, a.cargo, a.turno,
                                                a.candidatos.split(","), a.top)
    totais.rename(columns={"NR_VOTAVEL": "numero", "NM_VOTAVEL": "nome"}).to_csv(
        pasta / "candidatos.csv", index=False)

    log("2/5 locais de votação (TSE)...")
    secoes, locais = tse.carregar_locais(a.ano, a.uf, a.turno)
    sem = locais[locais["lat"].isna()]
    if len(sem):
        sem.to_csv(pasta / "locais_sem_coordenada.csv", index=False)
        log(f"   {len(sem)} de {len(locais)} locais sem coordenada (ver locais_sem_coordenada.csv)")

    log("3/5 setores do Censo 2022 (IBGE)...")
    setores = censo.carregar_setores(a.uf)
    centroides, contem = obter_geo(a.uf, locais)

    log(f"4/5 perfil do entorno (raio {a.raio:.0f} m, níveis {', '.join(niveis)})...")
    perfil = entorno.perfil_locais(locais, setores, centroides, contem, a.raio, niveis)
    locais = pd.concat([locais, perfil], axis=1)

    log("5/5 cruzando e gravando...")
    # seção -> local (do arquivo de eleitorado; cai no NR_LOCAL do próprio arquivo de votos se faltar)
    v = votos.merge(secoes[tse.CHAVE_SECAO + ["NR_LOCAL_VOTACAO"]], on=tse.CHAVE_SECAO,
                    how="left", suffixes=("_votos", ""))
    if "NR_LOCAL_VOTACAO_votos" in v:
        v["NR_LOCAL_VOTACAO"] = v["NR_LOCAL_VOTACAO"].fillna(v.pop("NR_LOCAL_VOTACAO_votos"))
    v = v.merge(validos, on=tse.CHAVE_SECAO, how="left")
    v = v.merge(locais, on=tse.CHAVE_LOCAL, how="left")
    tot = v.groupby("NR_VOTAVEL")["QT_VOTOS"].transform("sum")
    v.insert(0, "votos_total_candidato", tot)
    v["pct_votos_validos_secao"] = (100 * v["QT_VOTOS"] / v["validos_secao"]).round(2)
    v["pct_do_total_do_candidato"] = (100 * v["QT_VOTOS"] / tot).round(4)

    ren = {"NM_VOTAVEL": "candidato", "NR_VOTAVEL": "numero", "NM_MUNICIPIO": "municipio",
           "NR_ZONA": "zona", "NR_SECAO": "secao", "NR_LOCAL_VOTACAO": "nr_local",
           "NM_LOCAL_VOTACAO": "local_votacao", "QT_VOTOS": "votos"}
    frente = ["candidato", "numero", "votos_total_candidato", "municipio", "zona", "secao",
              "nr_local", "local_votacao", "endereco", "bairro_tse", "bairro_ibge", "cd_setor",
              "lat", "lon", "votos", "validos_secao", "pct_votos_validos_secao",
              "pct_do_total_do_candidato"]
    v = v.rename(columns=ren)
    censo_cols = [c for c in v.columns if c.split("_")[0] in niveis and c not in frente]
    v = v[[c for c in frente if c in v] + censo_cols]
    v = v.sort_values(["votos_total_candidato", "candidato", "votos"], ascending=[False, True, False])
    v.to_csv(pasta / "votos_por_secao.csv", index=False)
    for (num, nome), g in v.groupby(["numero", "candidato"]):
        g.to_csv(pasta / f"secoes_{num}_{slug(nome)}.csv", index=False)

    # candidato x TODOS os locais da UF (inclui zeros: necessário p/ comparar com quem não votou nele)
    validos_local = (validos.merge(secoes, on=tse.CHAVE_SECAO, how="left")
                     .groupby(tse.CHAVE_LOCAL, as_index=False)["validos_secao"].sum()
                     .rename(columns={"validos_secao": "validos_local"}))
    base_locais = locais.merge(validos_local, on=tse.CHAVE_LOCAL, how="left")
    por_local = (votos.merge(secoes[tse.CHAVE_SECAO + ["NR_LOCAL_VOTACAO"]], on=tse.CHAVE_SECAO,
                             how="left", suffixes=("_votos", "")))
    if "NR_LOCAL_VOTACAO_votos" in por_local:
        por_local["NR_LOCAL_VOTACAO"] = por_local["NR_LOCAL_VOTACAO"].fillna(por_local.pop("NR_LOCAL_VOTACAO_votos"))
    por_local = por_local.groupby(["NR_VOTAVEL", "NM_VOTAVEL"] + tse.CHAVE_LOCAL, as_index=False)["QT_VOTOS"].sum()

    linhas_resumo, tabelas = [], []
    for (num, nome), g in por_local.groupby(["NR_VOTAVEL", "NM_VOTAVEL"]):
        t = base_locais.merge(g[tse.CHAVE_LOCAL + ["QT_VOTOS"]], on=tse.CHAVE_LOCAL, how="left")
        t["QT_VOTOS"] = t["QT_VOTOS"].fillna(0).astype(int)
        t.insert(0, "candidato", nome)
        t.insert(1, "numero", num)
        t["pct_votos_validos_local"] = (100 * t["QT_VOTOS"] / t["validos_local"]).round(2)
        tabelas.append(t)

        total = t["QT_VOTOS"].sum()
        ordenado = t["QT_VOTOS"].sort_values(ascending=False)
        n_locais = int((t["QT_VOTOS"] > 0).sum())
        top10 = ordenado.head(max(1, int(np.ceil(0.10 * n_locais)))).sum()
        mun = t.groupby("NM_MUNICIPIO")["QT_VOTOS"].sum().sort_values(ascending=False)
        base = {"candidato": nome, "numero": num, "votos": total,
                "secoes_com_voto": int((v["numero"] == num).sum()),
                "locais_com_voto": n_locais, "municipios_com_voto": int((mun > 0).sum()),
                "pct_votos_nos_10pct_locais_mais_fortes": round(100 * top10 / total, 1) if total else np.nan,
                "municipio_principal": mun.index[0], "pct_no_municipio_principal": round(100 * mun.iloc[0] / total, 1)}
        nivel = "raio" if "raio" in niveis else niveis[0]
        for ind in INDICADORES_RESUMO:
            col = f"{nivel}_{ind}"
            if col not in t:
                continue
            pv = media_ponderada(t, col, "QT_VOTOS")
            pu = media_ponderada(t, col, "validos_local")
            linhas_resumo.append({**base, "nivel_censo": nivel, "indicador": ind,
                                  "perfil_dos_votos_do_candidato": round(pv, 1),
                                  "perfil_do_eleitorado_da_uf": round(pu, 1),
                                  "diferenca": round(pv - pu, 1)})

    pd.concat(tabelas).to_csv(pasta / "votos_por_local_todos_os_locais.csv", index=False)
    resumo = pd.DataFrame(linhas_resumo)
    resumo.to_csv(pasta / "resumo_perfil.csv", index=False)

    log(f"\nPronto: {pasta}")
    if not resumo.empty:
        cab = resumo.drop_duplicates("numero")[["candidato", "numero", "votos", "locais_com_voto",
                                                 "pct_votos_nos_10pct_locais_mais_fortes",
                                                 "municipio_principal", "pct_no_municipio_principal"]]
        log(cab.to_string(index=False))
    return pasta


if __name__ == "__main__":
    main()
