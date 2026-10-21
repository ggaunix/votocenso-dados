"""Configuração: caminhos, URLs, códigos e mapeamento de variáveis do Censo 2022.

Os códigos V*** do Censo vêm dos dicionários oficiais do IBGE. O passo
`python -m votocenso.verificar` imprime o rótulo oficial de cada código usado
aqui, para conferir antes de confiar nos números.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
DADOS_TSE = DADOS / "tse"
DADOS_IBGE = DADOS / "ibge"
CACHE = DADOS / "cache"
SAIDA = RAIZ / "saida"

UF_IBGE = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17",
    "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27",
    "SE": "28", "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35", "PR": "41",
    "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}

# Cargos no arquivo votacao_secao do TSE (CD_CARGO)
CARGOS = {
    "senador": 5,
    "deputado federal": 6,
    "deputado estadual": 7,
    "deputado distrital": 8,
}
# NR_VOTAVEL que não são votos válidos
NAO_VALIDOS = {95, 96, 97}  # branco, nulo, anulado/apurado em separado

# ---------------------------------------------------------------- Censo 2022
# Arquivos de agregados por setor (nacionais; o pipeline filtra pela UF).
# tema -> padrão do nome do CSV dentro de dados/ibge/
ARQUIVOS_CENSO = {
    "basico": "Agregados_por_setores_basico_BR*.csv",
    "demografia": "Agregados_por_setores_demografia_BR*.csv",
    "cor_ou_raca": "Agregados_por_setores_cor_ou_raca_BR*.csv",
    "alfabetizacao": "Agregados_por_setores_alfabetizacao_BR*.csv",
    "renda": "Agregados_por_setores_renda_responsavel_BR*.csv",
}

# Contagens somáveis: nome amigável -> (tema, código).
# Somar contagens de vários setores é exato (exceto células suprimidas "X").
CONTAGENS = {
    "pop": ("basico", "V0001"),
    "domicilios": ("basico", "V0007"),       # domicílios particulares permanentes ocupados
    "idade_00_04": ("demografia", "V01031"),
    "idade_05_09": ("demografia", "V01032"),
    "idade_10_14": ("demografia", "V01033"),
    "idade_15_19": ("demografia", "V01034"),
    "idade_20_24": ("demografia", "V01035"),
    "idade_25_29": ("demografia", "V01036"),
    "idade_30_39": ("demografia", "V01037"),
    "idade_40_49": ("demografia", "V01038"),
    "idade_50_59": ("demografia", "V01039"),
    "idade_60_69": ("demografia", "V01040"),
    "idade_70_mais": ("demografia", "V01041"),
    "cor_branca": ("cor_ou_raca", "V01317"),
    "cor_preta": ("cor_ou_raca", "V01318"),
    "cor_amarela": ("cor_ou_raca", "V01319"),
    "cor_parda": ("cor_ou_raca", "V01320"),
    "cor_indigena": ("cor_ou_raca", "V01321"),
    "pop_15_mais": ("alfabetizacao", "V00900"),
    "alfabetizados_15_mais": ("alfabetizacao", "V00901"),
    "responsaveis_com_renda": ("renda", "V06001"),
}
# Médias não se somam: guardamos o código e ponderamos pelo peso indicado.
MEDIAS = {
    "renda_media_responsavel": ("renda", "V06004", "responsaveis_com_renda"),
}
# Apenas informativo (mediana não agrega entre setores; vai só no nível setor).
MEDIANAS = {
    "renda_mediana_responsavel": ("renda", "V06006"),
}

# Faixas etárias derivadas (somas de contagens acima)
FAIXAS = {
    "pct_0_14": ["idade_00_04", "idade_05_09", "idade_10_14"],
    "pct_15_24": ["idade_15_19", "idade_20_24"],
    "pct_25_39": ["idade_25_29", "idade_30_39"],
    "pct_40_59": ["idade_40_49", "idade_50_59"],
    "pct_60_mais": ["idade_60_69", "idade_70_mais"],
}

# Atributos de identificação do setor (arquivo básico)
ATRIBUTOS_SETOR = [
    "CD_SETOR", "CD_SIT", "CD_TIPO", "AREA_KM2", "CD_MUN", "NM_MUN",
    "CD_DIST", "NM_DIST", "CD_SUBDIST", "NM_SUBDIST", "CD_BAIRRO", "NM_BAIRRO",
]

RAIO_PADRAO_M = 1000

URL_TSE = "https://cdn.tse.jus.br/estatistica/sead/odsele"
URL_IBGE = "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022"
