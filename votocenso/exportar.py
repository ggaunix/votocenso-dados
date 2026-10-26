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
import collections
import datetime as dt
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import censo, config, contas, entorno, tse

PRAZO_CONTAS_FINAL = {2026: dt.date(2026, 11, 3)}  # 1º turno; depois disso o TSE ainda leva dias para publicar

# Código do portal = CD_CARGO do TSE; 2º turno de cargo majoritário = CD_CARGO + 100.
NOMES_CARGO = {1: "Presidente – 1º turno", 101: "Presidente – 2º turno",
               3: "Governador – 1º turno", 103: "Governador – 2º turno", 5: "Senador",
               6: "Deputado federal", 7: "Deputado estadual", 8: "Deputado distrital"}
NAO_ELEITOS = {1: 20, 101: 2, 3: 15, 103: 2, 5: 5, 6: 30, 7: 30, 8: 15}  # mínimo de não eleitos com mapa, mesmo abaixo do corte de votos
# majoritários com número de 2 dígitos: para eles, número < 100 é candidato, não voto de legenda
DOIS_DIGITOS = {1, 101, 3, 103}
# cargos sem contas na tela, com o motivo
SEM_CONTAS = {
    1: "Campanha nacional: dividir o gasto da campanha inteira pelos votos de {uf} daria um número sem sentido.",
    101: "Campanha nacional: dividir o gasto da campanha inteira pelos votos de {uf} daria um número sem sentido.",
    103: "As contas de campanha (que cobrem os dois turnos) aparecem na aba do 1º turno.",
}




def e_candidato(cargo: pd.Series, nr: pd.Series) -> pd.Series:
    return (nr >= 100) | cargo.isin(DOIS_DIGITOS)


MIN_VOTOS_MAPA = 1000  # todo candidato com pelo menos isso ganha mapa e perfil

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
    p.add_argument("--min-votos", dest="min_votos", type=int, default=MIN_VOTOS_MAPA)
    a = p.parse_args(argv)
    destino = a.saida or (config.RAIZ / "portal_dados" / f"{a.ano}_{a.uf}")
    base = [5, 6, 8] if a.uf == "DF" else [5, 6, 7]
    mapa = {(c, 1): c for c in base} | {(1, 1): 1, (1, 2): 101, (3, 1): 3, (3, 2): 103}

    log("candidatos (consulta_cand)...")
    cands = tse.carregar_candidatos(a.ano, a.uf, mapa)

    def escolher(totais):
        t = totais[e_candidato(totais["CD_CARGO"], totais["NR_VOTAVEL"])].merge(
            cands, left_on=["CD_CARGO", "NR_VOTAVEL"], right_on=["CD_CARGO", "NR_CANDIDATO"], how="left")
        sit = t["DS_SIT_TOT_TURNO"].fillna("").str.upper()
        eleito = sit.str.startswith("ELEITO")
        sel = set(zip(t.loc[eleito, "CD_CARGO"], t.loc[eleito, "NR_VOTAVEL"]))
        for cargo in sorted(t["CD_CARGO"].dropna().unique()):
            resto = t[(t["CD_CARGO"] == cargo) & ~eleito].nlargest(
                NAO_ELEITOS.get(int(cargo), 10) * (1 if eleito.any() else 4), "votos")
            sel |= set(zip(resto["CD_CARGO"], resto["NR_VOTAVEL"]))
        corte = t[t["votos"] >= a.min_votos]
        sel |= set(zip(corte["CD_CARGO"], corte["NR_VOTAVEL"]))
        log(f"   candidatos com mapa: {len(sel)} (eleitos + todos com {a.min_votos} votos ou mais)")
        return {(int(c), int(n)) for c, n in sel}

    log("votos por seção (passadas 1 e 2)...")
    votos, validos, totais = tse.votos_varios_cargos(a.ano, a.uf, mapa, escolher)
    escolhidos = set(zip(votos["CD_CARGO"], votos["NR_VOTAVEL"]))
    cargos = sorted(int(c) for c in totais["CD_CARGO"].dropna().unique())
    faltam = [NOMES_CARGO[c] for c in mapa.values() if c not in cargos]
    log(f"   cargos com voto no arquivo: {[NOMES_CARGO[c] for c in cargos]}" + (f"; ainda sem dados: {faltam}" if faltam else ""))

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

    # seção -> índice do local. Vale primeiro o local informado no próprio arquivo de votos
    # (no 2º turno algumas seções mudam de endereço); senão, o do cadastro de locais.
    sec = secoes.merge(locais[tse.CHAVE_LOCAL].reset_index().rename(columns={"index": "li"}),
                       on=tse.CHAVE_LOCAL, how="left")[tse.CHAVE_SECAO + ["li"]]
    chave_li = locais[tse.CHAVE_LOCAL].astype("Int64").reset_index().rename(columns={"index": "li_voto"})
    chave_sec = sec.rename(columns={"li": "li_cad"})

    def a_local(df):
        k = df[tse.CHAVE_SECAO + ["NR_LOCAL_VOTACAO"]].astype("Int64").reset_index()
        k = k.merge(chave_li, on=tse.CHAVE_LOCAL, how="left").merge(chave_sec, on=tse.CHAVE_SECAO, how="left")
        k = k.set_index("index").reindex(df.index)
        mudou = int((k["li_voto"].notna() & k["li_cad"].notna() & (k["li_voto"] != k["li_cad"])).sum())
        return k["li_voto"].astype("float").fillna(k["li_cad"].astype("float")), mudou

    log("montando arquivos...")
    val_sec = validos.copy()
    val_sec["li"], mud = a_local(val_sec)
    log(f"   linhas cargo×seção em local diferente do cadastro: {mud}")
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
    # censo do município inteiro (soma de todos os setores do município), na ordem de `muns`.
    # O município do IBGE de cada nome do TSE sai dos setores onde ficam os locais.
    cod_ibge = (pd.DataFrame({"m": L["mun"], "cd": perfil["cd_setor"].astype("string").str[:7]})
                .dropna().groupby("m")["cd"].agg(lambda x: x.mode().iloc[0]))
    ind_mun = censo.indicadores(censo.somar_por(setores, "CD_MUN"))
    ind_mun.index = ind_mun.index.astype(str)
    L["ind_mun"] = {k: lista([ind_mun[k].get(cod_ibge.get(i)) if cod_ibge.get(i) in ind_mun.index else None
                              for i in range(len(muns))], casas)
                    for k, _, _, casas in INDICADORES if k in ind_mun}
    sem_cod = [muns[i] for i in range(len(muns)) if cod_ibge.get(i) not in ind_mun.index]
    log(f"   censo municipal: {len(muns) - len(sem_cod)} de {len(muns)} municípios" + (f"; sem: {sem_cod[:5]}" if sem_cod else ""))
    tam = gravar(destino / "locais.json.gz", L)
    log(f"   locais.json: {len(locais)} locais, {tam / 1e6:.1f} MB antes de comprimir")

    # candidatos
    v = votos.copy()
    v["li"], _ = a_local(v)
    sem_local = int(v.loc[v["li"].isna(), "QT_VOTOS"].sum())
    v = v.dropna(subset=["li"])
    v["li"] = v["li"].astype(int)
    val_por_sec = validos.groupby(["CD_CARGO"] + tse.CHAVE_SECAO, as_index=False)["validos"].sum()
    v = v.merge(val_por_sec, on=["CD_CARGO"] + tse.CHAVE_SECAO, how="left")
    for (cargo, nr), g in v.groupby(["CD_CARGO", "NR_VOTAVEL"]):
        por_local = g.groupby("li")["QT_VOTOS"].sum()
        g = g.sort_values(["li", "NR_SECAO"])
        gravar(destino / "cand" / f"{cargo}_{nr}.json.gz", {
            "id": f"{cargo}_{nr}",
            "li": por_local.index.tolist(), "v": lista(por_local.values),
            "s_li": g["li"].tolist(), "s_sec": lista(g["NR_SECAO"]),
            "s_v": lista(g["QT_VOTOS"]), "s_val": lista(g["validos"]),
        })

    # lista completa: quem teve voto (votacao_secao) + todos os registrados no consulta_cand,
    # inclusive indeferidos, renúncias e quem ficou com zero voto
    comvoto = totais[e_candidato(totais["CD_CARGO"], totais["NR_VOTAVEL"])].rename(columns={"NR_VOTAVEL": "NR_CANDIDATO"})
    reg = cands[cands["CD_CARGO"].isin(cargos)] if len(cands) else cands
    t = comvoto.merge(reg, on=["CD_CARGO", "NR_CANDIDATO"], how="outer")
    t["votos"] = t["votos"].fillna(0).astype(int)
    t = t.sort_values(["CD_CARGO", "votos"], ascending=[True, False])

    def texto(x):
        return x.strip() if isinstance(x, str) and x.strip() and x.strip().upper() not in ("#NULO#", "#NULO", "#NE#", "#NE", "NAN", "NÃO SE APLICA") else ""

    lista_cand = []
    for r in t.to_dict("records"):
        c, n = int(r["CD_CARGO"]), int(r["NR_CANDIDATO"])
        final = texto(r.get("DS_SIT_TOT_TURNO"))
        registro = next((texto(r.get(k)) for k in r if isinstance(k, str) and k.startswith("DS_DETALHE") and texto(r.get(k))), "")
        apto = next((texto(r.get(k)) for k in ("DS_SITUACAO_CANDIDATURA", "DS_SIT_CANDIDATURA", "DS_SITUACAO_CANDIDATO")
                     if texto(r.get(k))), "")
        registro = registro or (apto if apto.upper() not in ("APTO", "") else "")
        lista_cand.append({
            "id": f"{c}_{n}", "cargo": c, "nr": n,
            "nome": texto(r.get("NM_URNA_CANDIDATO")) or texto(r.get("NM_VOTAVEL")) or str(n),
            "partido": texto(r.get("SG_PARTIDO")),
            # situação final do turno; sem ela (indeferido, renúncia...), a situação do registro
            "situacao": final or registro or apto,
            "registro": registro,
            "votos": int(r["votos"]), "detalhe": (c, n) in escolhidos,
        })
    for cargo in cargos:
        reg_c = int((reg["CD_CARGO"] == cargo).sum()) if len(reg) else 0
        vot_c = int((comvoto["CD_CARGO"] == cargo).sum())
        tot_c = sum(1 for x in lista_cand if x["cargo"] == cargo)
        log(f"   cargo {cargo}: {reg_c} registrados no consulta_cand, {vot_c} com voto, {tot_c} na lista")
        fora = collections.Counter(x["registro"] or "(sem registro)" for x in lista_cand if x["cargo"] == cargo and x["votos"] == 0)
        if fora:
            log(f"      sem voto, por situação do registro: {dict(fora.most_common(8))}")

    # prestação de contas de campanha (falha aqui não derruba o resto)
    info_contas = None
    try:
        tab, info = contas.carregar(a.ano, a.uf)
        if tab is not None:
            por = {(int(c), int(n)): r for c, n, r in zip(tab["CD_CARGO"], tab["NR_CANDIDATO"], tab.to_dict("records"))}
            n_com = 0
            for c in lista_cand:
                if c["cargo"] in SEM_CONTAS:
                    continue
                r = por.get((c["cargo"], c["nr"]))
                if r:
                    c["contas"] = {"desp": round(float(r.get("despesas", 0)), 2), "rec": round(float(r.get("receitas", 0)), 2),
                                   "pub": round(float(r.get("publico", 0)), 2)}
                    n_com += 1
            prazo = PRAZO_CONTAS_FINAL.get(a.ano)
            final = prazo is not None and dt.date.today() > prazo + dt.timedelta(days=10)
            info_contas = {**info, "situacao": "final" if final else "parcial",
                           "prazo_final": prazo.isoformat() if prazo else None, "candidatos_com_contas": n_com}
            log(f"   contas: {n_com} candidatos com prestação de contas ({info_contas['situacao']}, ref. {info.get('referencia')})")
        else:
            log(f"   contas: {info}")
    except Exception as e:  # noqa: BLE001
        log(f"   contas: ignoradas por erro: {e}")

    tem_limites = False
    try:
        lim = geo.limites(a.uf, setores)
        gravar(destino / "limites.json.gz", lim)
        tem_limites = True
    except ImportError:
        log("   geopandas ausente: limites.json não gerado")

    meta = {
        "ano": a.ano, "uf": a.uf, "turno": 2 if any(c > 100 for c in cargos) else 1, "raio_m": a.raio, "min_votos_mapa": a.min_votos,
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "municipios": muns,
        "cargos": {str(c): {"nome": NOMES_CARGO[c],
                            "validos_uf": int(validos.loc[validos["CD_CARGO"] == c, "validos"].sum()),
                            "turno": 2 if c > 100 else 1, "contas": c not in SEM_CONTAS,
                            "motivo_contas": SEM_CONTAS.get(c, "").format(uf=a.uf)}
                   for c in cargos},
        "candidatos": lista_cand,
        "contas": info_contas,
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
            f"TSE, prestação de contas eleitorais de candidatos {a.ano}",
        ],
    }
    gravar(destino / "meta.json", meta, comprimir=False)
    log(f"pronto: {destino} ({len(escolhidos)} candidatos detalhados)")
    return destino


if __name__ == "__main__":
    main()
