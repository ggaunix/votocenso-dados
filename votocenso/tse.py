"""Leitura dos arquivos do TSE: votação por seção e eleitorado por local de votação."""
from __future__ import annotations

import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

CHAVE_SECAO = ["CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]
CHAVE_LOCAL = ["CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]


def _achar(pasta: Path, padrao: str) -> Path:
    achados = sorted(pasta.glob(padrao))
    if not achados:
        raise FileNotFoundError(
            f"Não achei {padrao} em {pasta}. Rode ./baixar_dados.sh primeiro."
        )
    return achados[0]


def _blocos(caminho: Path, colunas: list[str], obrigatorias: list[str], tamanho=2_000_000):
    """CSV do TSE: ';', latin-1, campos entre aspas. Lê em blocos só as colunas que existem."""
    cab = pd.read_csv(caminho, sep=";", encoding="latin-1", nrows=0).columns.tolist()
    falta = sorted(set(obrigatorias) - set(cab))
    if falta:
        raise ValueError(f"{caminho.name}: faltam colunas {falta}. Colunas presentes: {cab}")
    return pd.read_csv(
        caminho, sep=";", encoding="latin-1", dtype=str, keep_default_na=False,
        usecols=[c for c in colunas if c in cab], chunksize=tamanho,
    )


def _int(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("Int64")


def normalizar(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    return " ".join(txt.upper().split())


# --------------------------------------------------------------------- locais
def carregar_locais(ano: int, uf: str, turno: int = 1):
    """Retorna (secoes, locais).

    secoes: uma linha por seção -> local de votação.
    locais: uma linha por local com endereço, bairro declarado, lat/lon e eleitores.
    """
    caminho = None
    for padrao in (f"eleitorado_local_votacao_{ano}_{uf}.csv", f"eleitorado_local_votacao_{ano}_BRASIL.csv",
                   f"eleitorado_local_votacao_{ano}.csv"):
        if (config.DADOS_TSE / padrao).exists():
            caminho = config.DADOS_TSE / padrao
            break
    if caminho is None:
        caminho = _achar(config.DADOS_TSE, f"eleitorado_local_votacao_{ano}*.csv")
    cols = [
        "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO",
        "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "DS_ENDERECO", "NM_BAIRRO", "NR_CEP",
        "NR_LATITUDE", "NR_LONGITUDE", "QT_ELEITOR_SECAO", "QT_ELEITOR",
    ]
    obrig = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO"]
    partes = []
    for b in _blocos(caminho, cols, obrig):
        b = b[b["SG_UF"] == uf]
        if "NR_TURNO" in b:
            b = b[b["NR_TURNO"].isin([str(turno), ""])]
        partes.append(b)
    df = pd.concat(partes, ignore_index=True)
    if df.empty:
        raise ValueError(f"Nenhum local de votação para {uf} em {caminho.name}")
    for c in CHAVE_SECAO + ["NR_LOCAL_VOTACAO"]:
        df[c] = _int(df[c])
    qt = "QT_ELEITOR_SECAO" if "QT_ELEITOR_SECAO" in df else ("QT_ELEITOR" if "QT_ELEITOR" in df else None)
    df["eleitores"] = _int(df[qt]).fillna(0) if qt else 0

    def coord(col):
        if col not in df:
            return pd.Series(np.nan, index=df.index)
        return pd.to_numeric(df[col].str.replace(",", "."), errors="coerce")

    lat, lon = coord("NR_LATITUDE"), coord("NR_LONGITUDE")
    ok = lat.between(-34.5, 5.5) & lon.between(-74.5, -28.5)
    df["lat"] = lat.where(ok)
    df["lon"] = lon.where(ok)

    secoes = df[CHAVE_SECAO + ["NR_LOCAL_VOTACAO", "eleitores"]].drop_duplicates(CHAVE_SECAO)

    texto = [c for c in ["NM_MUNICIPIO", "NM_LOCAL_VOTACAO", "DS_ENDERECO", "NM_BAIRRO", "NR_CEP"] if c in df]
    locais = (
        df.groupby(CHAVE_LOCAL, as_index=False)
        .agg(**{c: (c, "first") for c in texto},
             lat=("lat", "median"), lon=("lon", "median"),
             eleitores=("eleitores", "sum"), n_secoes=("NR_SECAO", "nunique"))
        .rename(columns={"NM_BAIRRO": "bairro_tse", "DS_ENDERECO": "endereco"})
    )

    # Coordenadas geocodificadas por fora (opcional) completam as faltantes.
    extra = config.DADOS / "locais_geocodificados.csv"
    if extra.exists():
        g = pd.read_csv(extra, dtype={"CD_MUNICIPIO": "Int64", "NR_ZONA": "Int64", "NR_LOCAL_VOTACAO": "Int64"})
        locais = locais.merge(g[CHAVE_LOCAL + ["lat", "lon"]], on=CHAVE_LOCAL, how="left", suffixes=("", "_geo"))
        locais["lat"] = locais["lat"].fillna(locais["lat_geo"])
        locais["lon"] = locais["lon"].fillna(locais["lon_geo"])
        locais = locais.drop(columns=["lat_geo", "lon_geo"])
    return secoes, locais


# ---------------------------------------------------------------------- votos
def carregar_votos(ano: int, uf: str, cargo: str, turno: int, seletores: list[str], top: int = 0):
    """Duas passadas no votacao_secao: totais (para escolher candidatos) e extração.

    Retorna (votos_cand, validos_secao, totais_cand):
      votos_cand    : candidato x seção, só seções com voto
      validos_secao : votos válidos do cargo por seção (denominador do %)
      totais_cand   : total por candidato na UF, ordenado
    """
    cd_cargo = config.CARGOS[cargo.lower()]
    caminho = _achar(config.DADOS_TSE, f"votacao_secao_{ano}_{uf}*.csv")
    cols = ["NR_TURNO", "CD_CARGO", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO",
            "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS", "NR_LOCAL_VOTACAO"]
    obrig = ["CD_CARGO", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS"]

    def filtrar(b):
        b = b[b["CD_CARGO"] == str(cd_cargo)]
        if "NR_TURNO" in b:
            b = b[b["NR_TURNO"] == str(turno)]
        b = b.copy()
        for c in CHAVE_SECAO + ["NR_VOTAVEL", "QT_VOTOS"]:
            b[c] = _int(b[c])
        return b

    tot_parts, val_parts, nomes = [], [], {}
    for b in _blocos(caminho, cols, obrig):
        b = filtrar(b)
        if b.empty:
            continue
        tot_parts.append(b.groupby("NR_VOTAVEL")["QT_VOTOS"].sum())
        nomes.update(dict(zip(b["NR_VOTAVEL"], b["NM_VOTAVEL"])))
        v = b[~b["NR_VOTAVEL"].isin(config.NAO_VALIDOS)]
        val_parts.append(v.groupby(CHAVE_SECAO)["QT_VOTOS"].sum())
    if not tot_parts:
        raise ValueError(f"Nenhum voto para '{cargo}' turno {turno} em {caminho.name}")

    totais = pd.concat(tot_parts).groupby(level=0).sum().rename("votos_uf").reset_index()
    totais["NM_VOTAVEL"] = totais["NR_VOTAVEL"].map(nomes)
    totais = totais[~totais["NR_VOTAVEL"].isin(config.NAO_VALIDOS)]
    totais = totais.sort_values("votos_uf", ascending=False, ignore_index=True)
    validos = (pd.concat(val_parts).groupby(level=list(range(3))).sum()
               .rename("validos_secao").reset_index())

    escolhidos = selecionar(totais, seletores, top)
    if not escolhidos:
        raise ValueError("Nenhum candidato casou com a seleção. Veja saida/candidatos_*.csv")

    partes = []
    for b in _blocos(caminho, cols, obrig):
        b = filtrar(b)
        partes.append(b[b["NR_VOTAVEL"].isin(escolhidos)])
    votos = pd.concat(partes, ignore_index=True)
    if "NR_LOCAL_VOTACAO" in votos:
        votos["NR_LOCAL_VOTACAO"] = _int(votos["NR_LOCAL_VOTACAO"])
    keep = [c for c in CHAVE_SECAO + ["NR_LOCAL_VOTACAO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS"] if c in votos]
    votos = votos[keep].groupby([c for c in keep if c != "QT_VOTOS"], as_index=False, dropna=False)["QT_VOTOS"].sum()
    return votos, validos, totais


def selecionar(totais: pd.DataFrame, seletores: list[str], top: int) -> list[int]:
    nums: list[int] = []
    for s in seletores:
        s = s.strip()
        if not s:
            continue
        if s.isdigit():
            nums.append(int(s))
        else:
            alvo = normalizar(s)
            m = totais["NM_VOTAVEL"].map(normalizar).str.contains(alvo, regex=False)
            nums.extend(totais.loc[m, "NR_VOTAVEL"].astype(int).tolist())
    if top:
        nums.extend(totais["NR_VOTAVEL"].head(top).astype(int).tolist())
    vistos = set(totais["NR_VOTAVEL"].astype(int))
    return list(dict.fromkeys(n for n in nums if n in vistos))


# ------------------------------------------------------- vários cargos (portal)
def carregar_candidatos(ano: int, uf: str) -> pd.DataFrame:
    """consulta_cand: número, nome de urna, partido e situação final, por cargo.

    Lê só as colunas necessárias (o arquivo traz CPF e e-mail, que não usamos).
    """
    try:
        caminho = _achar(config.DADOS_TSE, f"consulta_cand_{ano}_{uf}*.csv")
    except FileNotFoundError:
        return pd.DataFrame(columns=["CD_CARGO", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "DS_SIT_TOT_TURNO"])
    cols = ["NR_TURNO", "SG_UF", "CD_CARGO", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "DS_SIT_TOT_TURNO"]
    df = pd.concat(_blocos(caminho, cols, ["CD_CARGO", "NR_CANDIDATO"]), ignore_index=True)
    if "NR_TURNO" in df:
        df = df[df["NR_TURNO"] == "1"]
    df["CD_CARGO"] = _int(df["CD_CARGO"])
    df["NR_CANDIDATO"] = _int(df["NR_CANDIDATO"])
    return df.drop_duplicates(["CD_CARGO", "NR_CANDIDATO"])


def votos_varios_cargos(ano: int, uf: str, cargos: list[int], escolher, turno: int = 1):
    """Passada 1: totais por (cargo, número) e válidos por (cargo, seção).
    escolher(totais) -> conjunto de (cargo, número) a detalhar.
    Passada 2: linhas candidato x seção dos escolhidos.
    """
    caminho = _achar(config.DADOS_TSE, f"votacao_secao_{ano}_{uf}*.csv")
    cols = ["NR_TURNO", "CD_CARGO", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
            "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS", "NR_LOCAL_VOTACAO"]
    obrig = ["CD_CARGO", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS"]
    alvo = {str(c) for c in cargos}

    def filtrar(b):
        b = b[b["CD_CARGO"].isin(alvo)]
        if "NR_TURNO" in b:
            b = b[b["NR_TURNO"] == str(turno)]
        b = b.copy()
        for c in ["CD_CARGO"] + CHAVE_SECAO + ["NR_VOTAVEL", "QT_VOTOS"]:
            b[c] = _int(b[c])
        return b

    tot, val, nomes = [], [], {}
    for b in _blocos(caminho, cols, obrig):
        b = filtrar(b)
        if b.empty:
            continue
        tot.append(b.groupby(["CD_CARGO", "NR_VOTAVEL"])["QT_VOTOS"].sum())
        nomes.update(dict(zip(zip(b["CD_CARGO"], b["NR_VOTAVEL"]), b["NM_VOTAVEL"])))
        v = b[~b["NR_VOTAVEL"].isin(config.NAO_VALIDOS)]
        val.append(v.groupby(["CD_CARGO"] + CHAVE_SECAO)["QT_VOTOS"].sum())
    if not tot:
        raise ValueError(f"Nenhum voto dos cargos {cargos} em {caminho.name}")
    totais = pd.concat(tot).groupby(level=[0, 1]).sum().rename("votos").reset_index()
    totais["NM_VOTAVEL"] = [nomes.get(k) for k in zip(totais["CD_CARGO"], totais["NR_VOTAVEL"])]
    totais = totais[~totais["NR_VOTAVEL"].isin(config.NAO_VALIDOS)]
    validos = pd.concat(val).groupby(level=[0, 1, 2, 3]).sum().rename("validos").reset_index()

    escolhidos = escolher(totais)
    partes = []
    for b in _blocos(caminho, cols, obrig):
        b = filtrar(b)
        chave = list(zip(b["CD_CARGO"], b["NR_VOTAVEL"]))
        partes.append(b[[k in escolhidos for k in chave]])
    votos = pd.concat(partes, ignore_index=True)
    votos = votos.groupby(["CD_CARGO", "NR_VOTAVEL"] + CHAVE_SECAO, as_index=False)["QT_VOTOS"].sum()
    return votos, validos, totais
