#!/usr/bin/env bash
# Baixa TSE (votação por seção + eleitorado por local) e IBGE (Censo 2022 por setor).
# Uso: ./baixar_dados.sh SP 2022 [2026 ...]
set -euo pipefail

UF="${1:?uso: $0 UF ANO [ANO...]}"; shift
ANOS=("${@:-2022}")
UF="$(echo "$UF" | tr a-z A-Z)"
RAIZ="$(cd "$(dirname "$0")" && pwd)"
TSE="$RAIZ/dados/tse"; IBGE="$RAIZ/dados/ibge"
mkdir -p "$TSE" "$IBGE"

U_TSE="https://cdn.tse.jus.br/estatistica/sead/odsele"
U_IBGE="https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022"
U_SET="$U_IBGE/Agregados_por_Setores_Censitarios"

baixar() {  # url destino
  local url="$1" dest="$2"
  if [[ -s "$dest" ]]; then echo "ok (já existe) $(basename "$dest")"; return; fi
  echo "baixando $(basename "$dest")"
  if ! curl -fL --retry 3 --retry-delay 5 -o "$dest.part" "$url"; then
    rm -f "$dest.part"; echo "  FALHOU: $url" >&2; return 1
  fi
  mv "$dest.part" "$dest"
}

extrair() {  # zip pasta
  unzip -o -q "$1" -d "$2" && rm -f "$1"
}

# TSE: os zips ficam em dados/zips (em cache) e são baixados de novo só se o TSE publicar versão
# mais nova (curl -z compara com a data do zip local). Os CSVs são extraídos a cada execução.
ZIPS="$RAIZ/dados/zips"; mkdir -p "$ZIPS"
atualizar() {  # url zip
  local url="$1" zip="$2"
  if [[ -s "$zip" ]]; then
    if curl -fsSL --retry 3 --retry-delay 5 -R -z "$zip" -o "$zip.novo" "$url" && [[ -s "$zip.novo" ]]; then
      mv "$zip.novo" "$zip"; echo "atualizado $(basename "$zip") ($(date -r "$zip" -u +%F' '%H:%MZ))"
    else
      rm -f "$zip.novo"; echo "sem mudança $(basename "$zip") ($(date -r "$zip" -u +%F' '%H:%MZ))"
    fi
  else
    echo "baixando $(basename "$zip")"
    curl -fL --retry 3 --retry-delay 5 -R -o "$zip.part" "$url" || { rm -f "$zip.part"; echo "  FALHOU: $url" >&2; return 1; }
    mv "$zip.part" "$zip"; echo "  versão de $(date -r "$zip" -u +%F' '%H:%MZ)"
  fi
}

for ANO in "${ANOS[@]}"; do
  rm -f "$TSE"/votacao_secao_"${ANO}"_"${UF}"*.csv "$TSE"/consulta_cand_"${ANO}"_*.csv "$TSE"/eleitorado_local_votacao_"${ANO}"*.csv

  z="$ZIPS/votacao_secao_${ANO}_${UF}.zip"
  if atualizar "$U_TSE/votacao_secao/votacao_secao_${ANO}_${UF}.zip" "$z"; then unzip -o -q "$z" -d "$TSE"
  else echo "  (se for eleição recente, o TSE pode ainda não ter publicado)"; fi

  z="$ZIPS/consulta_cand_${ANO}.zip"
  if atualizar "$U_TSE/consulta_cand/consulta_cand_${ANO}.zip" "$z"; then
    unzip -o -q "$z" "consulta_cand_${ANO}_${UF}.csv" -d "$TSE" || echo "  consulta_cand sem arquivo de $UF" >&2
    unzip -o -q "$z" "consulta_cand_${ANO}_BR.csv" -d "$TSE" || echo "  consulta_cand sem arquivo nacional (BR)" >&2
  fi

  # contas de campanha: sempre baixa de novo (mudam até a prestação final); fica fora do cache
  CONTAS="$RAIZ/dados/contas"; mkdir -p "$CONTAS"; z="$CONTAS/contas_${ANO}.zip"; rm -f "$z"
  if baixar "$U_TSE/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_${ANO}.zip" "$z"; then
    unzip -o -q "$z" "*_${ANO}_${UF}.csv" -d "$CONTAS" || echo "  contas: sem arquivos de $UF no zip" >&2
    rm -f "$z"; find "$CONTAS" -mindepth 2 -name '*.csv' -exec mv -f {} "$CONTAS"/ \;
    ls -la "$CONTAS"
  else echo "  contas de campanha indisponíveis" >&2; fi

  z="$ZIPS/eleitorado_local_votacao_${ANO}.zip"
  if atualizar "$U_TSE/eleitorado_locais_votacao/eleitorado_local_votacao_${ANO}.zip" "$z"; then
    # a partir de 2026 o zip traz um arquivo por UF; antes, um nacional
    unzip -o -q "$z" "*_${UF}.csv" -d "$TSE" 2>/dev/null || unzip -o -q "$z" -d "$TSE"
  fi
done

# Censo 2022: malha da UF (com atributos) + agregados nacionais por setor
baixar "$U_SET/malha_com_atributos/setores/gpkg/UF/$UF/${UF}_setores_CD2022.gpkg" "$IBGE/${UF}_setores_CD2022.gpkg"

for f in Agregados_por_setores_basico_BR_20260520 Agregados_por_setores_demografia_BR \
         Agregados_por_setores_cor_ou_raca_BR Agregados_por_setores_alfabetizacao_BR; do
  if ls "$IBGE/$f"*.csv >/dev/null 2>&1; then echo "ok $f"; continue; fi
  baixar "$U_SET/Agregados_por_Setor_csv/$f.zip" "$IBGE/$f.zip" && extrair "$IBGE/$f.zip" "$IBGE"
done

f=Agregados_por_setores_renda_responsavel_BR_20260508_csv
if ls "$IBGE"/Agregados_por_setores_renda_responsavel_BR*.csv >/dev/null 2>&1; then echo "ok renda"
else baixar "$U_IBGE/Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/$f.zip" "$IBGE/$f.zip" && extrair "$IBGE/$f.zip" "$IBGE"; fi

baixar "$U_SET/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx" "$IBGE/dicionario_agregados_setores.xlsx"
baixar "$U_IBGE/Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/dicionario_de_dados_renda_responsavel_20260508.xlsx" "$IBGE/dicionario_renda_responsavel.xlsx"

# Alguns zips trazem subpastas: sobe os CSVs para dados/tse e dados/ibge
find "$TSE" -mindepth 2 -name '*.csv' -exec mv -n {} "$TSE"/ \;
find "$IBGE" -mindepth 2 -name '*.csv' -exec mv -n {} "$IBGE"/ \;
echo "feito. Agora: python -m votocenso.verificar"
