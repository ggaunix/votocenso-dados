"""Teste ponta a ponta com dados sintéticos no formato dos arquivos do TSE/IBGE.

Roda sem geopandas (usa centroides em cache). Uso: python -m tests.test_pipeline
"""
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from votocenso import config, run

rng = np.random.default_rng(42)
LAT0, LON0, PASSO = -23.60, -46.70, 0.004  # ~400 m


def gerar(raiz: Path, n_locais: int = 40):
    tse, ibge, cache = raiz / "tse", raiz / "ibge", raiz / "cache"
    for p in (tse, ibge, cache):
        p.mkdir(parents=True)

    # ---- setores: grade 20x20; renda e % branca crescem para nordeste
    linhas = []
    for i in range(20):
        for j in range(20):
            cd = f"3550308050{i:02d}{j:03d}"
            gradiente = (i + j) / 38
            pop = int(rng.integers(300, 1200))
            bairro = f"3550308{(i // 10) * 2 + (j // 10):03d}"
            linhas.append(dict(
                CD_SETOR=cd, lat=LAT0 + i * PASSO, lon=LON0 + j * PASSO, pop=pop,
                renda=1500 + 9000 * gradiente, branca=0.2 + 0.6 * gradiente,
                favela=1 if gradiente < 0.15 else 0, bairro=bairro,
            ))
    s = pd.DataFrame(linhas)
    pd.DataFrame({"CD_SETOR": s["CD_SETOR"], "lat": s["lat"], "lon": s["lon"]}).to_csv(
        cache / "centroides_SP.csv", index=False)

    basico = pd.DataFrame({
        "CD_SETOR": s["CD_SETOR"], "SITUACAO": "Urbana", "CD_SIT": "1", "CD_TIPO": s["favela"].astype(str),
        "AREA_KM2": "0,16", "CD_MUN": "3550308", "NM_MUN": "São Paulo", "CD_DIST": "355030805",
        "NM_DIST": "Distrito X", "CD_SUBDIST": "35503080500", "NM_SUBDIST": "",
        "CD_BAIRRO": s["bairro"], "NM_BAIRRO": "Bairro " + s["bairro"].str[-1],
        "v0001": s["pop"], "v0007": (s["pop"] / 2.8).astype(int),
    }).astype(str)
    basico.loc[5, "v0007"] = "X"  # supressão
    # setor de outra UF que tem de ser filtrado
    basico = pd.concat([basico, basico.iloc[[0]].assign(CD_SETOR="330455705000001")])
    basico.to_csv(ibge / "Agregados_por_setores_basico_BR_20260520.csv", sep=";", index=False, encoding="utf-8")

    idade = {f"V0{1031 + k}": (s["pop"] * w).round().astype(int)
             for k, w in enumerate([.06, .06, .07, .07, .08, .08, .16, .15, .12, .09, .06])}
    pd.DataFrame({"CD_SETOR": s["CD_SETOR"], **idade}).to_csv(
        ibge / "Agregados_por_setores_demografia_BR.csv", sep=";", index=False, encoding="latin-1")

    br = (s["pop"] * s["branca"]).round().astype(int)
    cor = pd.DataFrame({"CD_SETOR": s["CD_SETOR"], "V01317": br, "V01318": ((s["pop"] - br) * .25).astype(int),
                        "V01319": 2, "V01320": ((s["pop"] - br) * .74).astype(int), "V01321": 1})
    cor = cor.astype(str)
    cor.loc[7, "V01319"] = "X"
    cor.to_csv(ibge / "Agregados_por_setores_cor_ou_raca_BR.csv", sep=";", index=False)

    p15 = (s["pop"] * .81).astype(int)
    pd.DataFrame({"CD_SETOR": s["CD_SETOR"], "V00900": p15, "V00901": (p15 * (.9 + .09 * (s["renda"] / 10500))).astype(int)}
                 ).to_csv(ibge / "Agregados_por_setores_alfabetizacao_BR.csv", sep=";", index=False)

    resp = (s["pop"] / 3).astype(int)
    renda = pd.DataFrame({"CD_SETOR": s["CD_SETOR"], "V06001": resp, "V06004": s["renda"].round(2),
                          "V06006": (s["renda"] * .7).round(2)})
    renda.to_csv(ibge / "Agregados_por_setores_renda_responsavel_BR_20260508.csv", sep=",", index=False)

    # ---- locais de votação (TSE): 40 locais, 3 seções cada; 2 sem coordenada
    locs = []
    for k in range(n_locais):
        i, j = rng.uniform(0, 19, 2)
        lat, lon = LAT0 + i * PASSO, LON0 + j * PASSO
        sem = k in (3, 17)
        for sec in range(3):
            locs.append(dict(
                AA_ELEICAO="2022", NR_TURNO="1", SG_UF="SP", CD_MUNICIPIO="71072", NM_MUNICIPIO="SÃO PAULO",
                NR_ZONA=str(1 + k // 20), NR_SECAO=str(k * 10 + sec + 1), NR_LOCAL_VOTACAO=str(1000 + k),
                NM_LOCAL_VOTACAO=f"EMEF NÚMERO {k}", DS_ENDERECO=f"RUA {k}, {k * 7}", NM_BAIRRO=f"BAIRRO TSE {k % 5}",
                NR_CEP="01000000",
                NR_LATITUDE="-1" if sem else f"{lat:.6f}".replace(".", ","),
                NR_LONGITUDE="-1" if sem else f"{lon:.6f}".replace(".", ","),
                QT_ELEITOR_SECAO=str(300), _g=(i + j) / 38,
            ))
    L = pd.DataFrame(locs)
    outro = L.iloc[[0]].assign(SG_UF="RJ", NR_SECAO="9999")
    pd.concat([L, outro]).drop(columns="_g").to_csv(
        tse / "eleitorado_local_votacao_2022.csv", sep=";", index=False, encoding="latin-1")

    # ---- votos: JOÃO forte no nordeste rico, MARIA no sudoeste pobre
    votos = []
    for _, r in L.iterrows():
        g = r["_g"]
        dist = {1111: int(5 + 80 * g ** 2), 2222: int(5 + 80 * (1 - g) ** 2), 3333: 30, 22: 4, 95: 6, 96: 9}
        for nr, q in dist.items():
            nome = {1111: "JOÃO RICO", 2222: "MARIA PERIFERIA", 3333: "OUTRO", 22: "PL", 95: "Branco", 96: "Nulo"}[nr]
            votos.append(dict(ANO_ELEICAO="2022", NR_TURNO="1", SG_UF="SP", CD_MUNICIPIO="71072",
                              NM_MUNICIPIO="SÃO PAULO", NR_ZONA=r["NR_ZONA"], NR_SECAO=r["NR_SECAO"],
                              CD_CARGO="6", DS_CARGO="Deputado Federal", NR_VOTAVEL=str(nr), NM_VOTAVEL=nome,
                              QT_VOTOS=str(q), NR_LOCAL_VOTACAO=r["NR_LOCAL_VOTACAO"]))
        votos.append({**votos[-1], "CD_CARGO": "5", "NR_VOTAVEL": "1111", "QT_VOTOS": "999"})
    pd.DataFrame(votos).to_csv(tse / "votacao_secao_2022_SP.csv", sep=";", index=False, encoding="latin-1")
    return L


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        L = gerar(tmp / "dados")
        config.DADOS, config.DADOS_TSE, config.DADOS_IBGE = tmp / "dados", tmp / "dados/tse", tmp / "dados/ibge"
        config.CACHE, config.SAIDA = tmp / "dados/cache", tmp / "saida"

        pasta = run.main(["--ano", "2022", "--uf", "SP", "--cargo", "deputado federal",
                          "--candidatos", "joao,2222", "--raio", "800"])

        sec = pd.read_csv(pasta / "votos_por_secao.csv")
        res = pd.read_csv(pasta / "resumo_perfil.csv")
        loc = pd.read_csv(pasta / "votos_por_local_todos_os_locais.csv")
        cand = pd.read_csv(pasta / "candidatos.csv")

        assert set(sec["numero"]) == {1111, 2222}, sec["numero"].unique()
        assert sec.groupby("numero")["votos"].sum().to_dict() == cand.set_index("numero").loc[[1111, 2222], "votos_uf"].to_dict()
        assert 999 not in sec["votos"].values, "votos de senador vazaram"
        assert sec["validos_secao"].notna().all()
        # válidos excluem branco/nulo mas incluem legenda (22)
        r0 = sec.iloc[0]
        assert r0["validos_secao"] > r0["votos"]
        assert sec["raio_renda_media_responsavel"].notna().mean() > 0.9   # 2 locais sem coordenada
        assert sec["bairro_ibge"].notna().any()
        assert len(loc) == 2 * L["NR_LOCAL_VOTACAO"].nunique()
        assert (pasta / "locais_sem_coordenada.csv").exists()

        r = res.set_index(["numero", "indicador"])["diferenca"]
        assert r[(1111, "renda_media_responsavel")] > 0 > r[(2222, "renda_media_responsavel")]
        assert r[(1111, "pct_branca")] > 0 > r[(2222, "pct_branca")]
        p = sec[["raio_pct_0_14", "raio_pct_15_24", "raio_pct_25_39", "raio_pct_40_59", "raio_pct_60_mais"]].sum(axis=1, min_count=1)
        assert p.dropna().between(99.5, 100.5).all()

        with pd.option_context("display.width", 200, "display.max_columns", 30):
            print("\n== votos_por_secao.csv (primeiras colunas) ==")
            print(sec.iloc[:5, :18].to_string(index=False))
            print("\n== censo do entorno (raio) nas mesmas linhas ==")
            print(sec[[c for c in sec if c.startswith("raio_")]].iloc[:5, :10].to_string(index=False))
            print("\n== resumo_perfil.csv ==")
            print(res[["candidato", "indicador", "perfil_dos_votos_do_candidato",
                       "perfil_do_eleitorado_da_uf", "diferenca"]].to_string(index=False))
        print("\nOK: todos os testes passaram")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
