"""Parte geográfica que depende de geopandas: centroides dos setores e setor que contém cada local.

Roda uma vez por UF e grava em dados/cache/; o resto do pipeline só usa pandas/scipy.
"""
from __future__ import annotations

import pandas as pd

from . import config

CRS_METROS = 5880  # SIRGAS 2000 / Brazil Polyconic


def _gpkg(uf: str):
    achados = sorted(config.DADOS_IBGE.glob(f"{uf}_setores_CD2022*.gpkg"))
    if not achados:
        raise FileNotFoundError(f"Malha {uf}_setores_CD2022.gpkg não encontrada em {config.DADOS_IBGE}")
    return achados[0]


def _ler_malha(uf: str):
    import geopandas as gpd

    g = gpd.read_file(_gpkg(uf))
    g.columns = [c.upper() if c != "geometry" else c for c in g.columns]
    g["CD_SETOR"] = g["CD_SETOR"].astype(str).str.replace(r"\D", "", regex=True)
    return g[["CD_SETOR", "geometry"]]


def centroides_setores(uf: str) -> pd.DataFrame:
    cache = config.CACHE / f"centroides_{uf}.csv"
    if cache.exists():
        return pd.read_csv(cache, dtype={"CD_SETOR": str})
    g = _ler_malha(uf)
    c = g.to_crs(CRS_METROS).centroid.to_crs(4326)
    out = pd.DataFrame({"CD_SETOR": g["CD_SETOR"], "lat": c.y, "lon": c.x})
    config.CACHE.mkdir(parents=True, exist_ok=True)
    out.to_csv(cache, index=False)
    return out


def setor_que_contem(uf: str, locais: pd.DataFrame) -> pd.Series:
    """CD_SETOR que contém o ponto de cada local (NaN se sem coordenada ou fora da malha)."""
    import geopandas as gpd

    g = _ler_malha(uf)
    tem = locais[["lat", "lon"]].notna().all(axis=1)
    pts = gpd.GeoDataFrame(
        index=locais.index[tem],
        geometry=gpd.points_from_xy(locais.loc[tem, "lon"], locais.loc[tem, "lat"]),
        crs=4326,
    ).to_crs(g.crs)
    j = gpd.sjoin(pts, g, how="left", predicate="within")
    j = j[~j.index.duplicated()]
    return j["CD_SETOR"].reindex(locais.index)


def limites(uf: str, setores: pd.DataFrame) -> dict:
    """Contornos simplificados de municípios e distritos, dissolvidos da malha de setores.

    Saem como GeoJSON (lon/lat com 4 casas, ~10 m) só para orientar o mapa do portal.
    """
    import geopandas as gpd  # noqa: F401

    g = _ler_malha(uf).merge(setores[["CD_SETOR", "CD_MUN", "NM_MUN", "CD_DIST", "NM_DIST"]],
                             on="CD_SETOR", how="left").to_crs(CRS_METROS)
    g["geometry"] = g.geometry.buffer(0)
    out = {}
    for nome, chave, rotulo, tol in (("mun", "CD_MUN", "NM_MUN", 120), ("dist", "CD_DIST", "NM_DIST", 50)):
        try:
            d = g.dissolve(by=chave, as_index=False, aggfunc={rotulo: "first"}, method="coverage")
        except Exception:  # noqa: BLE001  (geopandas antigo ou cobertura inválida)
            d = g.dissolve(by=chave, as_index=False, aggfunc={rotulo: "first"})
        d["geometry"] = d.geometry.simplify(tol, preserve_topology=True)
        d = d.to_crs(4326)
        feats = []
        for _, r in d.iterrows():
            geo = r.geometry.__geo_interface__
            feats.append({"type": "Feature", "properties": {"id": str(r[chave]), "nome": r[rotulo]},
                          "geometry": _arredondar(geo)})
        out[nome] = {"type": "FeatureCollection", "features": feats}
    return out


def _arredondar(geo):
    def r(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], 4), round(c[1], 4)]
        return [r(x) for x in c]
    return {"type": geo["type"], "coordinates": r(geo["coordinates"])}
