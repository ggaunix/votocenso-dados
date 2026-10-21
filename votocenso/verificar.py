"""Confere no dicionário oficial do IBGE o rótulo de cada código V*** usado em config.py.

Uso: python -m votocenso.verificar
Grava saida/variaveis_usadas.csv. Se algum rótulo não bater com o nome amigável,
corrija o código em config.py antes de rodar o pipeline.
"""
import pandas as pd

from . import config


def rotulos() -> dict[str, str]:
    achados: dict[str, str] = {}
    for xlsx in sorted(config.DADOS_IBGE.glob("dicionario*.xlsx")):
        for _, df in pd.read_excel(xlsx, sheet_name=None, header=None, dtype=str).items():
            for _, linha in df.iterrows():
                cel = [str(x).strip() for x in linha if pd.notna(x) and str(x).strip()]
                for i, c in enumerate(cel):
                    if c.upper().startswith("V0") and c.upper() not in achados:
                        resto = [x for j, x in enumerate(cel) if j != i]
                        achados[c.upper()] = " | ".join(resto)[:300]
    return achados


def main():
    rot = rotulos()
    if not rot:
        raise SystemExit(f"Nenhum dicionario*.xlsx em {config.DADOS_IBGE}. Rode ./baixar_dados.sh.")
    linhas = []
    for nome, (tema, cod) in config.CONTAGENS.items():
        linhas.append((nome, tema, cod, rot.get(cod.upper(), "NÃO ENCONTRADO")))
    for nome, (tema, cod, _) in config.MEDIAS.items():
        linhas.append((nome, tema, cod, rot.get(cod.upper(), "NÃO ENCONTRADO")))
    for nome, (tema, cod) in config.MEDIANAS.items():
        linhas.append((nome, tema, cod, rot.get(cod.upper(), "NÃO ENCONTRADO")))
    df = pd.DataFrame(linhas, columns=["nome_no_pipeline", "tema", "codigo", "rotulo_ibge"])
    config.SAIDA.mkdir(parents=True, exist_ok=True)
    df.to_csv(config.SAIDA / "variaveis_usadas.csv", index=False)
    with pd.option_context("display.max_colwidth", 110, "display.width", 200):
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
