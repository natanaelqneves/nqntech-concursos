"""Etapa "localizar": acha o PDF do edital dos pré-cadastros (busca na web) que ainda não têm um.

Ordem: o link do PDF que a busca informou; senão, os links de PDF da página oficial do concurso, escolhendo o que
parece o edital de abertura. O que for achado entra como documento PENDENTE e é baixado na etapa seguinte (de
qualquer site público que permita no robots.txt). Sem sucesso, o concurso vai para o e-mail de pendências e o
administrador envia o PDF pelo Drive com o código do concurso. Cada concurso é procurado no máximo a cada
`intervalo_h` horas.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from coletor.db import Repositorio
from coletor.http_cliente import QUALQUER_DOMINIO_PUBLICO, ClienteHttp, ErroHttp
from coletor.ia.busca_web import eh_oficial
from coletor.pipeline.comum import ResumoEtapa, agora
from coletor.texto import normalizar

log = logging.getLogger(__name__)

_NAO_E_ABERTURA = re.compile(
    r"resultado|gabarito|convoca|homologa|classifica|recurso|retifica|comunicado|aviso|\bata\b|cronograma|"
    r"local de prova|cartao|nomea|errata|anexo|modelo|requerimento|formulario|lista"
)


def _texto_e_url(link: tuple[str, str]) -> str:
    texto, url = link
    return normalizar(f"{texto} {urlsplit(url).path.rsplit('/', 1)[-1]}")


def escolher_edital(links: Iterable[tuple[str, str]]) -> str | None:
    """Dos links (texto, url absoluta) de PDF da página, o que parece o edital de abertura; None se nenhum."""
    melhor: tuple[int, int, str] | None = None
    for ordem, (texto, url) in enumerate(links):
        descricao = _texto_e_url((texto, url))
        if "edital" not in descricao or _NAO_E_ABERTURA.search(descricao):
            continue
        pontos = 2 * ("abertura" in descricao) + ("consolidado" in descricao or "atualizado" in descricao)
        candidato = (pontos, -ordem, url)  # empate: o primeiro da página
        if melhor is None or candidato > melhor:
            melhor = candidato
    return melhor[2] if melhor else None


def links_de_pdf(html: str, base: str) -> list[tuple[str, str]]:
    sopa = BeautifulSoup(html, "html.parser")
    links: list[tuple[str, str]] = []
    for ancora in sopa.find_all("a", href=True):
        url = urljoin(base, str(ancora["href"]).strip())
        if url.startswith("https://") and urlsplit(url).path.lower().endswith(".pdf"):
            links.append((ancora.get_text(" ", strip=True), url))
    return links


def executar_localizacao(
    repo: Repositorio,
    criar_http: Callable[[frozenset[str]], ClienteHttp],
    dominios_banca: Callable[[str | None], tuple[str, ...]],
    limite: int,
    intervalo_h: float,
) -> ResumoEtapa:
    inicio = agora()
    pendentes = repo.concursos_sem_edital(limite, intervalo_h)
    repo.conn.commit()
    achados = 0
    if not pendentes:
        return ResumoEtapa("LOCALIZACAO", "SUCESSO", 0)
    with criar_http(QUALQUER_DOMINIO_PUBLICO) as http:
        for concurso in pendentes:
            ja_tentados = repo.urls_de_documentos(concurso["id"])
            repo.conn.commit()
            url, falha = None, None
            sugerido = (concurso["dados"] or {}).get("link_edital")
            if sugerido and sugerido not in ja_tentados:
                url = sugerido
            else:
                try:
                    html = http.obter_texto(concurso["link_oficial"])
                except ErroHttp as erro:
                    falha = f"página oficial: {erro}"
                else:
                    candidatos = [
                        (t, u) for t, u in links_de_pdf(html, concurso["link_oficial"]) if u not in ja_tentados
                    ]
                    url = escolher_edital(candidatos)
                    if url is None:
                        falha = "nenhum PDF de edital na página oficial"
                if sugerido and sugerido in ja_tentados and url is None:
                    falha = f"o PDF indicado pela busca não pôde ser lido; {falha}"
            repo.retomar_conexao()
            with repo.transacao():
                if url is not None:
                    oficial = eh_oficial(url, dominios_banca(concurso["banca"]))
                    repo.garantir_documento(concurso["id"], "EDITAL", "Edital de abertura", url, None, oficial)
                    achados += 1
                    log.info("concurso %d: edital a baixar em %s", concurso["id"], url)
                else:
                    log.info("concurso %d: edital não encontrado (%s)", concurso["id"], falha)
                repo.marcar_edital_procurado(concurso["id"], falha)
    repo.registrar_execucao("LOCALIZACAO", inicio, "SUCESSO", achados, None)
    log.info("localização: %d pré-cadastros sem edital, %d editais encontrados", len(pendentes), achados)
    return ResumoEtapa("LOCALIZACAO", "SUCESSO", achados)
