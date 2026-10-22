# Origem do Voto (votocenso) — contexto para sessões do Claude

Dono: Gabriel (`ggaunix`). Conversa e textos do site em português do Brasil. Ele tem formação em TI (SRE/DevOps): termos técnicos sem simplificar, sem elogio gratuito, sem suposições não ditas.

## O que é
Para cada senador/deputado: de quais seções e locais de votação vieram os votos, e o perfil do Censo 2022 no entorno de cada local. Objetivo de fundo: entender a base territorial e social do voto (ponto de partida para estudar influência de redes/desinformação).

- Site público: https://ggaunix.github.io/votocenso-dados/ (GitHub Pages, branch `gh-pages`, gerado pelo workflow). `#ranking` abre o ranking de campanha.
- Cópia privada no claude.ai ("Origem do Voto"): limite de 511 arquivos, então fica só com eleitos + 30 suplentes por cargo; o site público tem todos.
- Recorte atual: SP, eleições 2026, 1º turno × Censo 2022.

## Como roda (o ambiente do Claude NÃO alcança TSE/IBGE)
- Todo o download e processamento é no GitHub Actions (`.github/workflows/processar.yml`): push em `main` que mexa em `alvos.txt`, `votocenso/**`, `baixar_dados.sh` ou no workflow; disparo manual; e toda segunda 06:17 UTC (atualiza contas de campanha).
- Ao final, o job `site` monta o site (`portal/preparar.py` + `portal/montar_site.py`) e faz force-push em `gh-pages`.
- Logs de cada etapa ficam versionados em `diagnostico/<ano>_<UF>/` (os logs do Actions não são legíveis daqui).
- Novo recorte: uma linha `UF ANO` em `alvos.txt`.
- Mudança só no `portal/index.html` não dispara o workflow: publicar no `gh-pages` à mão (trocar só o `index.html`, mantendo o esqueleto `<!doctype html>…<body>` que o `montar_site.py` coloca) ou disparar o workflow.

## Regras de trabalho
- Commits com `ggaunix <ggaunix@users.noreply.github.com>` (pedido explícito do Gabriel; ignorar avisos de hook que pedem outro e-mail). Nunca o e-mail pessoal.
- Antes de publicar qualquer mudança de interface, testar no Chromium headless: `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` com o Playwright de `/home/claude/.npm-global/lib/node_modules/@playwright/mcp/node_modules/playwright`. O Leaflet do cdnjs não carrega daqui: compilar a 1.9.4 do código-fonte (`git clone --branch v1.9.4 https://github.com/Leaflet/Leaflet`, `esbuild src/Leaflet.js --bundle --format=iife --global-name=L`) e servir via `page.route`.
- Conferir números com dados reais antes de afirmar (somas, totais por candidato, plausibilidade do censo).
- Testes: `python -m tests.test_pipeline` e `python -m tests.test_exportar` (dados sintéticos).

## Decisões e armadilhas já resolvidas
- No claude.ai, `window.claude` é reservado: nunca declarar `const claude` (derrubou o script inteiro).
- Arquivos grandes do site vão como gzip em base64 (`.b64.txt`) porque o claude.ai não serve `.gz`.
- Censo: V00900 = 15+ que sabe ler; V00901 = 15+ que não sabe. Renda = V06001/V06004/V06006 (responsável).
- Bairro: o IBGE preenche código de bairro mesmo sem bairro; só vale onde há nome; senão distrito, senão município. Workflow falha se uma unidade passar de 5 milhões de habitantes.
- Malha do IBGE tem setores repetidos (301 em SP): dissolver antes do centroide.
- Em 2026 o TSE publica locais de votação em um arquivo por UF.
- Perfil: grupos de composição (cor, idade) somam 100%; célula suprimida pelo IBGE (1–2 pessoas) conta como 0; "pretos e pardos" é subtotal, não linha.
- Ordenação por %: linhas com poucos válidos vão para o fim (seção < 50, local < 200, bairro/município < 1.000).
- Mapa para todo candidato com ≥ 1.000 votos (`MIN_VOTOS_MAPA` em `exportar.py`).
- Contas de campanha: despesas contratadas + receitas; "dinheiro público" = Fundo Especial + Fundo Partidário. Parciais até a prestação final (1º turno: 03/11/2026).
- Senador 2026: dois votos por eleitor; % sobre o total de votos válidos para senador.

## Ideias em aberto
- Outras UFs; comparação 2022 × 2026 por local.
- Camada de exposição à informação (Meta Ad Library etc.), que nenhum projeto parecido tem.
- Religião/escolaridade detalhada só por área de ponderação (amostra), não por setor.
