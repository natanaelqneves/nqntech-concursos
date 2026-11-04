"""Fonte Diário Oficial do Estado de São Paulo: API pública de busca do próprio site (doe.sp.gov.br).

Observado em 04/11/2026 (sondagem `captura-diarios`, a partir do GitHub Actions; robots.txt inexistente, 404):
- busca: GET do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications?Terms[0]=...&FromDate&ToDate
  → items[{id, date, title, slug, excerpt, hierarchy}];
- publicação: GET .../v2/publications/{slug} → {title, date, journal, secondLevelSectionName, publicationType,
  content (HTML com o texto integral)}.

Só publicações do tipo edital que falam em concurso/processo seletivo e em abertura de inscrições viram sinal;
convocações, homologações, resultados, contratos e retificações ficam de fora. Não há PDF: o texto da
publicação vai junto no sinal (`arquivos[].texto`) e a vinculação o grava direto no documento.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

from coletor.fontes.base import ResultadoDescoberta, SinalDescoberta
from coletor.http_cliente import ClienteHttp, ErroHttp
from coletor.texto import colapsar_espacos, normalizar, titulo_portugues

log = logging.getLogger(__name__)

API = "https://do-api-web-search.doe.sp.gov.br/v2"
PAGINA = "https://doe.sp.gov.br/{slug}"
TERMOS = ("edital de abertura", "abertura de inscrições", "concurso público")
DIAS = 7  # janela de busca; o mesmo edital não duplica (o sinal é pela URL)
MAX_PAGINAS = 5
TAMANHO_PAGINA = 50
MAX_TEXTO = 400_000

_CONCURSO = re.compile(r"concurso publico|processo seletivo")
_ABERTURA = re.compile(r"abertura|estarao abertas|acham-se abertas|ficam abertas|encontram-se abertas|inscricoes")
_DESCARTAR = re.compile(
    r"convoca|homologa|resultado|classifica|gabarito|contrat|prorroga|retifica|nomea|resumo de|extrato|"
    r"cancelamento|revoga|suspens|aprovados|lista de|recurso"
)
_SLUG = re.compile(r"^[a-z0-9/_-]{10,300}$")


def html_para_texto(conteudo: str) -> str:
    conteudo = re.sub(r"(?i)<\s*(br|/p|/div|/tr|/li|/h\d)\s*/?>", "\n", conteudo)
    conteudo = re.sub(r"<[^>]+>", " ", conteudo)
    linhas = (colapsar_espacos(html.unescape(linha)) for linha in conteudo.splitlines())
    return "\n".join(linha for linha in linhas if linha)


def interessa(item: dict[str, Any]) -> bool:
    """Pela listagem: edital de concurso/seleção com abertura de inscrições (o texto completo é triado depois)."""
    titulo = normalizar(str(item.get("title") or ""))
    trecho = normalizar(str(item.get("excerpt") or ""))
    if _DESCARTAR.search(titulo):
        return False
    return "edital" in titulo and bool(_CONCURSO.search(trecho + " " + titulo)) and bool(_ABERTURA.search(trecho))


def parse_publicacao(dados: dict[str, Any]) -> SinalDescoberta | None:
    slug = str(dados.get("slug") or "")
    texto = html_para_texto(str(dados.get("content") or ""))
    normal = normalizar(texto[:6000])
    if not _SLUG.match(slug) or not _CONCURSO.search(normal) or not _ABERTURA.search(normal):
        return None
    orgao = colapsar_espacos(str(dados.get("secondLevelSectionName") or ""))
    titulo_publicacao = colapsar_espacos(str(dados.get("title") or "Edital"))
    titulo = titulo_portugues(orgao) if orgao else titulo_publicacao
    try:
        dia = date.fromisoformat(str(dados.get("date") or "")[:10])
    except ValueError:
        dia = None
    url = PAGINA.format(slug=slug)
    return SinalDescoberta(
        titulo=titulo,
        url=url,
        data_publicacao=dia,
        payload={
            "titulo": titulo,
            "situacao_site": "DIARIO_OFICIAL",
            "descricao": f"{titulo_publicacao} (Diário Oficial do Estado de São Paulo)",
            "link_inscricao": None,
            "arquivos": [{
                "titulo": titulo_publicacao,
                "url": f"{API}/publications/{quote(slug, safe='/')}",
                "data": dia.isoformat() if dia else None,
                "pdf": True,  # entra como documento; o texto já vem pronto
                "tipo": "EDITAL",
                "texto": texto[:MAX_TEXTO],
            }],
        },
    )  # fmt: skip


class FonteDOESP:
    nome = "doe-sp"
    dominios = frozenset({"do-api-web-search.doe.sp.gov.br"})

    def __init__(self, dias: int = DIAS, hoje: Callable[[], date] = date.today) -> None:
        self._dias = dias
        self._hoje = hoje

    def descobrir(self, http: ClienteHttp, pular: frozenset[str] = frozenset()) -> ResultadoDescoberta:
        fim = self._hoje()
        inicio = fim - timedelta(days=self._dias)
        candidatos: dict[str, dict[str, Any]] = {}
        for termo in TERMOS:  # a primeira página de cada termo é obrigatória: falhou, a fonte falha
            for pagina in range(1, MAX_PAGINAS + 1):
                url = (
                    f"{API}/advanced-search/publications?Terms%5B0%5D={quote(termo)}&FromDate={inicio}"
                    f"&ToDate={fim}&PageNumber={pagina}&PageSize={TAMANHO_PAGINA}"
                    "&periodStartingDate=personalized"
                )
                dados = _json(http, url)
                itens = dados.get("items") or []
                for item in itens:
                    if isinstance(item, dict) and item.get("slug") and interessa(item):
                        candidatos.setdefault(str(item["slug"]), item)
                if pagina >= int(dados.get("totalPages") or 0) or not itens:
                    break
        log.info("DOE-SP: %d editais candidatos em %s a %s", len(candidatos), inicio, fim)
        sinais: list[SinalDescoberta] = []
        falhas: list[str] = []
        for slug in candidatos:
            if PAGINA.format(slug=slug) in pular or not _SLUG.match(slug):
                continue
            try:
                sinal = parse_publicacao(_json(http, f"{API}/publications/{quote(slug, safe='/')}"))
            except ErroHttp as erro:
                falhas.append(f"{slug}: {erro}")
                continue
            if sinal is not None:
                sinais.append(sinal)
        return ResultadoDescoberta(tuple(sinais), tuple(falhas))


def _json(http: ClienteHttp, url: str) -> dict[str, Any]:
    try:
        dados = json.loads(http.obter_texto(url))
    except json.JSONDecodeError as erro:
        raise ErroHttp(f"DOE-SP não devolveu JSON: {erro}") from erro
    if not isinstance(dados, dict):
        raise ErroHttp("DOE-SP mudou de formato")
    return dados
