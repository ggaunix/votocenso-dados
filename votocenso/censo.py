"""Censo 2022, agregados por setor censitário: leitura, filtro por UF e indicadores."""
from __future__ import annotations


import numpy as np
import pandas as pd

from . import config


def _so_digitos(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\D", "", regex=True)


def _abrir(caminho):
    """Detecta encoding e separador dos CSVs do IBGE (variam entre temas)."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            with open(caminho, encoding=enc) as f:
                linha = f.readline()
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if linha.count(";") >= linha.count(",") else ","
    return enc, sep


def _num(s: pd.Series) -> pd.Series:
    """'X' (suprimido) e vazio viram NaN; vírgula decimal vira ponto."""
    s = s.astype(str).str.strip().replace({"X": None, "x": None, "": None, "-": None, "nan": None})
    return pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")


def ler_tema(tema: str, uf: str, colunas: list[str]) -> pd.DataFrame:
    padrao = config.ARQUIVOS_CENSO[tema]
    achados = sorted(config.DADOS_IBGE.glob(padrao))
    if not achados:
        raise FileNotFoundError(f"Não achei {padrao} em {config.DADOS_IBGE}. Rode ./baixar_dados.sh.")
    caminho = achados[-1]  # o mais recente, se houver mais de uma versão
    enc, sep = _abrir(caminho)
    cab = pd.read_csv(caminho, sep=sep, encoding=enc, nrows=0).columns
    mapa = {c: c.upper() for c in cab}
    pedir = [c for c in cab if mapa[c] in {x.upper() for x in colunas} | {"CD_SETOR"}]
    faltam = {x.upper() for x in colunas} - {mapa[c] for c in pedir}
    if faltam:
        raise ValueError(
            f"{caminho.name}: códigos ausentes {sorted(faltam)}. "
            f"Confira o dicionário (python -m votocenso.verificar). Colunas: {list(cab)[:40]}..."
        )
    prefixo = config.UF_IBGE[uf]
    partes = []
    for b in pd.read_csv(caminho, sep=sep, encoding=enc, dtype=str, usecols=pedir, chunksize=500_000):
        b = b.rename(columns=mapa)
        b["CD_SETOR"] = _so_digitos(b["CD_SETOR"])
        partes.append(b[b["CD_SETOR"].str.startswith(prefixo)])
    return pd.concat(partes, ignore_index=True)


def carregar_setores(uf: str) -> pd.DataFrame:
    """Uma linha por setor da UF: atributos + contagens com nomes amigáveis."""
    cache = config.CACHE / f"setores_{uf}.pkl"
    if cache.exists():
        return pd.read_pickle(cache)

    por_tema: dict[str, list[str]] = {}
    for _, (tema, cod) in config.CONTAGENS.items():
        por_tema.setdefault(tema, []).append(cod)
    for _, (tema, cod, _) in config.MEDIAS.items():
        por_tema.setdefault(tema, []).append(cod)
    for _, (tema, cod) in config.MEDIANAS.items():
        por_tema.setdefault(tema, []).append(cod)

    base = ler_tema("basico", uf, config.ATRIBUTOS_SETOR[1:] + por_tema.pop("basico"))
    for tema, cods in por_tema.items():
        t = ler_tema(tema, uf, cods)
        base = base.merge(t, on="CD_SETOR", how="left")

    out = base[[c for c in config.ATRIBUTOS_SETOR if c in base]].copy()
    out["AREA_KM2"] = _num(out["AREA_KM2"])
    out["CD_SIT"] = pd.to_numeric(out["CD_SIT"], errors="coerce")
    out["CD_TIPO"] = pd.to_numeric(out["CD_TIPO"], errors="coerce")
    for nome, (_, cod) in config.CONTAGENS.items():
        out[nome] = _num(base[cod.upper()])
    for nome, (_, cod, peso) in config.MEDIAS.items():
        out[nome] = _num(base[cod.upper()])
        out[f"_{nome}_x_peso"] = out[nome] * out[peso]
        out[f"_{nome}_peso"] = out[peso].where(out[nome].notna())
    for nome, (_, cod) in config.MEDIANAS.items():
        out[nome] = _num(base[cod.upper()])
    # Populações em favela/comunidade urbana (CD_TIPO=1) e em setor rural (CD_SIT 5-8)
    out["pop_favela"] = out["pop"].where(out["CD_TIPO"] == 1, 0)
    out["pop_rural"] = out["pop"].where(out["CD_SIT"] >= 5, 0)
    # Bairro: municípios sem bairro oficial caem no subdistrito/distrito
    out["unidade_bairro"] = out["CD_BAIRRO"].where(out["CD_BAIRRO"].fillna("").str.len() > 0,
                                                   "D" + out["CD_DIST"].astype(str))
    out["nome_bairro"] = out["NM_BAIRRO"].where(out["CD_BAIRRO"].fillna("").str.len() > 0,
                                                out["NM_DIST"])
    config.CACHE.mkdir(parents=True, exist_ok=True)
    out.to_pickle(cache)
    return out


def colunas_somaveis(df: pd.DataFrame) -> list[str]:
    extras = ["AREA_KM2", "pop_favela", "pop_rural"]
    pesos = [c for c in df.columns if c.startswith("_") and (c.endswith("_x_peso") or c.endswith("_peso"))]
    return list(config.CONTAGENS) + extras + pesos


def indicadores(soma: pd.DataFrame) -> pd.DataFrame:
    """Converte somas de contagens em indicadores legíveis.

    Percentuais usam como denominador a soma das próprias categorias, para não
    misturar células suprimidas (X) no numerador com um total sem supressão.
    """
    r = pd.DataFrame(index=soma.index)
    r["pop"] = soma["pop"]
    r["domicilios"] = soma["domicilios"]
    r["area_km2"] = soma["AREA_KM2"].round(3)
    r["densidade_hab_km2"] = (soma["pop"] / soma["AREA_KM2"]).replace(np.inf, np.nan).round(0)

    idade_total = soma[[c for c in config.CONTAGENS if c.startswith("idade_")]].sum(axis=1, min_count=1)
    for nome, cols in config.FAIXAS.items():
        r[nome] = (100 * soma[cols].sum(axis=1, min_count=1) / idade_total).round(1)

    cores = [c for c in config.CONTAGENS if c.startswith("cor_")]
    cor_total = soma[cores].sum(axis=1, min_count=1)
    for c in cores:
        r["pct_" + c.removeprefix("cor_")] = (100 * soma[c] / cor_total).round(1)
    r["pct_preta_parda"] = (r["pct_preta"] + r["pct_parda"]).round(1)

    r["pct_alfabetizados_15_mais"] = (100 * soma["alfabetizados_15_mais"] / soma["pop_15_mais"]).round(1)

    for nome in config.MEDIAS:
        r[nome] = (soma[f"_{nome}_x_peso"] / soma[f"_{nome}_peso"]).round(0)

    r["pct_pop_favela"] = (100 * soma["pop_favela"] / soma["pop"]).round(1)
    r["pct_pop_rural"] = (100 * soma["pop_rural"] / soma["pop"]).round(1)
    return r


def somar_por(df: pd.DataFrame, chave) -> pd.DataFrame:
    cols = colunas_somaveis(df)
    return df.groupby(chave)[cols].sum(min_count=1)
