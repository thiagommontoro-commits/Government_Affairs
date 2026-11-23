# 🏛️ Gov Signals LATAM

Radar diário de **Relações Governamentais e Institucionais** para 12 mercados da América Latina, no mesmo formato do Early Signals.

Todos os dias, às **06:00 de Brasília**, o GitHub Actions:

1. busca no Google News as manchetes públicas das últimas 48h (RSS, **sem chave de API**);
2. classifica a confiança da fonte (**A** oficial, **B** mídia confiável, **C** outra), remove duplicadas e marca o que é **NOVO**;
3. usa o Gemini (opcional) para selecionar, resumir em português e classificar o farol (Crítico, Atenção ou Positivo);
4. publica o `index.html` no GitHub Pages e guarda o histórico em `dados/`.

**Países:** Brasil, México, Argentina, Colômbia, Chile, Peru, Equador, Uruguai, Paraguai, Bolívia, Guatemala e República Dominicana.

**Subtópicos:** Tributário & Fiscal · Comércio Exterior & Tarifas · Política Agrícola & Crédito Rural · Indústria, Investimento & Financiamento · Regulação, Ambiente & Energia · Cenário Político & Legislativo.

## Idiomas (PT / EN / ES)

Os botões 🇧🇷 PT · 🇺🇸 EN · 🇪🇸 ES do topo funcionam como no Early Signals, com uma garantia a mais:

| Conteúdo | Como é traduzido |
|---|---|
| Interface, países, subtópicos, faróis, status, confiança, data e rodapé | Textos fixos nos 3 idiomas, gravados no HTML. A troca é imediata e funciona sem internet. |
| Títulos, resumos, sínteses e impactos (com Gemini) | O Gemini já escreve em PT, EN e ES. Também fica gravado no HTML. |
| Manchetes no modo regras (sem Gemini) | Google Tradutor da página, de qualquer idioma de origem para o idioma escolhido, inclusive do espanhol para o português. |

A escolha de idioma fica salva no navegador. O título original continua visível em cada notícia.

## Estrutura

```
gerador_gov_signals.py                       script principal (só Python padrão)
dashboard_template.html                      layout do dashboard
requirements.txt                             vazio (sem dependências)
.github/workflows/atualizar_gov_signals.yml  agendamento diário
index.html                                   gerado automaticamente
dados/ultimo.json                            dados da última execução
dados/arquivo/AAAA-MM-DD.json                histórico diário
dados/historico_links.json                   links já vistos (para marcar NOVO)
```

## Como publicar (passo a passo)

1. Crie um repositório novo no GitHub, por exemplo `Gov-Signals`.
2. Faça o upload de todos os arquivos, **incluindo a pasta `.github/workflows`**.
   No upload pelo navegador, pastas que começam com ponto podem não aparecer. Se isso acontecer, crie o arquivo manualmente em **Add file → Create new file** com o nome `.github/workflows/atualizar_gov_signals.yml` e cole o conteúdo.
3. **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `GEMINI_API_KEY`
   - Secret: a mesma chave usada no Early Signals.
   Sem a chave, o dashboard funciona no modo regras, sem resumos.
4. **Settings → Actions → General → Workflow permissions** → marque **Read and write permissions** → Save.
5. **Actions → Atualizar Gov Signals LATAM → Run workflow** para a primeira execução.
6. **Settings → Pages** → Source: **Deploy from a branch** → Branch: `main` / `(root)` → Save.
7. Depois de 1 a 2 minutos, o dashboard fica em `https://SEU-USUARIO.github.io/Gov-Signals/`.

## Ajustes rápidos

| O que mudar | Onde |
|---|---|
| Horário | `cron` no `.yml` (em UTC: `0 9 * * *` = 06:00 de Brasília) |
| Países | lista `PAISES` no script |
| Subtópicos e palavras de busca | lista `SUBTOPICOS` no script |
| Fontes confiáveis | lista `MIDIA_CONFIAVEL` no script |
| Janela de notícias | `JANELA_DIAS` no `.yml` |
| Notícias por subtópico | `MAX_POR_SUBTOPICO` no `.yml` |
| Modelo do Gemini | variável `GEMINI_MODEL` em Settings → Variables |

## Proteções

- Link, fonte e data sempre vêm da coleta, nunca da IA. Se a IA devolver um ID inventado, ele é descartado.
- Se a IA falhar, o país é classificado por regras.
- Se um país vier vazio por falha de rede, o dashboard mantém a última versão boa.
- Rodar de novo no mesmo dia reaproveita o cache, sem gastar cota. Para forçar, use **Run workflow** com "forcar" marcado.

---
Relações Governamentais LATAM
