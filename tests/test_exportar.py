"""Teste do exportador do portal com os dados sintéticos de test_pipeline.

Uso: python -m tests.test_exportar [pasta_destino]
Com pasta_destino, mantém os arquivos gerados (para pré-visualizar o portal).
"""
import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

from tests.test_pipeline import gerar
from votocenso import config, exportar


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        gerar(tmp / "dados")
        pd.DataFrame([
            dict(NR_TURNO="1", SG_UF="SP", CD_CARGO="6", NR_CANDIDATO="1111", NM_URNA_CANDIDATO="JOÃO RICO",
                 SG_PARTIDO="AAA", DS_SIT_TOT_TURNO="ELEITO POR QP", NR_CPF_CANDIDATO="000"),
            dict(NR_TURNO="1", SG_UF="SP", CD_CARGO="6", NR_CANDIDATO="2222", NM_URNA_CANDIDATO="MARIA PERIFERIA",
                 SG_PARTIDO="BBB", DS_SIT_TOT_TURNO="SUPLENTE", NR_CPF_CANDIDATO="000"),
            dict(NR_TURNO="1", SG_UF="SP", CD_CARGO="5", NR_CANDIDATO="1111", NM_URNA_CANDIDATO="SENADOR TESTE",
                 SG_PARTIDO="CCC", DS_SIT_TOT_TURNO="ELEITO", NR_CPF_CANDIDATO="000"),
            dict(NR_TURNO="1", SG_UF="SP", CD_CARGO="6", NR_CANDIDATO="4444", NM_URNA_CANDIDATO="INDEFERIDO SEM VOTO",
                 SG_PARTIDO="DDD", DS_SIT_TOT_TURNO="#NULO#", DS_DETALHE_SITUACAO_CAND="INDEFERIDO", NR_CPF_CANDIDATO="000"),
        ]).to_csv(tmp / "dados/tse/consulta_cand_2022_SP.csv", sep=";", index=False, encoding="latin-1")

        tse_dir = tmp / "dados/tse"
        # presidente: 1º e 2º turno no mesmo arquivo de votos; no 2º, a seção 1 vai para o local 1001
        vs = pd.read_csv(tse_dir / "votacao_secao_2022_SP.csv", sep=";", encoding="latin-1", dtype=str)
        base = vs[vs["CD_CARGO"] == "6"].drop_duplicates(["NR_ZONA", "NR_SECAO"])
        pres = []
        for turno, cands_p in (("1", {"13": 60, "22": 50, "30": 10}), ("2", {"13": 70, "22": 55})):
            for _, r in base.iterrows():
                for nr, q in cands_p.items():
                    loc = "1001" if (turno == "2" and r["NR_SECAO"] == "1") else r["NR_LOCAL_VOTACAO"]
                    pres.append({**r.to_dict(), "NR_TURNO": turno, "CD_CARGO": "1", "DS_CARGO": "Presidente",
                                 "NR_VOTAVEL": nr, "NM_VOTAVEL": f"PRES {nr}", "QT_VOTOS": str(q), "NR_LOCAL_VOTACAO": loc})
        pd.concat([vs, pd.DataFrame(pres)]).to_csv(tse_dir / "votacao_secao_2022_SP.csv", sep=";", index=False, encoding="latin-1")
        pd.DataFrame([dict(NR_TURNO=t, SG_UF="BR", CD_CARGO="1", NR_CANDIDATO=n, NM_URNA_CANDIDATO=f"PRESIDENTE {n}",
                           SG_PARTIDO=pt, DS_SIT_TOT_TURNO=sit)
                      for t, n, pt, sit in (("1", "13", "P13", "2º TURNO"), ("1", "22", "P22", "2º TURNO"), ("1", "30", "P30", "NÃO ELEITO"),
                                            ("2", "13", "P13", "ELEITO"), ("2", "22", "P22", "NÃO ELEITO"))]
                     ).to_csv(tse_dir / "consulta_cand_2022_BR.csv", sep=";", index=False, encoding="latin-1")
        (tse_dir / "eleitorado_local_votacao_2022.csv").rename(tse_dir / "eleitorado_local_votacao_2022_SP.csv")
        ac = pd.read_csv(tse_dir / "eleitorado_local_votacao_2022_SP.csv", sep=";", encoding="latin-1", dtype=str).head(3)
        ac.assign(SG_UF="AC").to_csv(tse_dir / "eleitorado_local_votacao_2022_AC.csv", sep=";", index=False, encoding="latin-1")
        # setor repetido (como na malha real) não pode quebrar o cruzamento
        cc = tmp / "dados/cache/centroides_SP.csv"
        c0 = pd.read_csv(cc, dtype={"CD_SETOR": str})
        pd.concat([c0, c0.head(2)]).to_csv(cc, index=False)
        ct = tmp / "dados/contas"; ct.mkdir()
        pd.DataFrame([dict(DT_GERACAO="20/10/2026", CD_CARGO="6", NR_CANDIDATO="1111", VR_DESPESA_CONTRATADA="1.500,50"),
                      dict(DT_GERACAO="20/10/2026", CD_CARGO="6", NR_CANDIDATO="1111", VR_DESPESA_CONTRATADA="499,50")]
                     ).to_csv(ct / "despesas_contratadas_candidatos_2022_SP.csv", sep=";", index=False, encoding="latin-1")
        pd.DataFrame([dict(DT_GERACAO="20/10/2026", CD_CARGO="6", NR_CANDIDATO="1111", DS_FONTE_RECEITA="Fundo Especial", VR_RECEITA="3000,00"),
                      dict(DT_GERACAO="20/10/2026", CD_CARGO="6", NR_CANDIDATO="1111", DS_FONTE_RECEITA="Outros Recursos", VR_RECEITA="1000,00")]
                     ).to_csv(ct / "receitas_candidatos_2022_SP.csv", sep=";", index=False, encoding="latin-1")
        config.DADOS, config.DADOS_TSE, config.DADOS_IBGE = tmp / "dados", tmp / "dados/tse", tmp / "dados/ibge"
        config.CACHE = tmp / "dados/cache"
        destino = Path(sys.argv[1]) if len(sys.argv) > 1 else tmp / "out"
        exportar.main(["--ano", "2022", "--uf", "SP", "--raio", "800", "--saida", str(destino)])

        meta = json.loads((destino / "meta.json").read_text())
        L = json.loads(gzip.decompress((destino / "locais.json.gz").read_bytes()))
        c = json.loads(gzip.decompress((destino / "cand/6_1111.json.gz").read_bytes()))
        cand = {x["id"]: x for x in meta["candidatos"]}

        assert cand["6_1111"]["partido"] == "AAA" and cand["6_1111"]["situacao"] == "ELEITO POR QP"
        assert cand["6_3333"]["detalhe"] is True  # não eleito mais votado entra
        assert meta["min_votos_mapa"] == 1000
        assert cand["6_4444"]["votos"] == 0 and cand["6_4444"]["situacao"] == "INDEFERIDO" and not cand["6_4444"]["detalhe"]
        assert "NR_CPF" not in json.dumps(meta)
        assert L["n"] == 40 and len(L["lat"]) == 40 and L["lat"].count(None) == 2
        assert sum(c["v"]) == cand["6_1111"]["votos"] == sum(c["s_v"])
        assert all(sv >= v for sv, v in zip(c["s_val"], c["s_v"]))
        assert set(L["val"]) == {"1", "101", "5", "6"}, set(L["val"])
        assert meta["cargos"]["101"]["turno"] == 2 and meta["cargos"]["101"]["contas"] is False
        assert cand["101_13"]["situacao"] == "ELEITO" and cand["1_13"]["situacao"] == "2º TURNO" and cand["1_30"]["detalhe"]
        assert cand["101_13"]["votos"] == 70 * 120 and "contas" not in cand["1_13"]
        p2 = json.loads(gzip.decompress((destino / "cand/101_13.json.gz").read_bytes()))
        assert sum(p2["v"]) == 70 * 120
        li_1001 = L["nr"].index(1001)
        sec1 = [li for li, sc in zip(p2["s_li"], p2["s_sec"]) if sc == 1]
        assert sec1 == [li_1001], (sec1, li_1001)  # seção que mudou de local no 2º turno
        assert sum(L["val"]["101"]) == meta["cargos"]["101"]["validos_uf"] == 125 * 120
        assert sum(L["val"]["6"]) == meta["cargos"]["6"]["validos_uf"]
        assert len(L["ind"]["raio"]["renda_media_responsavel"]) == 40
        assert L["ind_mun"]["pop"][0] and L["ind_mun"]["renda_media_responsavel"][0] > 0, L["ind_mun"]["pop"]
        assert cand["6_1111"]["contas"] == {"desp": 2000.0, "rec": 4000.0, "pub": 3000.0}, cand["6_1111"].get("contas")
        assert "contas" not in cand["6_2222"] and meta["contas"]["situacao"] in ("parcial", "final")
        print(json.dumps(meta["avisos"]), len(meta["candidatos"]), "candidatos")
        print("OK: exportador")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
