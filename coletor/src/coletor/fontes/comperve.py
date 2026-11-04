"""Fonte COMPERVE (Núcleo Permanente de Concursos da UFRN): https://www.comperve.ufrn.br/conteudo/concursos.php.

Estrutura observada em 04/11/2026 (PHP, HTML estático, UTF-8): a listagem tem blocos `div.categoria` (SUSPENSOS,
NOVOS, INSCRIÇÕES ABERTAS, EM ANDAMENTO, CONCLUÍDOS) seguidos de links `concursos/<slug>/informacoes.php`. Cada
concurso tem `informacoes.php` (órgão no primeiro `h1` de `div.cabecalho_titulo`), `documentos.php` (seção
"Editais" com os PDFs) e `inscricoes.php` (período por extenso). robots.txt inexistente (404). O servidor não envia
o certificado intermediário: ver `http_cliente.contexto_tls`.

Só NOVOS e INSCRIÇÕES ABERTAS viram sinal; os comentários HTML da listagem trazem itens antigos e são descartados.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from urllib.parse import urljoin

from coletor.fontes.base import DadosEstruturados, ResultadoDescoberta, SinalDescoberta
from coletor.http_cliente import ClienteHttp, ErroHttp
from coletor.texto import colapsar_espacos, normalizar, titulo_portugues, todas_as_datas

log = logging.getLogger(__name__)

BASE = "https://www.comperve.ufrn.br/conteudo/"
LISTAGEM = f"{BASE}concursos.php"
CATEGORIAS = {"novos": "PREVISTO", "inscricoes abertas": "INSCRICOES_ABERTAS"}

_COMENTARIO = re.compile(r"<!--.*?-->", re.S)
_CATEGORIA = re.compile(r'<div class="categoria">\s*([^<]+?)\s*</div>', re.I)
_ITEM = re.compile(r'href="concursos/([a-z0-9_]{3,60})/informacoes\.php"[^>]*>(.*?)</a>', re.I | re.S)
_TITULO_CABECALHO = re.compile(r'<div class="cabecalho_titulo">(.*?)</div>', re.I | re.S)
_H1 = re.compile(r"<h1>(.*?)</h1>", re.I | re.S)
_LINK = re.compile(r"""<a\s+href=['"]([^'"]+\.pdf)['"][^>]*>(.*?)</a>""", re.I | re.S)
_NUMERO = re.compile(r"Edital\s+N[ºo°]?\s*(\d{1,3}\s*/\s*\d{4})", re.I)
_SECAO_EDITAIS = re.compile(r">\s*Editais\s*</li>(.*?)</details>", re.I | re.S)
_PERIODO = re.compile(r"inscri[çc][ãa]o dever[áa] ser feita(.{0,300})", re.I | re.S)


def _texto(fragmento: str) -> str:
    return colapsar_espacos(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragmento)))


def itens_da_listagem(html: str) -> list[tuple[str, str, str]]:
    """(slug, título, situação) dos concursos novos e com inscrições abertas, na ordem da página."""
    html = _COMENTARIO.sub("", html)
    marcas = list(_CATEGORIA.finditer(html))
    itens: list[tuple[str, str, str]] = []
    for i, marca in enumerate(marcas):
        situacao = CATEGORIAS.get(normalizar(marca.group(1)))
        if situacao is None:
            continue
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(html)
        for slug, titulo in _ITEM.findall(html, marca.end(), fim):
            itens.append((slug, _texto(titulo), situacao))
    return itens


def orgao(html_informacoes: str) -> str | None:
    cabecalho = _TITULO_CABECALHO.search(html_informacoes)
    titulos = [_texto(h) for h in _H1.findall(cabecalho.group(1))] if cabecalho else []
    return titulo_portugues(titulos[0]) if titulos and "COMPERVE" not in titulos[0].upper() else None


def edital_de_abertura(html_documentos: str, url_documentos: str) -> dict[str, object] | None:
    """O edital consolidado ("retificado em ...") se houver; senão o original. Retificações avulsas ficam de fora."""
    secao = _SECAO_EDITAIS.search(html_documentos)
    if secao is None:
        return None
    candidatos = []
    for href, rotulo in _LINK.findall(secao.group(1)):
        titulo = _texto(rotulo)
        if re.match(r"edital\s+n", titulo, re.I):
            candidatos.append((0 if "retificado" in titulo.lower() else 1, titulo, href))
    if not candidatos:
        return None
    _, titulo, href = min(candidatos)
    datas = todas_as_datas(titulo)
    return {
        "titulo": titulo,
        "url": urljoin(url_documentos, href),
        "data": datas[0].isoformat() if datas else None,
        "pdf": True,
        "tipo": "EDITAL",
    }


def periodo_inscricao(html_inscricoes: str) -> tuple:
    trecho = _PERIODO.search(_texto(html_inscricoes))
    datas = todas_as_datas(trecho.group(1)) if trecho else []
    return (datas[0], datas[1]) if len(datas) >= 2 and datas[0] <= datas[1] else (None, None)


def montar_sinal(
    slug: str,
    titulo: str,
    situacao: str,
    informacoes: str,
    documentos: str | None,
    inscricoes: str | None,
) -> SinalDescoberta:
    url = f"{BASE}concursos/{slug}/informacoes.php"
    url_documentos = f"{BASE}concursos/{slug}/documentos.php"
    arquivo = edital_de_abertura(documentos, url_documentos) if documentos else None
    inicio, fim = periodo_inscricao(inscricoes) if inscricoes else (None, None)
    numero = _NUMERO.search(_texto(informacoes))
    avisos = () if arquivo else ("edital ainda não localizado na página da banca: confira a página oficial",)
    return SinalDescoberta(
        titulo=titulo,
        url=url,
        data_publicacao=inicio,
        payload={
            "titulo": titulo,
            "situacao_site": situacao,
            "descricao": titulo,
            "link_inscricao": f"{BASE}concursos/{slug}/inscricoes.php" if situacao == "INSCRICOES_ABERTAS" else None,
            "arquivos": [arquivo] if arquivo else [],
        },
        estruturado=DadosEstruturados(
            orgao=orgao(informacoes),
            numero_edital=re.sub(r"\s", "", numero.group(1)) if numero else None,
            situacao=situacao,
            inscricao_inicio=inicio,
            inscricao_fim=fim,
            avisos=avisos,
        ),
    )


class FonteComperve:
    nome = "comperve"
    dominios = frozenset({"www.comperve.ufrn.br"})

    def descobrir(self, http: ClienteHttp, pular: frozenset[str] = frozenset()) -> ResultadoDescoberta:
        itens = itens_da_listagem(http.obter_texto(LISTAGEM))  # sem a listagem, a fonte inteira falha
        log.info("COMPERVE: %d concursos novos ou com inscrições abertas", len(itens))
        sinais: list[SinalDescoberta] = []
        falhas: list[str] = []
        for slug, titulo, situacao in itens:
            pasta = f"{BASE}concursos/{slug}/"
            if f"{pasta}informacoes.php" in pular:
                continue
            try:
                informacoes = http.obter_texto(f"{pasta}informacoes.php")
            except ErroHttp as erro:
                log.warning("COMPERVE: falha ao ler %s: %s", slug, erro)
                falhas.append(f"{slug}: {erro}")
                continue
            sinais.append(
                montar_sinal(
                    slug,
                    titulo,
                    situacao,
                    informacoes,
                    _opcional(http, f"{pasta}documentos.php"),
                    _opcional(http, f"{pasta}inscricoes.php"),
                )
            )
        return ResultadoDescoberta(tuple(sinais), tuple(falhas))


def _opcional(http: ClienteHttp, url: str) -> str | None:
    """Páginas secundárias: concurso "novo" ainda pode não ter inscrições; a falta delas não derruba o sinal."""
    try:
        return http.obter_texto(url)
    except ErroHttp as erro:
        log.info("COMPERVE: página secundária indisponível (%s): %s", url, erro)
        return None
