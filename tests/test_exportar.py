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
        ]).to_csv(tmp / "dados/tse/consulta_cand_2022_SP.csv", sep=";", index=False, encoding="latin-1")

        tse_dir = tmp / "dados/tse"
        (tse_dir / "eleitorado_local_votacao_2022.csv").rename(tse_dir / "eleitorado_local_votacao_2022_SP.csv")
        ac = pd.read_csv(tse_dir / "eleitorado_local_votacao_2022_SP.csv", sep=";", encoding="latin-1", dtype=str).head(3)
        ac.assign(SG_UF="AC").to_csv(tse_dir / "eleitorado_local_votacao_2022_AC.csv", sep=";", index=False, encoding="latin-1")
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
        assert "NR_CPF" not in json.dumps(meta)
        assert L["n"] == 40 and len(L["lat"]) == 40 and L["lat"].count(None) == 2
        assert sum(c["v"]) == cand["6_1111"]["votos"] == sum(c["s_v"])
        assert all(sv >= v for sv, v in zip(c["s_val"], c["s_v"]))
        assert set(L["val"]) == {"5", "6", "7"}
        assert sum(L["val"]["6"]) == meta["cargos"]["6"]["validos_uf"]
        assert len(L["ind"]["raio"]["renda_media_responsavel"]) == 40
        print(json.dumps(meta["avisos"]), len(meta["candidatos"]), "candidatos")
        print("OK: exportador")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
