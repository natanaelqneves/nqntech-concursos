"""Etapas 3 e 4: download temporário + extração de texto, documento a documento.

Baixar e extrair ficam juntos porque o PDF nunca é guardado (seção 5.3 do contexto): cada arquivo vive numa
pasta temporária só enquanto o texto é extraído e é apagado em seguida, mesmo se algo falhar.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError

from coletor.db import Repositorio
from coletor.http_cliente import AcessoNaoPermitido, ClienteHttp, ErroHttp
from coletor.pipeline.comum import DIAS_FOLGA_INSCRICAO, ResumoEtapa, agora, hoje
from coletor.texto import limitar

log = logging.getLogger(__name__)

MAX_CARACTERES_TEXTO = 1_500_000
MAX_PAGINAS = 400
MIN_CARACTERES_UTEIS = 200  # abaixo disso o PDF provavelmente é imagem escaneada


class ExtracaoFalhou(Exception):
    pass


def extrair_texto_pdf(caminho: Path) -> str:
    """Texto do PDF com páginas separadas por \\f. Levanta ExtracaoFalhou para PDF protegido ou corrompido."""
    try:
        with pdfplumber.open(caminho) as pdf:
            paginas = []
            for pagina in pdf.pages[:MAX_PAGINAS]:
                paginas.append(pagina.extract_text() or "")
                pagina.flush_cache()  # PDFs grandes: libera memória página a página
            return "\n\f\n".join(paginas)
    except Exception as erro:  # pdfplumber/pdfminer levantam muitos tipos, às vezes embrulhados
        causas = _cadeia(erro)
        if any(isinstance(c, PDFPasswordIncorrect) for c in causas):
            raise ExtracaoFalhou("PDF protegido por senha") from erro
        if any(isinstance(c, PDFSyntaxError) for c in causas):
            raise ExtracaoFalhou("PDF corrompido") from erro
        raise ExtracaoFalhou(f"PDF ilegível: {type(causas[-1]).__name__}") from erro


def _cadeia(erro: BaseException) -> list[BaseException]:
    causas: list[BaseException] = []
    atual: BaseException | None = erro
    while atual is not None and atual not in causas:
        causas.append(atual)
        atual = (
            atual.__cause__
            or atual.__context__
            or next((a for a in getattr(atual, "args", ()) if isinstance(a, BaseException)), None)
        )
    return causas


def executar_documentos(
    repo: Repositorio,
    criar_http: Callable[[frozenset[str]], ClienteHttp],
    dominios: frozenset[str],
    limite: int,
    max_bytes: int,
) -> ResumoEtapa:
    inicio = agora()
    ignorados = repo.ignorar_documentos_sem_interesse(hoje(), DIAS_FOLGA_INSCRICAO)
    pendentes = repo.documentos_pendentes(limite)
    repo.conn.commit()
    log.info(
        "documentos: %d pendentes nesta execução (limite %d); %d marcados como IGNORADO",
        len(pendentes),
        limite,
        ignorados,
    )

    processados = 0
    falhas: list[str] = []
    with criar_http(dominios) as http, tempfile.TemporaryDirectory(prefix="nqntech-pdf-") as pasta:
        for documento in pendentes:
            url = documento["url_origem"]
            try:
                download = http.baixar_pdf(url, Path(pasta), max_bytes)
            except ErroHttp as erro:
                repo.retomar_conexao()
                log.warning("download recusado/falhou: %s", erro)
                # Fora da política (robots.txt, domínio) ou fora dos limites não é falha: é decisão de não baixar.
                recusado = isinstance(erro, AcessoNaoPermitido) or "excede" in str(erro) or "não é PDF" in str(erro)
                status = "IGNORADO" if recusado else "FALHA"
                repo.salvar_extracao(documento["id"], None, None, status)
                if status == "FALHA":
                    falhas.append(f"{url}: {erro}")
                continue

            try:
                repo.retomar_conexao()
                existente = repo.texto_por_hash(download.sha256)
                repo.conn.commit()  # a extração pode levar minutos: nada de transação aberta enquanto isso
                if existente is not None:
                    # Mesmo arquivo publicado em outra URL (comum em retificações consolidadas): reaproveita.
                    repo.salvar_extracao(
                        documento["id"], download.sha256, existente["texto_extraido"], existente["status_extracao"]
                    )
                else:
                    try:
                        texto = extrair_texto_pdf(download.caminho)
                    except ExtracaoFalhou as erro:
                        log.warning("extração falhou em %s: %s", url, erro)
                        repo.retomar_conexao()
                        repo.salvar_extracao(documento["id"], download.sha256, None, "FALHA")
                        falhas.append(f"{url}: {erro}")
                        continue
                    repo.retomar_conexao()
                    util = len(texto.replace("\f", "").strip())
                    status = "OK" if util >= MIN_CARACTERES_UTEIS else "SEM_TEXTO"
                    repo.salvar_extracao(documento["id"], download.sha256, limitar(texto, MAX_CARACTERES_TEXTO), status)
                processados += 1
                log.info("documento %d ok (%d KB, %s)", documento["id"], download.tamanho // 1024, documento["tipo"])
            finally:
                download.caminho.unlink(missing_ok=True)

    status = "SUCESSO" if not falhas else ("FALHA" if processados == 0 else "PARCIAL")
    mensagem = "; ".join(falhas[:10]) or None
    repo.registrar_execucao("DOCUMENTOS", inicio, status, processados, mensagem)
    return ResumoEtapa("DOCUMENTOS", status, processados, mensagem)
