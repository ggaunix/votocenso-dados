# votocenso

Para cada candidato (senador, deputado federal/estadual/distrital): de quais seções vieram os votos, quantos em cada uma, e ao lado de cada seção o perfil do Censo 2022 no entorno do local de votação.

## Rodar

```bash
pip install -r requirements.txt
./baixar_dados.sh SP 2022            # TSE + IBGE (~1 GB; os agregados do censo são nacionais)
python -m votocenso.verificar        # confere os códigos V*** contra o dicionário do IBGE
python -m votocenso.run --ano 2022 --uf SP --cargo "deputado federal" --candidatos "NOME,1234"
python -m votocenso.run --ano 2022 --uf SP --cargo senador --top 3 --raio 800
```

`--candidatos` aceita número de urna ou trecho do nome (sem acento, sem maiúscula). `--top N` inclui os N mais votados. A lista completa do cargo sai em `candidatos.csv` na primeira execução.

O primeiro processamento de uma UF precisa de geopandas (lê a malha de setores e grava centroides em `dados/cache/`). Depois disso o resto roda só com pandas/scipy.

## Saída (`saida/<ano>_<UF>_<cargo>/`)

| arquivo | conteúdo |
|---|---|
| `secoes_<numero>_<nome>.csv` | uma linha por seção onde o candidato teve voto: município, zona, seção, local, endereço, bairro (TSE e IBGE), lat/lon, votos, válidos da seção, % da seção, % do total do candidato, e as colunas do censo |
| `votos_por_secao.csv` | o mesmo, todos os candidatos selecionados juntos |
| `votos_por_local_todos_os_locais.csv` | candidato × **todos** os locais da UF, inclusive onde teve zero. É a base para mapa e regressão |
| `resumo_perfil.csv` | por candidato: concentração dos votos e o perfil médio do entorno dos seus votos (ponderado por voto) contra o perfil do eleitorado da UF (ponderado por votos válidos) |
| `locais_sem_coordenada.csv` | locais que o TSE publicou sem lat/lon |
| `candidatos.csv` | todos os candidatos do cargo com o total na UF |

## Colunas do censo, em três níveis

Cada indicador aparece com prefixo `setor_`, `raio_` e `bairro_`:

- **setor**: o setor censitário onde fica o local (quadra/conjunto de quadras, centenas de domicílios)
- **raio**: soma dos setores cujo centroide está a até `--raio` metros do local (padrão 1000 m)
- **bairro**: bairro oficial do IBGE onde fica o local; município sem bairro cai no distrito

Indicadores: `pop`, `domicilios`, `area_km2`, `densidade_hab_km2`, `pct_0_14` / `15_24` / `25_39` / `40_59` / `60_mais`, `pct_branca` / `preta` / `parda` / `amarela` / `indigena` / `preta_parda`, `pct_alfabetizados_15_mais`, `renda_media_responsavel`, `pct_pop_favela` (favelas e comunidades urbanas), `pct_pop_rural`. No nível setor vem também `renda_mediana_responsavel`.

## Escolhas de método (e onde mexer)

- **Contagens são somadas, percentuais calculados depois.** A renda média é ponderada pelo número de responsáveis com renda. Os percentuais de idade e cor usam como denominador a soma das próprias categorias, para que as células suprimidas pelo IBGE (`X`) não distorçam a proporção.
- **Os raios de locais vizinhos se sobrepõem.** Isso é correto para descrever o entorno de cada local, mas significa que as linhas não devem ser somadas entre si.
- **Setor do local** é o setor que contém o ponto (geopandas). Sem geopandas, o pipeline usa o centroide mais próximo.
- **Coordenadas faltantes**: `python -m votocenso.geocodificar saida/.../locais_sem_coordenada.csv --uf SP` busca os endereços no Nominatim (1 req/s) e grava `dados/locais_geocodificados.csv`, que o pipeline usa na rodada seguinte. Também dá para preencher esse arquivo à mão ou com outra fonte, nas colunas `CD_MUNICIPIO,NR_ZONA,NR_LOCAL_VOTACAO,lat,lon`.
- **Códigos do IBGE** ficam em `votocenso/config.py`. Rode `verificar` antes de confiar nos números. Os códigos de renda (V06001/V06004/V06006) foram conferidos em fonte externa; os de idade, cor e alfabetização seguem o padrão dos agregados de 2022 e **precisam ser confirmados** no dicionário.

## O que o censo por setor não tem

- **Religião, escolaridade detalhada e trabalho** vêm do questionário da amostra. O IBGE não divulga esses dados por setor; o menor recorte é a área de ponderação. Para anexá-los, seria preciso cruzar o local com a área de ponderação e usar os microdados da amostra (próximo passo possível).
- **Renda**: o universo de 2022 só tem a renda do responsável pelo domicílio, não a renda domiciliar per capita.

## Testes

`python -m tests.test_pipeline` gera dados sintéticos no formato TSE/IBGE (com supressões `X`, separadores e encodings diferentes, locais sem coordenada, outra UF e outro cargo misturados) e roda o pipeline inteiro.
