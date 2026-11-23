#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GOV SIGNALS LATAM - Radar diario de Relacoes Governamentais e Institucionais
=============================================================================
Mesmo conceito do Early Signals:
  1. Busca manchetes do dia no Google News (RSS publico, sem chave de API).
  2. Filtra por fonte confiavel, remove duplicadas e marca o que e NOVO.
  3. (Opcional) Usa o Gemini para selecionar, resumir e classificar em PT, EN e ES.
     Sem GEMINI_API_KEY o script funciona do mesmo jeito, com regras simples.
  4. Gera o index.html (dashboard trilingue PT/EN/ES) e salva o historico em /dados.

Nenhuma biblioteca externa e necessaria (somente Python padrao).

Variaveis de ambiente (todas opcionais):
  GEMINI_API_KEY     chave do Google Gemini (secret no GitHub)
  GEMINI_MODEL       modelo do Gemini (padrao: gemini-2.5-flash)
  JANELA_DIAS        janela de busca de noticias em dias (padrao: 2)
  MAX_POR_SUBTOPICO  noticias exibidas por subtopico/pais (padrao: 3)
  FORCAR             "true" ignora o cache do dia e gera tudo novamente

Relações Governamentais LATAM
"""
import datetime as dt
import difflib
import html
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

# ===========================================================================
# 1. CONFIGURACOES GERAIS
# ===========================================================================
BASE = Path(__file__).resolve().parent
TEMPLATE = BASE / "dashboard_template.html"
SAIDA_HTML = BASE / "index.html"
PASTA_DADOS = BASE / "dados"
PASTA_ARQUIVO = PASTA_DADOS / "arquivo"
ARQ_ULTIMO = PASTA_DADOS / "ultimo.json"
ARQ_HISTORICO = PASTA_DADOS / "historico_links.json"

JANELA_DIAS = int(os.getenv("JANELA_DIAS", "2"))
MAX_POR_SUBTOPICO = int(os.getenv("MAX_POR_SUBTOPICO", "3"))
MAX_CANDIDATOS_IA = 8          # manchetes por subtopico enviadas para a IA
DIAS_HISTORICO = 30            # por quanto tempo lembrar links ja vistos
PAUSA_RSS = 1.0                # segundos entre buscas no Google News
PAUSA_IA = 6.0                 # segundos entre chamadas ao Gemini (cota gratuita)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
FORCAR = os.getenv("FORCAR", "false").strip().lower() in ("1", "true", "sim", "yes")

FUSO_BR = dt.timezone(dt.timedelta(hours=-3))
AGORA = dt.datetime.now(FUSO_BR)
HOJE = AGORA.date().isoformat()

# ===========================================================================
# 2. PAISES (12 maiores mercados da America Latina para o escopo)
#    incluir_nome=True -> adiciona o nome do pais na busca (paises sem edicao
#    propria do Google News).
# ===========================================================================
PAISES = [
    {"cod": "br", "nome": "Brasil",       "bandeira": "🇧🇷", "idioma": "pt", "hl": "pt-BR",  "gl": "BR", "ceid": "BR:pt-419", "busca_nome": "Brasil",               "incluir_nome": False},
    {"cod": "mx", "nome": "México",       "bandeira": "🇲🇽", "idioma": "es", "hl": "es-419", "gl": "MX", "ceid": "MX:es-419", "busca_nome": "México",               "incluir_nome": False},
    {"cod": "ar", "nome": "Argentina",    "bandeira": "🇦🇷", "idioma": "es", "hl": "es-419", "gl": "AR", "ceid": "AR:es-419", "busca_nome": "Argentina",            "incluir_nome": False},
    {"cod": "co", "nome": "Colômbia",     "bandeira": "🇨🇴", "idioma": "es", "hl": "es-419", "gl": "CO", "ceid": "CO:es-419", "busca_nome": "Colombia",             "incluir_nome": False},
    {"cod": "cl", "nome": "Chile",        "bandeira": "🇨🇱", "idioma": "es", "hl": "es-419", "gl": "CL", "ceid": "CL:es-419", "busca_nome": "Chile",                "incluir_nome": False},
    {"cod": "pe", "nome": "Peru",         "bandeira": "🇵🇪", "idioma": "es", "hl": "es-419", "gl": "PE", "ceid": "PE:es-419", "busca_nome": "Perú",                 "incluir_nome": False},
    {"cod": "ec", "nome": "Equador",      "bandeira": "🇪🇨", "idioma": "es", "hl": "es-419", "gl": "EC", "ceid": "EC:es-419", "busca_nome": "Ecuador",              "incluir_nome": True},
    {"cod": "uy", "nome": "Uruguai",      "bandeira": "🇺🇾", "idioma": "es", "hl": "es-419", "gl": "UY", "ceid": "UY:es-419", "busca_nome": "Uruguay",              "incluir_nome": True},
    {"cod": "py", "nome": "Paraguai",     "bandeira": "🇵🇾", "idioma": "es", "hl": "es-419", "gl": "PY", "ceid": "PY:es-419", "busca_nome": "Paraguay",             "incluir_nome": True},
    {"cod": "bo", "nome": "Bolívia",      "bandeira": "🇧🇴", "idioma": "es", "hl": "es-419", "gl": "BO", "ceid": "BO:es-419", "busca_nome": "Bolivia",              "incluir_nome": True},
    {"cod": "gt", "nome": "Guatemala",    "bandeira": "🇬🇹", "idioma": "es", "hl": "es-419", "gl": "GT", "ceid": "GT:es-419", "busca_nome": "Guatemala",            "incluir_nome": True},
    {"cod": "do", "nome": "Rep. Dominicana", "bandeira": "🇩🇴", "idioma": "es", "hl": "es-419", "gl": "DO", "ceid": "DO:es-419", "busca_nome": "República Dominicana", "incluir_nome": True},
]
PAIS_POR_COD = {p["cod"]: p for p in PAISES}

# ===========================================================================
# 3. SUBTOPICOS DE RELACOES GOVERNAMENTAIS / INSTITUCIONAIS
#    "pt" e "es" sao as consultas enviadas ao Google News.
# ===========================================================================
SUBTOPICOS = [
    {"id": "fiscal", "nome": "Tributário & Fiscal", "icone": "💰",
     "pt": '("reforma tributária" OR imposto OR tributação OR "Receita Federal" OR IPI OR ICMS OR CBS OR IBS)',
     "es": '("reforma tributaria" OR "reforma fiscal" OR impuesto OR impuestos OR IVA OR recaudación)'},
    {"id": "comercio", "nome": "Comércio Exterior & Tarifas", "icone": "🚢",
     "pt": '("tarifa de importação" OR "comércio exterior" OR Mercosul OR antidumping OR "acordo comercial" OR Camex)',
     "es": '(arancel OR aranceles OR "comercio exterior" OR Mercosur OR "acuerdo comercial" OR "libre comercio" OR aduana)'},
    {"id": "agro", "nome": "Política Agrícola & Crédito Rural", "icone": "🌾",
     "pt": '("Plano Safra" OR "crédito rural" OR "Ministério da Agricultura" OR "política agrícola" OR Pronaf OR Moderfrota)',
     "es": '("política agrícola" OR "crédito agrícola" OR "crédito agropecuario" OR "ministerio de agricultura" OR "sector agropecuario" OR retenciones)'},
    {"id": "industria", "nome": "Indústria, Investimento & Financiamento", "icone": "🏭",
     "pt": '(BNDES OR "política industrial" OR "Nova Indústria Brasil" OR "incentivo ao investimento" OR "máquinas agrícolas" OR "máquinas e equipamentos")',
     "es": '("política industrial" OR "incentivos a la inversión" OR "maquinaria agrícola" OR RIGI OR "banca de desarrollo" OR "inversión extranjera")'},
    {"id": "regulacao", "nome": "Regulação, Ambiente & Energia", "icone": "⚖️",
     "pt": '(regulamentação OR "licenciamento ambiental" OR emissões OR biocombustível OR diesel OR "Combustível do Futuro" OR desmatamento)',
     "es": '(regulación OR "normativa ambiental" OR emisiones OR biocombustibles OR diésel OR "ley de energía" OR combustibles)'},
    {"id": "politica", "nome": "Cenário Político & Legislativo", "icone": "🏛️",
     "pt": '(Congresso OR Senado OR "Câmara dos Deputados" OR eleições OR "projeto de lei" OR STF)',
     "es": '(Congreso OR Senado OR "Asamblea Legislativa" OR elecciones OR "proyecto de ley" OR gabinete)'},
]
SUB_POR_ID = {s["id"]: s for s in SUBTOPICOS}

# ===========================================================================
# 4. FONTES: oficial (A), midia confiavel (B), demais (C)
# ===========================================================================
RE_OFICIAL = re.compile(
    r"(\.gov\.[a-z]{2}|\.gob\.[a-z]{2}|\.gub\.uy|gob\.mx|gob\.pe|gob\.ar|gob\.cl|"
    r"camara\.leg\.br|senado\.leg\.br|congreso|asamblea|diariooficial|boletinoficial|"
    r"dof\.gob|andina\.pe|agenciabrasil\.ebc|telam|bcb\.gov)", re.I)

MIDIA_CONFIAVEL = [
    # Internacional
    "reuters.com", "bloomberg.com", "bloomberglinea.com", "apnews.com", "efe.com", "afp.com",
    "ft.com", "wsj.com", "economist.com", "bbc.com", "dw.com", "elpais.com", "swissinfo.ch",
    # Brasil
    "valor.globo.com", "g1.globo.com", "oglobo.globo.com", "globorural.globo.com", "estadao.com.br",
    "folha.uol.com.br", "uol.com.br", "cnnbrasil.com.br", "infomoney.com.br", "exame.com",
    "poder360.com.br", "jota.info", "correiobraziliense.com.br", "canalrural.com.br",
    "noticiasagricolas.com.br", "agrolink.com.br", "metropoles.com", "veja.abril.com.br",
    # Mexico
    "elfinanciero.com.mx", "eleconomista.com.mx", "expansion.mx", "eluniversal.com.mx",
    "milenio.com", "reforma.com", "jornada.com.mx", "forbes.com.mx",
    # Argentina
    "lanacion.com.ar", "clarin.com", "infobae.com", "ambito.com", "cronista.com", "perfil.com",
    "pagina12.com.ar", "iprofesional.com",
    # Colombia
    "eltiempo.com", "portafolio.co", "larepublica.co", "elespectador.com", "semana.com", "valoraanalitik.com",
    # Chile
    "df.cl", "latercera.com", "emol.com", "biobiochile.cl", "elmostrador.cl", "cooperativa.cl",
    # Peru
    "gestion.pe", "elcomercio.pe", "larepublica.pe", "rpp.pe", "infobae.com",
    # Equador
    "primicias.ec", "eluniverso.com", "elcomercio.com", "expreso.ec",
    # Uruguai
    "elobservador.com.uy", "elpais.com.uy", "montevideo.com.uy", "ladiaria.com.uy",
    # Paraguai
    "abc.com.py", "ultimahora.com", "lanacion.com.py", "5dias.com.py",
    # Bolivia
    "eldeber.com.bo", "la-razon.com", "opinion.com.bo", "paginasiete.bo", "erbol.com.bo",
    # Guatemala
    "prensalibre.com", "republica.gt", "soy502.com",
    # Republica Dominicana
    "diariolibre.com", "listindiario.com", "eldinero.com.do", "elcaribe.com.do",
]

# Palavras-chave para a classificacao sem IA (modo regras)
PALAVRAS_CRITICO = ["aumento de imposto", "aumenta imposto", "alta de imposto", "sobretaxa", "nova taxa",
                    "eleva", "elevação", "aumento de", "alza", "aumenta", "suba de", "recorte", "corte de",
                    "suspende", "suspensão", "restrição", "restricción", "prohíbe", "proíbe", "crise", "crisis",
                    "greve", "paro", "bloqueio", "bloqueo", "arancel adicional", "tarifaço", "veto", "default"]
PALAVRAS_POSITIVO = ["redução", "reduz", "reducción", "reduce", "isenção", "exención", "incentivo",
                     "estímulo", "acordo", "acuerdo", "linha de crédito", "línea de crédito", "libera",
                     "amplia", "amplía", "desoneração", "elimina", "simplifica", "aprova crédito", "investimento"]
PALAVRAS_STATUS = [
    ("Em vigor",       ["entra em vigor", "entra en vigor", "publicado no diário", "publica decreto", "decreto", "vigente", "vigência", "vigencia"]),
    ("Aprovado",       ["aprova", "aprovado", "aprovada", "aprueba", "aprobó", "aprobado", "sanciona", "promulga"]),
    ("Em tramitação",  ["comissão", "comisión", "votação", "votación", "plenário", "pleno", "tramita", "debate"]),
    ("Proposta",       ["projeto", "proposta", "propõe", "proyecto", "propone", "iniciativa", "estuda", "analiza", "planeja"]),
]


# ===========================================================================
# 5. FUNCOES AUXILIARES
# ===========================================================================
def esc(txt):
    """Escapa texto para HTML."""
    return html.escape("" if txt is None else str(txt), quote=True)


def normalizar(txt):
    """Minusculas, sem acentos e sem pontuacao (para comparar titulos)."""
    t = unicodedata.normalize("NFKD", str(txt).lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def ler_json(caminho, padrao):
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except Exception:
        return padrao


def salvar_json(caminho, dados):
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    Path(caminho).write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def confianca_da_fonte(dominio):
    d = (dominio or "").lower()
    if RE_OFICIAL.search(d):
        return "A"
    if any(d == m or d.endswith("." + m) or d.endswith(m) for m in MIDIA_CONFIAVEL):
        return "B"
    return "C"


def data_br(iso):
    try:
        return dt.datetime.fromisoformat(iso).astimezone(FUSO_BR).strftime("%d/%m %H:%M")
    except Exception:
        return ""


# ===========================================================================
# 6. COLETA - GOOGLE NEWS RSS
# ===========================================================================
def montar_consulta(pais, sub):
    termos = sub[pais["idioma"]]
    if pais["incluir_nome"]:
        termos += f' "{pais["busca_nome"]}"'
    return f"{termos} when:{JANELA_DIAS}d"


def buscar_rss(pais, sub):
    """Retorna a lista de manchetes do Google News para um pais + subtopico."""
    params = {"q": montar_consulta(pais, sub), "hl": pais["hl"], "gl": pais["gl"], "ceid": pais["ceid"]}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (GovSignals LATAM)"})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                conteudo = resp.read()
            break
        except Exception as e:
            print(f"   ⚠️  {pais['cod'].upper()}/{sub['id']}: falha RSS ({e}), tentativa {tentativa + 1}/3")
            time.sleep(3 * (tentativa + 1))
    else:
        return []

    itens = []
    limite = AGORA - dt.timedelta(days=JANELA_DIAS)
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError:
        return []
    for item in raiz.iter("item"):
        titulo = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        fonte_el = item.find("source")
        fonte = (fonte_el.text or "").strip() if fonte_el is not None else ""
        fonte_url = fonte_el.get("url", "") if fonte_el is not None else ""
        if fonte and titulo.endswith(" - " + fonte):
            titulo = titulo[: -len(" - " + fonte)].strip()
        try:
            publicado = parsedate_to_datetime(item.findtext("pubDate")).astimezone(FUSO_BR)
        except Exception:
            publicado = AGORA
        if publicado < limite or not titulo or not link:
            continue
        dominio = urllib.parse.urlparse(fonte_url).netloc.replace("www.", "")
        itens.append({
            "titulo": titulo,
            "link": link,
            "fonte": fonte or dominio or "Não informada",
            "dominio": dominio,
            "publicado": publicado.isoformat(),
            "confianca": confianca_da_fonte(dominio),
            "subtopico": sub["id"],
        })
    return itens


def deduplicar(itens):
    """Remove manchetes repetidas (mesmo link ou titulos muito parecidos).
    Mantem a versao de fonte mais confiavel."""
    ordem = {"A": 0, "B": 1, "C": 2}
    itens = sorted(itens, key=lambda x: ordem[x["confianca"]])
    unicos, titulos = [], []
    for it in itens:
        n = normalizar(it["titulo"])
        if any(difflib.SequenceMatcher(None, n, t).ratio() > 0.82 for t in titulos):
            continue
        titulos.append(n)
        unicos.append(it)
    return unicos


def coletar_pais(pais, historico):
    """Coleta todos os subtopicos de um pais. Cada noticia fica em 1 subtopico."""
    por_sub, ja_usados = {}, []
    for sub in SUBTOPICOS:
        brutos = buscar_rss(pais, sub)
        time.sleep(PAUSA_RSS)
        # remove o que ja apareceu em subtopico anterior do mesmo pais
        filtrados = []
        for it in deduplicar(brutos):
            n = normalizar(it["titulo"])
            if any(difflib.SequenceMatcher(None, n, u).ratio() > 0.82 for u in ja_usados):
                continue
            ja_usados.append(n)
            it["id"] = f"{pais['cod']}-{sub['id']}-{len(filtrados) + 1}"
            primeira_vez = historico.get(it["link"])
            it["novo"] = (primeira_vez is None) or (primeira_vez == HOJE)
            filtrados.append(it)
        # prioridade: confianca A/B primeiro, depois mais recentes
        ordem = {"A": 0, "B": 1, "C": 2}
        filtrados.sort(key=lambda x: (ordem[x["confianca"]], not x["novo"],
                                      -dt.datetime.fromisoformat(x["publicado"]).timestamp()))
        por_sub[sub["id"]] = filtrados[:MAX_CANDIDATOS_IA]
        print(f"   📰 {pais['cod'].upper()} | {sub['nome']}: {len(brutos)} manchetes -> {len(filtrados)} únicas")
    return por_sub


# ===========================================================================
# 7. TRADUCOES FIXAS (PT / EN / ES) - interface sempre nos 3 idiomas
# ===========================================================================
NOMES_PAIS = {
    "br": ("Brasil", "Brazil", "Brasil"),          "mx": ("México", "Mexico", "México"),
    "ar": ("Argentina", "Argentina", "Argentina"), "co": ("Colômbia", "Colombia", "Colombia"),
    "cl": ("Chile", "Chile", "Chile"),             "pe": ("Peru", "Peru", "Perú"),
    "ec": ("Equador", "Ecuador", "Ecuador"),       "uy": ("Uruguai", "Uruguay", "Uruguay"),
    "py": ("Paraguai", "Paraguay", "Paraguay"),    "bo": ("Bolívia", "Bolivia", "Bolivia"),
    "gt": ("Guatemala", "Guatemala", "Guatemala"), "do": ("Rep. Dominicana", "Dominican Rep.", "Rep. Dominicana"),
}
NOMES_SUB = {
    "fiscal":    ("Tributário & Fiscal", "Tax & Fiscal", "Tributario y Fiscal"),
    "comercio":  ("Comércio Exterior & Tarifas", "Foreign Trade & Tariffs", "Comercio Exterior y Aranceles"),
    "agro":      ("Política Agrícola & Crédito Rural", "Agricultural Policy & Rural Credit", "Política Agrícola y Crédito Rural"),
    "industria": ("Indústria, Investimento & Financiamento", "Industry, Investment & Financing", "Industria, Inversión y Financiamiento"),
    "regulacao": ("Regulação, Ambiente & Energia", "Regulation, Environment & Energy", "Regulación, Ambiente y Energía"),
    "politica":  ("Cenário Político & Legislativo", "Political & Legislative Landscape", "Escenario Político y Legislativo"),
}
TXT_FAROL = {
    "critico": ("Crítico", "Critical", "Crítico"), "atencao": ("Atenção", "Watch", "Atención"),
    "positivo": ("Positivo", "Positive", "Positivo"), "sem_movimento": ("Sem movimento", "No activity", "Sin movimiento"),
}
TXT_STATUS = {
    "Anúncio": ("Anúncio", "Announcement", "Anuncio"), "Proposta": ("Proposta", "Proposal", "Propuesta"),
    "Em tramitação": ("Em tramitação", "In legislative process", "En trámite"),
    "Aprovado": ("Aprovado", "Approved", "Aprobado"), "Em vigor": ("Em vigor", "In force", "Vigente"),
    "Contexto": ("Contexto", "Context", "Contexto"),
}
TXT_CONF = {"A": ("Fonte oficial", "Official source", "Fuente oficial"),
            "B": ("Mídia confiável", "Trusted media", "Medio confiable"),
            "C": ("Outra fonte", "Other source", "Otra fuente")}
TXT = {
    "novo": ("Novo", "New", "Nuevo"),
    "fonte": ("Fonte", "Source", "Fuente"),
    "original": ("Título original", "Original headline", "Título original"),
    # Titulo do bloco no rodape de cada noticia
    "impacto_ia": ("Impacto para o agronegócio", "Impact on agribusiness", "Impacto para el agronegocio"),
    "por_que": ("Por que este farol", "Why this signal", "Por qué este semáforo"),
    "radar": ("Radar Institucional", "Institutional Radar", "Radar Institucional"),
    "noticias_sub": ("Notícias por Subtópico", "News by Subtopic", "Noticias por Subtema"),
    "vazio": ("Nenhuma notícia relevante identificada no período.", "No relevant news identified in the period.",
              "No se identificaron noticias relevantes en el período."),
    "visao": ("Visão LATAM", "LATAM Overview", "Visión LATAM"),
    # KPIs
    "k_total": ("Notícias monitoradas", "News monitored", "Noticias monitoreadas"),
    "k_crit": ("Alertas críticos", "Critical alerts", "Alertas críticas"),
    "k_pos": ("Oportunidades", "Opportunities", "Oportunidades"),
    "k_vigor": ("Medidas aprovadas ou em vigor", "Measures approved or in force", "Medidas aprobadas o vigentes"),
    "k_ofic": ("Vindas de fonte oficial", "From official sources", "De fuentes oficiales"),
    # Secoes da Visao LATAM
    "sintese": ("Síntese do Dia", "Daily Briefing", "Síntesis del Día"),
    "ranking": ("Onde Olhar Primeiro", "Where to Look First", "Dónde Mirar Primero"),
    "ranking_dica": ("Índice de pressão = 3 × críticos + 1 × atenção + 1 extra por crítico de fonte oficial. "
                     "Clique no país para abrir.",
                     "Pressure index = 3 × critical + 1 × watch + 1 extra per critical from an official source. "
                     "Click a country to open it.",
                     "Índice de presión = 3 × críticos + 1 × atención + 1 extra por crítico de fuente oficial. "
                     "Haga clic en el país para abrirlo."),
    "temas": ("Temas em Alta na Região", "Trending Topics in the Region", "Temas en Alza en la Región"),
    "etapas": ("Em que Etapa Estão as Medidas", "Where the Measures Stand", "En qué Etapa Están las Medidas"),
    "etapas_dica": ("Etapa identificada pelo título da notícia. Notícias sem etapa clara ficam como Contexto.",
                    "Stage identified from the headline. News without a clear stage are counted as Context.",
                    "Etapa identificada por el título. Noticias sin etapa clara quedan como Contexto."),
    "alertas": ("Alertas Críticos por País", "Critical Alerts by Country", "Alertas Críticas por País"),
    "pais": ("País", "Country", "País"),
    "indice": ("Índice de pressão", "Pressure index", "Índice de presión"),
    "c_crit": ("Críticos", "Critical", "Críticos"),
    "c_aten": ("Atenção", "Watch", "Atención"),
    "c_pos": ("Positivos", "Positive", "Positivos"),
    "tema_principal": ("Tema principal", "Main topic", "Tema principal"),
    "noticias": ("notícias", "news", "noticias"),
    "paises": ("países", "countries", "países"),
    "sem_alertas": ("Nenhum alerta crítico identificado no período.", "No critical alerts identified in the period.",
                    "No se identificaron alertas críticas en el período."),
    "sem_mov": ("Sem movimentações relevantes identificadas no período.", "No relevant developments identified in the period.",
                "No se identificaron movimientos relevantes en el período."),
}
# Texto generico das versoes anteriores. Se vier de um cache antigo, nao e exibido.
REGRA_IMPACTO_ANTIGA = "Classificação automática por palavras-chave (sem IA). Validar no texto original."

MESES = {"pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"],
         "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
         "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]}
IDIOMAS = ("pt", "en", "es")


def t3(trio, cls=""):
    """Texto com as 3 versões. O JavaScript mostra o idioma escolhido.
    'notranslate' impede que o Google Tradutor mexa no que já está traduzido."""
    pt, en, es = trio
    return (f'<span class="i18n notranslate {cls}" data-pt="{esc(pt)}" data-en="{esc(en)}" '
            f'data-es="{esc(es)}">{esc(pt)}</span>')


def trio_de(valor, padrao=""):
    """Converte a resposta da IA ({'pt','en','es'} ou texto simples) em trio."""
    if isinstance(valor, dict):
        pt = str(valor.get("pt") or padrao)
        return (pt, str(valor.get("en") or pt), str(valor.get("es") or pt))
    v = str(valor or padrao)
    return None if not v else (v, v, v)


def lista3(itens):
    """Junta nomes em cada idioma: ['A','B','C'] -> 'A, B e C' / 'A, B and C' / 'A, B y C'."""
    conj = {"pt": " e ", "en": " and ", "es": " y "}
    saida = []
    for i, lang in enumerate(IDIOMAS):
        nomes = [x[i] for x in itens]
        if len(nomes) <= 1:
            saida.append("".join(nomes))
        else:
            saida.append(", ".join(nomes[:-1]) + conj[lang] + nomes[-1])
    return tuple(saida)


# ===========================================================================
# 8. ANALISE - GEMINI (opcional) OU REGRAS
# ===========================================================================
def chamar_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    corpo = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        url, data=json.dumps(corpo).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY})
    for tentativa in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
            texto = dados["candidates"][0]["content"]["parts"][0]["text"]
            texto = re.sub(r"^```(json)?|```$", "", texto.strip()).strip()
            return json.loads(texto)
        except urllib.error.HTTPError as e:
            espera = 20 * (tentativa + 1)
            print(f"   ⚠️  Gemini HTTP {e.code}; nova tentativa em {espera}s")
            if e.code not in (429, 500, 503):
                break
            time.sleep(espera)
        except Exception as e:
            print(f"   ⚠️  Gemini falhou ({e}); nova tentativa")
            time.sleep(10)
    return None


def montar_prompt(pais, por_sub):
    linhas = []
    for sub in SUBTOPICOS:
        for it in por_sub.get(sub["id"], []):
            linhas.append(f'- id={it["id"]} | subtopico={sub["id"]} | fonte={it["fonte"]} '
                          f'(confianca {it["confianca"]}) | data={data_br(it["publicado"])} | titulo="{it["titulo"]}"')
    lista = "\n".join(linhas) if linhas else "(nenhuma manchete encontrada)"
    subs = ", ".join(f'{s["id"]} ({s["nome"]})' for s in SUBTOPICOS)
    return f"""Você é analista sênior de Relações Governamentais e Institucionais de uma fabricante global
de máquinas agrícolas (tratores, colheitadeiras, pulverizadores, plantadeiras), atuando em {pais['nome']}.
Abaixo estão as manchetes públicas das últimas {JANELA_DIAS * 24} horas, já separadas por subtópico.
Subtópicos: {subs}.

MANCHETES:
{lista}

TAREFA:
1. Para cada subtópico, selecione no máximo {MAX_POR_SUBTOPICO} manchetes realmente relevantes para
   Relações Governamentais (governo, legislação, regulação, tributos, comércio, crédito, política).
   Descarte esportes, crimes, celebridades, opinião genérica e notícias de outros países sem efeito em {pais['nome']}.
2. Para cada manchete selecionada, escreva SEMPRE em três idiomas: português do Brasil (pt), inglês (en) e espanhol (es):
   - "titulo": título fiel ao original;
   - "resumo": 1 a 2 frases, usando SOMENTE o que a manchete informa. Não invente números,
     datas, nomes ou desdobramentos. Se a manchete for vaga, diga que os detalhes não constam no título;
   - "impacto": 1 frase sobre o efeito potencial para o agronegócio e máquinas agrícolas
     (ou "Sem impacto direto identificado").
   E também (sem tradução):
   - "status": um de ["Anúncio", "Proposta", "Em tramitação", "Aprovado", "Em vigor", "Contexto"];
   - "farol": "critico" (risco/custo para o setor), "atencao" (acompanhar) ou "positivo" (oportunidade).
3. Para cada subtópico, gere um "radar" com "farol" ("critico", "atencao", "positivo" ou "sem_movimento")
   e "sintese" (1 frase executiva, nos três idiomas). Use "sem_movimento" quando nada relevante foi selecionado.

Responda APENAS com JSON válido neste formato:
{{"radar": [{{"subtopico": "fiscal", "farol": "atencao", "sintese": {{"pt": "...", "en": "...", "es": "..."}}}}],
  "noticias": [{{"id": "...", "titulo": {{"pt": "...", "en": "...", "es": "..."}},
                 "resumo": {{"pt": "...", "en": "...", "es": "..."}},
                 "impacto": {{"pt": "...", "en": "...", "es": "..."}},
                 "status": "...", "farol": "..."}}]}}"""


def achar_termo(titulo_min, palavras):
    """Retorna o primeiro termo encontrado no inicio de uma palavra do titulo (ou None).
    Exige inicio de palavra para evitar falsos positivos (ex.: 'paro' dentro de 'amparo')."""
    for p in palavras:
        if re.search(r"(?<!\w)" + re.escape(p), titulo_min):
            return p
    return None


def classificar_por_regras(titulo):
    """Retorna (farol, status, termo_do_farol, termo_do_status)."""
    t = titulo.lower()
    farol, termo_farol = "atencao", None
    termo = achar_termo(t, PALAVRAS_CRITICO)
    if termo:
        farol, termo_farol = "critico", termo
    else:
        termo = achar_termo(t, PALAVRAS_POSITIVO)
        if termo:
            farol, termo_farol = "positivo", termo
    status, termo_status = "Contexto", None
    for rotulo, palavras in PALAVRAS_STATUS:
        termo = achar_termo(t, palavras)
        if termo:
            status, termo_status = rotulo, termo
            break
    return farol, status, termo_farol, termo_status


def leitura_por_regras(farol, status, termo_farol, termo_status, confianca):
    """Monta, para cada noticia, uma explicacao propria de como ela foi classificada,
    usando somente o que esta no titulo (sem inventar contexto)."""
    if farol == "critico":
        f = (f"Risco: o título cita «{termo_farol}».", f"Risk: the headline mentions «{termo_farol}».",
             f"Riesgo: el título menciona «{termo_farol}».")
    elif farol == "positivo":
        f = (f"Oportunidade: o título cita «{termo_farol}».", f"Opportunity: the headline mentions «{termo_farol}».",
             f"Oportunidad: el título menciona «{termo_farol}».")
    else:
        f = ("Sem termo de risco ou oportunidade no título; fica em acompanhamento.",
             "No risk or opportunity term in the headline; kept on watch.",
             "Sin término de riesgo u oportunidad en el título; queda en seguimiento.")
    st = TXT_STATUS[status]
    if termo_status:
        s = (f"Etapa {st[0]} (termo «{termo_status}»).", f"Stage {st[1]} (term «{termo_status}»).",
             f"Etapa {st[2]} (término «{termo_status}»).")
    else:
        s = ("Etapa não indicada no título.", "Stage not stated in the headline.", "Etapa no indicada en el título.")
    c = {"A": ("Fonte oficial: peso alto.", "Official source: high weight.", "Fuente oficial: peso alto."),
         "B": ("Mídia confiável.", "Trusted media.", "Medio confiable."),
         "C": ("Fonte não verificada: confirmar antes de agir.", "Unverified source: confirm before acting.",
               "Fuente no verificada: confirmar antes de actuar.")}[confianca]
    return [f"{f[i]} {s[i]} {c[i]}" for i in range(3)]


def analisar_por_regras(por_sub):
    """Plano B sem IA: pega as melhores manchetes e classifica por palavras-chave."""
    noticias, radar = [], []
    peso = {"critico": 3, "atencao": 2, "positivo": 1}
    for sub in SUBTOPICOS:
        escolhidas = por_sub.get(sub["id"], [])[:MAX_POR_SUBTOPICO]
        pior = None
        cont = {"critico": 0, "atencao": 0, "positivo": 0}
        for it in escolhidas:
            farol, status, termo_f, termo_s = classificar_por_regras(it["titulo"])
            cont[farol] += 1
            noticias.append({**it, "status": status, "farol": farol, "termo": termo_f,
                             "leitura_i18n": leitura_por_regras(farol, status, termo_f, termo_s, it["confianca"])})
            if pior is None or peso[farol] > peso[pior]:
                pior = farol
        n = len(escolhidas)
        if n:
            sintese = (f"{n} notícia(s): {cont['critico']} crítica(s), {cont['atencao']} em atenção, {cont['positivo']} positiva(s).",
                       f"{n} news item(s): {cont['critico']} critical, {cont['atencao']} on watch, {cont['positivo']} positive.",
                       f"{n} noticia(s): {cont['critico']} crítica(s), {cont['atencao']} en atención, {cont['positivo']} positiva(s).")
        else:
            sintese = TXT["sem_mov"]
        radar.append({"subtopico": sub["id"], "farol": pior or "sem_movimento", "sintese_i18n": list(sintese)})
    return {"radar": radar, "noticias": noticias, "origem": "regras"}


def analisar_pais(pais, por_sub):
    if not GEMINI_API_KEY:
        return analisar_por_regras(por_sub)
    resposta = chamar_gemini(montar_prompt(pais, por_sub))
    if not isinstance(resposta, dict) or "noticias" not in resposta:
        print(f"   ⚠️  {pais['cod'].upper()}: IA indisponível, usando regras.")
        return analisar_por_regras(por_sub)

    # link, fonte e data nunca vêm da IA: só os textos
    originais = {it["id"]: it for lst in por_sub.values() for it in lst}
    noticias, contagem = [], {}
    for n in resposta.get("noticias", []):
        base = originais.get(str(n.get("id")))
        if not base:
            continue  # descarta qualquer id inventado
        if contagem.get(base["subtopico"], 0) >= MAX_POR_SUBTOPICO:
            continue
        contagem[base["subtopico"]] = contagem.get(base["subtopico"], 0) + 1
        farol = n.get("farol") if n.get("farol") in ("critico", "atencao", "positivo") else "atencao"
        status = n.get("status") if n.get("status") in TXT_STATUS else "Contexto"
        titulo = trio_de(n.get("titulo"), base["titulo"])
        resumo = trio_de(n.get("resumo"))
        impacto = trio_de(n.get("impacto"))
        noticias.append({**base, "status": status, "farol": farol,
                         "titulo_i18n": list(titulo) if titulo else None,
                         "resumo_i18n": list(resumo) if resumo else None,
                         "impacto_i18n": list(impacto) if impacto else None})

    radar_ia = {r.get("subtopico"): r for r in resposta.get("radar", []) if isinstance(r, dict)}
    radar = []
    for sub in SUBTOPICOS:
        r = radar_ia.get(sub["id"], {})
        farol = r.get("farol") if r.get("farol") in TXT_FAROL else "atencao"
        sintese = trio_de(r.get("sintese"), "—")
        if not contagem.get(sub["id"]):
            farol, sintese = "sem_movimento", TXT["sem_mov"]
        radar.append({"subtopico": sub["id"], "farol": farol, "sintese_i18n": list(sintese)})
    return {"radar": radar, "noticias": noticias, "origem": "ia"}


# ===========================================================================
# 9. GERACAO DO HTML
# ===========================================================================
FAROL = {"critico": "farol-critical", "atencao": "farol-warning", "positivo": "farol-positive", "sem_movimento": "farol-neutral"}
CLASSE_CARD = {"critico": "tendencia-negativa", "positivo": "tendencia-positiva",
               "atencao": "tendencia-neutra", "sem_movimento": "tendencia-vazia"}
ETAPAS = ["Proposta", "Em tramitação", "Aprovado", "Em vigor"]


def farol_html(chave):
    chave = chave if chave in FAROL else "atencao"
    return f'<span class="farol {FAROL[chave]}"><span class="farol-dot"></span>{t3(TXT_FAROL[chave])}</span>'


def texto_livre(trio_salvo, original, idioma_origem):
    """Usa o trio (IA). Sem trio, deixa o texto original para o Google Tradutor traduzir."""
    if trio_salvo:
        return t3(tuple(trio_salvo))
    return f'<span lang="{idioma_origem}">{esc(original)}</span>'


def html_radar(radar):
    cards = []
    for r in radar:
        sub = SUB_POR_ID[r["subtopico"]]
        sintese = r.get("sintese_i18n") or [r.get("sintese", "")] * 3
        cards.append(f"""
        <div class="analysis-card {CLASSE_CARD.get(r['farol'], 'tendencia-neutra')}">
          <div class="analysis-header">
            <div class="analysis-icon">{sub['icone']}</div>
            <h3 class="analysis-card-title">{t3(NOMES_SUB[sub['id']])}</h3>
            {farol_html(r['farol'])}
          </div>
          <p class="analysis-text">{t3(tuple(sintese))}</p>
        </div>""")
    return '<div class="analysis-grid">' + "".join(cards) + "</div>"


def bloco_rodape_noticia(n):
    """Com IA: impacto para o agronegocio. Sem IA: explicacao propria da classificacao."""
    impacto = n.get("impacto_i18n")
    if impacto and impacto[0] != REGRA_IMPACTO_ANTIGA:
        titulo, texto = TXT["impacto_ia"], impacto
    elif n.get("leitura_i18n"):
        titulo, texto = TXT["por_que"], n["leitura_i18n"]
    else:
        return ""
    return f"""
        <div class="machinery-analysis">
          <div class="analysis-title">{t3(titulo)}</div>
          <div class="m-desc">{t3(tuple(texto))}</div>
        </div>"""


def html_noticia(n, idioma_origem):
    sub = SUB_POR_ID[n["subtopico"]]
    titulo = texto_livre(n.get("titulo_i18n"), n["titulo"], idioma_origem)
    original = ""
    if n.get("titulo_i18n"):
        original = (f'<p class="news-original">{t3(TXT["original"])}: '
                    f'<span class="notranslate">{esc(n["titulo"])}</span></p>')
    resumo = f'<p>{t3(tuple(n["resumo_i18n"]))}</p>' if n.get("resumo_i18n") else ""
    novo = f'<span class="tag tag-new">{t3(TXT["novo"])}</span>' if n.get("novo") else ""
    status = TXT_STATUS.get(n.get("status"), (n.get("status", ""),) * 3)
    return f"""
    <div class="news-block" data-novo="{'1' if n.get('novo') else '0'}" data-farol="{esc(n['farol'])}">
      <div class="news-header farol-border-{esc(n['farol'])}">
        <h3 class="news-title"><span class="news-topic-icon">{sub['icone']}</span>{titulo}</h3>
        {farol_html(n['farol'])}
      </div>
      <div class="news-body">
        <div class="tags">{novo}<span class="tag tag-status">{t3(status)}</span>
          <span class="tag tag-conf-{esc(n['confianca'])}">{esc(n['confianca'])} · {t3(TXT_CONF[n['confianca']])}</span></div>
        {resumo}{original}
        <p class="news-source">{t3(TXT['fonte'])}: <a class="notranslate" href="{esc(n['link'])}" target="_blank"
          rel="noopener noreferrer">{esc(n['fonte'])}</a> · {esc(data_br(n['publicado']))}</p>
      </div>{bloco_rodape_noticia(n)}
    </div>"""


def html_pais(pais, analise):
    partes = [f'<h2 class="country-title">{pais["bandeira"]} {t3(NOMES_PAIS[pais["cod"]])}</h2>',
              f'<h2 class="section-title">{t3(TXT["radar"])}</h2>', html_radar(analise["radar"]),
              f'<h2 class="section-title">{t3(TXT["noticias_sub"])}</h2>']
    tem_noticia = False
    for sub in SUBTOPICOS:
        lista = [n for n in analise["noticias"] if n["subtopico"] == sub["id"]]
        if not lista:
            continue
        tem_noticia = True
        partes.append(f'<h3 class="sub-title">{sub["icone"]} {t3(NOMES_SUB[sub["id"]])} <span class="sub-count">{len(lista)}</span></h3>')
        partes.append('<div class="news-grid">' + "".join(html_noticia(n, pais["idioma"]) for n in lista) + "</div>")
    if not tem_noticia:
        partes.append(f'<p class="empty">{t3(TXT["vazio"])}</p>')
    return f'<div id="{pais["cod"]}" class="tab-content">' + "".join(partes) + "</div>"


# ---------------------------------------------------------------------------
# Visao LATAM: indicadores calculados somente a partir das noticias do dia
# ---------------------------------------------------------------------------
def estatisticas(resultado):
    """Calcula, por pais e por subtopico, tudo que a Visao LATAM usa."""
    por_pais = []
    for p in PAISES:
        nots = resultado[p["cod"]]["noticias"]
        crit = [n for n in nots if n["farol"] == "critico"]
        aten = sum(1 for n in nots if n["farol"] == "atencao")
        pos = sum(1 for n in nots if n["farol"] == "positivo")
        bonus = sum(1 for n in crit if n["confianca"] == "A")
        indice = 3 * len(crit) + aten + bonus
        # tema principal: subtopico com mais criticos; desempate por total de noticias
        tema = None
        if nots:
            tema = max(SUBTOPICOS, key=lambda s: (sum(1 for n in crit if n["subtopico"] == s["id"]),
                                                  sum(1 for n in nots if n["subtopico"] == s["id"])))["id"]
        por_pais.append({"pais": p, "total": len(nots), "crit": len(crit), "aten": aten, "pos": pos,
                         "indice": indice, "tema": tema})
    por_pais.sort(key=lambda x: (-x["indice"], -x["crit"], -x["total"]))

    por_sub = []
    for s in SUBTOPICOS:
        itens = [(p, n) for p in PAISES for n in resultado[p["cod"]]["noticias"] if n["subtopico"] == s["id"]]
        crit_paises = sorted({p["cod"] for p, n in itens if n["farol"] == "critico"},
                             key=lambda c: [x["cod"] for x in PAISES].index(c))
        por_sub.append({"sub": s, "total": len(itens), "crit": sum(1 for _, n in itens if n["farol"] == "critico"),
                        "pos": sum(1 for _, n in itens if n["farol"] == "positivo"),
                        "paises": len({p["cod"] for p, _ in itens}), "crit_paises": crit_paises})
    por_sub.sort(key=lambda x: (-x["crit"], -x["total"]))
    return por_pais, por_sub


def frases_sintese(todas, por_pais, por_sub):
    """Gera de 3 a 4 frases objetivas, nos 3 idiomas, so com contagens reais."""
    frases = []
    total_crit = sum(1 for n, _ in todas if n["farol"] == "critico")
    if not todas:
        return [TXT["sem_mov"]]

    # 1) Pais com maior pressao
    topo = por_pais[0]
    if topo["crit"]:
        nome = NOMES_PAIS[topo["pais"]["cod"]]
        tema = NOMES_SUB[topo["tema"]]
        frases.append((f"{nome[0]} lidera o índice de pressão: {topo['crit']} dos {total_crit} alertas críticos da região, principalmente em {tema[0]}.",
                       f"{nome[1]} tops the pressure index: {topo['crit']} of the region's {total_crit} critical alerts, mainly in {tema[1]}.",
                       f"{nome[2]} lidera el índice de presión: {topo['crit']} de las {total_crit} alertas críticas de la región, principalmente en {tema[2]}."))
    else:
        frases.append(("Nenhum alerta crítico na região no período; o radar está em acompanhamento.",
                       "No critical alerts in the region in the period; the radar is on watch.",
                       "Ninguna alerta crítica en la región en el período; el radar está en seguimiento."))

    # 2) Tema que mais aparece com risco em varios paises
    s = por_sub[0]
    if s["crit"]:
        nomes = lista3([NOMES_PAIS[c] for c in s["crit_paises"][:4]])
        ns = NOMES_SUB[s["sub"]["id"]]
        extra = len(s["crit_paises"]) - 4
        mais = ((f" e mais {extra}", f" and {extra} more", f" y {extra} más") if extra > 0 else ("", "", ""))
        frases.append((f"{ns[0]} é o tema mais sensível: {s['crit']} alerta(s) crítico(s) em {nomes[0]}{mais[0]}.",
                       f"{ns[1]} is the most sensitive topic: {s['crit']} critical alert(s) in {nomes[1]}{mais[1]}.",
                       f"{ns[2]} es el tema más sensible: {s['crit']} alerta(s) crítica(s) en {nomes[2]}{mais[2]}."))

    # 3) Medidas ja aprovadas ou em vigor (efeito pratico mais proximo)
    vigor = [(n, p) for n, p in todas if n.get("status") in ("Aprovado", "Em vigor")]
    if vigor:
        paises_v = []
        for n, cod in vigor:
            if cod not in paises_v:
                paises_v.append(cod)
        nomes = lista3([NOMES_PAIS[c] for c in paises_v[:4]])
        extra = len(paises_v) - 4
        mais = ((f" e mais {extra} país(es)", f" and {extra} more", f" y {extra} más") if extra > 0 else ("", "", ""))
        frases.append((f"{len(vigor)} medida(s) já aprovada(s) ou em vigor, com efeito prático mais próximo: {nomes[0]}{mais[0]}.",
                       f"{len(vigor)} measure(s) already approved or in force, with nearer practical effect: {nomes[1]}{mais[1]}.",
                       f"{len(vigor)} medida(s) ya aprobada(s) o vigente(s), con efecto práctico más cercano: {nomes[2]}{mais[2]}."))

    # 4) Oportunidades
    pos = [x for x in por_pais if x["pos"]]
    if pos:
        melhor = max(pos, key=lambda x: x["pos"])
        nome = NOMES_PAIS[melhor["pais"]["cod"]]
        total_pos = sum(x["pos"] for x in pos)
        frases.append((f"{total_pos} sinal(is) positivo(s) na região; {nome[0]} lidera com {melhor['pos']}.",
                       f"{total_pos} positive signal(s) in the region; {nome[1]} leads with {melhor['pos']}.",
                       f"{total_pos} señal(es) positiva(s) en la región; {nome[2]} lidera con {melhor['pos']}."))
    return frases


def html_visao_geral(resultado, primeira_coleta=False):
    todas = [(n, p["cod"]) for p in PAISES for n in resultado[p["cod"]]["noticias"]]
    por_pais, por_sub = estatisticas(resultado)
    total = len(todas)
    novas = sum(1 for n, _ in todas if n.get("novo"))
    crit = sum(1 for n, _ in todas if n["farol"] == "critico")
    pos = sum(1 for n, _ in todas if n["farol"] == "positivo")
    vigor = sum(1 for n, _ in todas if n.get("status") in ("Aprovado", "Em vigor"))
    ofic = sum(1 for n, _ in todas if n["confianca"] == "A")
    paises_crit = sum(1 for x in por_pais if x["crit"])
    pct = round(100 * ofic / total) if total else 0

    if primeira_coleta:
        sub_total = ("1ª coleta: todas são novas", "1st run: all are new", "1ª recolección: todas son nuevas")
    else:
        sub_total = (f"{novas} novas desde ontem", f"{novas} new since yesterday", f"{novas} nuevas desde ayer")
    kpis = [
        (total, TXT["k_total"], sub_total, ""),
        (crit, TXT["k_crit"], (f"em {paises_crit} de {len(PAISES)} países", f"in {paises_crit} of {len(PAISES)} countries",
                               f"en {paises_crit} de {len(PAISES)} países"), "kpi-crit"),
        (pos, TXT["k_pos"], ("sinais positivos para o setor", "positive signals for the sector",
                             "señales positivas para el sector"), "kpi-pos"),
        (vigor, TXT["k_vigor"], ("efeito prático mais próximo", "nearer practical effect", "efecto práctico más cercano"), ""),
        (f"{pct}%", TXT["k_ofic"], (f"{ofic} de {total} notícias", f"{ofic} of {total} news", f"{ofic} de {total} noticias"), ""),
    ]
    kpi_html = "".join(f'<div class="kpi {cls}"><div class="kpi-val">{v}</div><div class="kpi-lbl">{t3(lbl)}</div>'
                       f'<div class="kpi-sub">{t3(sub)}</div></div>' for v, lbl, sub, cls in kpis)

    # Sintese do dia
    sintese = "".join(f"<li>{t3(f)}</li>" for f in frases_sintese(todas, por_pais, por_sub))

    # Ranking de paises
    maior = max([x["indice"] for x in por_pais] + [1])
    linhas = []
    for i, x in enumerate(por_pais, 1):
        p = x["pais"]
        largura = round(100 * x["indice"] / maior)
        tema = (f'{SUB_POR_ID[x["tema"]]["icone"]} {t3(NOMES_SUB[x["tema"]])}' if x["tema"] else "–")
        linhas.append(
            f'<tr onclick="openTab(\'{p["cod"]}\')"><td class="rk-pos">{i}</td>'
            f'<td class="rk-pais">{p["bandeira"]} {t3(NOMES_PAIS[p["cod"]])}</td>'
            f'<td class="rk-barra"><div class="barra"><span style="width:{largura}%"></span></div><b>{x["indice"]}</b></td>'
            f'<td class="rk-n n-crit">{x["crit"] or "–"}</td><td class="rk-n n-aten">{x["aten"] or "–"}</td>'
            f'<td class="rk-n n-pos">{x["pos"] or "–"}</td><td class="rk-tema">{tema}</td></tr>')
    ranking = (f'<div class="table-wrap"><table class="rank"><thead><tr><th>#</th><th>{t3(TXT["pais"])}</th>'
               f'<th>{t3(TXT["indice"])}</th><th>{t3(TXT["c_crit"])}</th><th>{t3(TXT["c_aten"])}</th>'
               f'<th>{t3(TXT["c_pos"])}</th><th>{t3(TXT["tema_principal"])}</th></tr></thead>'
               f'<tbody>{"".join(linhas)}</tbody></table></div>')

    # Temas em alta
    maior_t = max([s["total"] for s in por_sub] + [1])
    temas = []
    for s in por_sub:
        sid = s["sub"]["id"]
        w_crit = round(100 * s["crit"] / maior_t)
        w_pos = round(100 * s["pos"] / maior_t)
        w_rest = round(100 * (s["total"] - s["crit"] - s["pos"]) / maior_t)
        bandeiras = " ".join(PAIS_POR_COD[c]["bandeira"] for c in s["crit_paises"])
        temas.append(f"""
        <div class="tema">
          <div class="tema-top"><span>{s['sub']['icone']} {t3(NOMES_SUB[sid])}</span>
            <span class="tema-num">{s['total']} {t3(TXT['noticias'])} · {s['paises']} {t3(TXT['paises'])}</span></div>
          <div class="pilha"><span class="p-crit" style="width:{w_crit}%"></span><span class="p-aten" style="width:{w_rest}%"></span><span class="p-pos" style="width:{w_pos}%"></span></div>
          <div class="tema-crit">{farol_html('critico') if s['crit'] else ''} {('<b>' + str(s['crit']) + '</b> ' + bandeiras) if s['crit'] else ''}</div>
        </div>""")

    # Etapas das medidas
    etapas = []
    for i, e in enumerate(ETAPAS):
        itens = [(n, c) for n, c in todas if n.get("status") == e]
        bandeiras = []
        for _, c in itens:
            b = PAIS_POR_COD[c]["bandeira"]
            if b not in bandeiras:
                bandeiras.append(b)
        seta = '<div class="etapa-seta">➜</div>' if i < len(ETAPAS) - 1 else ""
        etapas.append(f'<div class="etapa"><div class="etapa-num">{len(itens)}</div>'
                      f'<div class="etapa-lbl">{t3(TXT_STATUS[e])}</div>'
                      f'<div class="etapa-band">{" ".join(bandeiras) or "–"}</div></div>{seta}')
    contexto = sum(1 for n, _ in todas if n.get("status") not in ETAPAS)
    etapas_html = (f'<div class="etapas">{"".join(etapas)}</div>'
                   f'<p class="hint">{t3(TXT["etapas_dica"])} {t3(TXT_STATUS["Contexto"])}: {contexto}</p>')

    # Alertas criticos agrupados por pais (lista compacta)
    grupos = []
    for x in por_pais:
        p = x["pais"]
        crits = [n for n in resultado[p["cod"]]["noticias"] if n["farol"] == "critico"]
        if not crits:
            continue
        crits.sort(key=lambda n: (n["confianca"], not n.get("novo")))
        itens = []
        for n in crits:
            sub = SUB_POR_ID[n["subtopico"]]
            novo = f'<span class="tag tag-new">{t3(TXT["novo"])}</span>' if n.get("novo") else ""
            st = TXT_STATUS.get(n.get("status"), (n.get("status", ""),) * 3)
            itens.append(
                f'<li><span class="al-ico">{sub["icone"]}</span><div class="al-txt">'
                f'<a href="{esc(n["link"])}" target="_blank" rel="noopener noreferrer">'
                f'{texto_livre(n.get("titulo_i18n"), n["titulo"], p["idioma"])}</a>'
                f'<div class="tags">{novo}<span class="tag tag-status">{t3(st)}</span>'
                f'<span class="tag tag-conf-{esc(n["confianca"])}">{esc(n["confianca"])} · {t3(TXT_CONF[n["confianca"]])}</span>'
                f'<span class="al-fonte notranslate">{esc(n["fonte"])} · {esc(data_br(n["publicado"]))}</span></div></div></li>')
        grupos.append(f'<div class="al-grupo"><div class="al-pais" onclick="openTab(\'{p["cod"]}\')">'
                      f'{p["bandeira"]} {t3(NOMES_PAIS[p["cod"]])} <span class="sub-count">{len(crits)}</span></div>'
                      f'<ul>{"".join(itens)}</ul></div>')
    alertas = ('<div class="al-wrap">' + "".join(grupos) + "</div>") if grupos else f'<p class="empty">{t3(TXT["sem_alertas"])}</p>'

    return f"""
    <div id="geral" class="tab-content active">
      <h2 class="country-title">{t3(TXT["visao"])}</h2>
      <div class="kpis">{kpi_html}</div>
      <div class="briefing"><div class="briefing-title">📌 {t3(TXT["sintese"])}</div><ul>{sintese}</ul></div>
      <div class="duas-col">
        <div>
          <h2 class="section-title">{t3(TXT["ranking"])}</h2>
          <p class="hint">{t3(TXT["ranking_dica"])}</p>
          {ranking}
        </div>
        <div>
          <h2 class="section-title">{t3(TXT["temas"])}</h2>
          <div class="temas">{"".join(temas)}</div>
        </div>
      </div>
      <h2 class="section-title">{t3(TXT["etapas"])}</h2>
      {etapas_html}
      <h2 class="section-title">{t3(TXT["alertas"])}</h2>
      {alertas}
    </div>"""


def gerar_html(resultado, modo, primeira_coleta=False):
    d = AGORA
    data_txt = t3((f"{d.day:02d} de {MESES['pt'][d.month - 1]} de {d.year}",
                   f"{MESES['en'][d.month - 1]} {d.day:02d}, {d.year}",
                   f"{d.day:02d} de {MESES['es'][d.month - 1]} de {d.year}"))
    h = JANELA_DIAS * 24
    modo_txt = {"ia": ("Análise com IA (Gemini) nos 3 idiomas", "AI analysis (Gemini) in 3 languages",
                       "Análisis con IA (Gemini) en 3 idiomas"),
                "regras": ("Classificação automática por palavras-chave do título",
                           "Automatic classification by headline keywords",
                           "Clasificación automática por palabras clave del título")}[modo]
    banner = t3((f"Monitoramento diário de 12 mercados latino-americanos · 6 subtópicos de Relações Governamentais · "
                 f"Janela de {h}h · Modo: {modo_txt[0]} · Confiança: A = fonte oficial · B = mídia confiável · "
                 f"C = outra fonte. Confirme itens críticos no texto original ou no documento oficial.",
                 f"Daily monitoring of 12 Latin American markets · 6 Government Relations subtopics · "
                 f"{h}h window · Mode: {modo_txt[1]} · Confidence: A = official source · B = trusted media · "
                 f"C = other source. Confirm critical items against the original text or official document.",
                 f"Monitoreo diario de 12 mercados latinoamericanos · 6 subtemas de Relaciones Gubernamentales · "
                 f"Ventana de {h}h · Modo: {modo_txt[2]} · Confianza: A = fuente oficial · B = medio confiable · "
                 f"C = otra fuente. Confirme los temas críticos en el texto original o en el documento oficial."))
    gerado = AGORA.strftime("%d/%m/%Y %H:%M")
    atualizado = t3((f"Atualizado em {gerado} (Brasília) · Fontes públicas via Google News",
                     f"Updated on {gerado} (Brasília time) · Public sources via Google News",
                     f"Actualizado el {gerado} (Brasilia) · Fuentes públicas vía Google News"))
    abas = [f'<button class="tab-btn active" data-tab="geral" onclick="openTab(\'geral\')">🌎 {t3(TXT["visao"])}</button>']
    abas += [f'<button class="tab-btn" data-tab="{p["cod"]}" onclick="openTab(\'{p["cod"]}\')">'
             f'{p["bandeira"]} {t3(NOMES_PAIS[p["cod"]])}</button>' for p in PAISES]
    conteudo = html_visao_geral(resultado, primeira_coleta) + "".join(html_pais(p, resultado[p["cod"]]) for p in PAISES)
    modelo = TEMPLATE.read_text(encoding="utf-8")
    return (modelo.replace("{{DATA_RELATORIO}}", data_txt)
                  .replace("{{BANNER}}", banner)
                  .replace("{{ABAS}}", "".join(abas))
                  .replace("{{CONTEUDO}}", conteudo)
                  .replace("{{ATUALIZADO}}", atualizado))


# ===========================================================================
# 10. EXECUCAO PRINCIPAL
# ===========================================================================
def main():
    print("=" * 70)
    print(f"🏛️  GOV SIGNALS LATAM | {AGORA:%d/%m/%Y %H:%M} | janela {JANELA_DIAS * 24}h")
    print(f"🤖 IA: {'Gemini ' + GEMINI_MODEL if GEMINI_API_KEY else 'desligada (modo regras)'} | forçar: {FORCAR}")
    print("=" * 70)

    historico = ler_json(ARQ_HISTORICO, {})
    primeira_coleta = not historico
    ultimo = ler_json(ARQ_ULTIMO, {})
    cache_valido = (not FORCAR) and ultimo.get("data") == HOJE
    resultado, origens = {}, {}

    for i, pais in enumerate(PAISES):
        antigo = ultimo.get("paises", {}).get(pais["cod"]) if cache_valido else None
        if antigo and antigo.get("origem") == "ia" and all("sintese_i18n" in r for r in antigo.get("radar", [])):
            print(f"♻️  {pais['cod'].upper()}: cache de hoje reaproveitado.")
            resultado[pais["cod"]] = antigo
            origens[pais["cod"]] = "cache"
            continue
        print(f"🔎 {pais['bandeira']} {pais['nome']}")
        por_sub = coletar_pais(pais, historico)
        analise = analisar_pais(pais, por_sub)
        resultado[pais["cod"]] = analise
        origens[pais["cod"]] = analise["origem"]
        if analise["origem"] == "ia" and i < len(PAISES) - 1:
            time.sleep(PAUSA_IA)

    # Se o pais veio vazio hoje (ex.: falha de rede), mantem a ultima versao boa
    for pais in PAISES:
        atual = resultado[pais["cod"]]
        anterior = ultimo.get("paises", {}).get(pais["cod"])
        if not atual["noticias"] and anterior and anterior.get("noticias"):
            print(f"🛟 {pais['cod'].upper()}: sem notícias hoje; mantendo a última versão salva.")
            resultado[pais["cod"]] = anterior
            origens[pais["cod"]] = "anterior"

    # Atualiza o historico de links (para marcar NOVO amanha)
    for a in resultado.values():
        for n in a["noticias"]:
            historico.setdefault(n["link"], HOJE)
    corte = (AGORA.date() - dt.timedelta(days=DIAS_HISTORICO)).isoformat()
    historico = {k: v for k, v in historico.items() if v >= corte}

    modo = "ia" if any(o in ("ia", "cache") for o in origens.values()) else "regras"
    SAIDA_HTML.write_text(gerar_html(resultado, modo, primeira_coleta), encoding="utf-8")
    pacote = {"data": HOJE, "gerado_em": AGORA.isoformat(), "paises": resultado}
    salvar_json(ARQ_ULTIMO, pacote)
    salvar_json(PASTA_ARQUIVO / f"{HOJE}.json", pacote)
    salvar_json(ARQ_HISTORICO, historico)

    print("\n📋 RESUMO")
    print(f"{'País':<18}{'Notícias':>9}{'Críticas':>10}{'Origem':>11}")
    for p in PAISES:
        a = resultado[p["cod"]]
        crit = sum(1 for n in a["noticias"] if n["farol"] == "critico")
        print(f"{p['nome']:<18}{len(a['noticias']):>9}{crit:>10}{origens[p['cod']]:>11}")
    print(f"\n✅ Dashboard gerado: {SAIDA_HTML.name}")


if __name__ == "__main__":
    main()
