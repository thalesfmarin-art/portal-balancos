# Portal de Resultados

Portal com os resultados trimestrais das ~100 empresas mais negociadas da B3 (IBrX-100) e de BDRs americanas ligadas a inteligência artificial. Atualiza sozinho duas vezes por dia pelo GitHub Actions e é publicado no GitHub Pages.

## Como funciona
- **B3:** balanços oficiais da CVM (Dados Abertos, DFP e ITR). A lista de empresas vem da carteira do IBrX-100 na B3.
- **BDRs:** demonstrações da empresa americana na SEC (10-Q/10-K) e datas de divulgação pelos comunicados 8-K.
- **Resumo:** veredito automático (Bom / Misto / Ruim) com os motivos e o que observar, calculado a partir dos números. Se você cadastrar o segredo `ANTHROPIC_API_KEY`, o resumo ganha um texto analítico escrito pelo Claude (só gasta quando sai resultado novo).
- **Calendário:** próximas divulgações estimadas pela data do mesmo trimestre no ano anterior (ou prazo legal).

## Ajustes
- Empresas: edite `config.json` (índices da B3, tickers extras ou excluídos, lista de BDRs).
- Horários: edite `cron` em `.github/workflows/atualizar.yml`.
- Rodar manualmente: aba **Actions** → **Atualizar portal** → **Run workflow**.
