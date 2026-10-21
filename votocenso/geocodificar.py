"""Geocodifica pelo endereço os locais de votação que vieram sem coordenada do TSE.

Usa o Nominatim (OpenStreetMap): 1 requisição/segundo, conforme a política de uso.
Lê saida/<pasta>/locais_sem_coordenada.csv e grava/atualiza dados/locais_geocodificados.csv,
que o pipeline usa automaticamente na próxima execução.

Uso: python -m votocenso.geocodificar saida/2022_SP_deputado_federal/locais_sem_coordenada.csv --uf SP
"""
import argparse
import json
import time
import urllib.parse
import urllib.request

import pandas as pd

from . import config

URL = "https://nominatim.openstreetmap.org/search"
CHAVE = ["CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]


def buscar(q: dict) -> tuple[float, float] | None:
    url = URL + "?" + urllib.parse.urlencode({**q, "format": "json", "limit": 1, "countrycodes": "br"})
    req = urllib.request.Request(url, headers={"User-Agent": "votocenso/0.1 (pesquisa academica)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    return (float(res[0]["lat"]), float(res[0]["lon"])) if res else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("arquivo")
    p.add_argument("--uf", required=True)
    a = p.parse_args()
    faltam = pd.read_csv(a.arquivo)
    destino = config.DADOS / "locais_geocodificados.csv"
    feitos = pd.read_csv(destino) if destino.exists() else pd.DataFrame(columns=CHAVE + ["lat", "lon", "fonte"])
    ja = set(map(tuple, feitos[CHAVE].astype(int).values))
    novos = []
    for _, r in faltam.iterrows():
        k = tuple(int(r[c]) for c in CHAVE)
        if k in ja:
            continue
        rua = str(r.get("endereco", "")).split(" - ")[0]
        tentativas = [
            ({"street": rua, "city": r["NM_MUNICIPIO"], "state": a.uf}, "endereco"),
            ({"q": f'{r.get("NM_LOCAL_VOTACAO", "")}, {r["NM_MUNICIPIO"]}, {a.uf}'}, "nome_do_local"),
        ]
        for q, fonte in tentativas:
            time.sleep(1.1)
            try:
                achou = buscar(q)
            except Exception as e:  # noqa: BLE001
                print("erro:", e)
                achou = None
            if achou:
                novos.append({**dict(zip(CHAVE, k)), "lat": achou[0], "lon": achou[1], "fonte": fonte})
                print(f"ok  {r.get('NM_LOCAL_VOTACAO', k)} ({fonte})")
                break
        else:
            print(f"--  sem resultado: {r.get('NM_LOCAL_VOTACAO', k)} | {rua}")
    if novos:
        pd.concat([feitos, pd.DataFrame(novos)]).to_csv(destino, index=False)
    print(f"{len(novos)} novos de {len(faltam)}. Arquivo: {destino}")


if __name__ == "__main__":
    main()
