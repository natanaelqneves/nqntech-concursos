"""Importação manual de PDFs para bancas sem coleta automática (robots.txt, 403, sem rota pública).

Fluxo: cada PDF da pasta vira um sinal da fonte inativa `manual-<banca>` com o documento já lido; daí em diante o
caminho é o mesmo da coleta automática (vinculação, estruturação com regras e IA, classificação, resumo e
publicação). Os mesmos limites valem: tamanho máximo, assinatura %PDF-, PDF protegido/corrompido/escaneado, texto
limitado. O PDF não é copiado nem guardado; só o texto vai ao banco (seção 5.3 do contexto).

Link oficial por arquivo: `<nome>.url` ao lado do PDF (uma linha https://...), senão o `--link` do comando. PDFs
com o mesmo link viram o mesmo concurso (edital + retificação). Sem link, o concurso aparece no site sem o botão
da página oficial.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from coletor.db import Repositorio
from coletor.fontes.base import SinalDescoberta
from coletor.pipeline.comum import ResumoEtapa
from coletor.pipeline.documentos import MAX_CARACTERES_TEXTO, MIN_CARACTERES_UTEIS, ExtracaoFalhou, extrair_texto_pdf
from coletor.pipeline.vinculacao import classificar_tipo_documento, executar_vinculacao
from coletor.texto import colapsar_espacos, limitar

log = logging.getLogger(__name__)

_LINK = re.compile(r"^https://[^\s<>\"']{4,500}$")


class ImportacaoInvalida(Exception):
    pass


@dataclass(frozen=True)
class PdfLido:
    arquivo: Path
    sha256: str
    texto: str | None
    status: str  # OK, SEM_TEXTO ou FALHA (mesmos status da etapa de documentos)
    link: str | None
    motivo: str | None = None

    @property
    def url_documento(self) -> str:
        # Identificador estável do arquivo (não é URL navegável): o mesmo PDF importado duas vezes não duplica.
        return f"manual:{self.sha256}"


def titulo_do_arquivo(arquivo: Path) -> str:
    return colapsar_espacos(re.sub(r"[_\-]+", " ", arquivo.stem)) or "Edital"


def link_do_arquivo(arquivo: Path, padrao: str | None) -> str | None:
    lateral = arquivo.with_suffix(".url")
    link = lateral.read_text(encoding="utf-8").strip() if lateral.exists() else (padrao or "").strip()
    if not link:
        return None
    if not _LINK.match(link):
        raise ImportacaoInvalida(f"link inválido para {arquivo.name} (precisa começar com https://): {link!r}")
    return link


def ler_pdf(arquivo: Path, max_bytes: int, link_padrao: str | None) -> PdfLido:
    link = link_do_arquivo(arquivo, link_padrao)
    tamanho = arquivo.stat().st_size
    conteudo = arquivo.read_bytes() if tamanho <= max_bytes else b""
    sha = hashlib.sha256(conteudo or arquivo.name.encode()).hexdigest()
    if tamanho > max_bytes:
        return PdfLido(arquivo, sha, None, "FALHA", link, f"excede o limite de {max_bytes // 1024 // 1024} MB")
    if not conteudo.startswith(b"%PDF-"):
        return PdfLido(arquivo, sha, None, "FALHA", link, "conteúdo não começa com %PDF-")
    try:
        texto = extrair_texto_pdf(arquivo)
    except ExtracaoFalhou as erro:
        return PdfLido(arquivo, sha, None, "FALHA", link, str(erro))
    util = len(texto.replace("\f", "").strip())
    status = "OK" if util >= MIN_CARACTERES_UTEIS else "SEM_TEXTO"
    motivo = None if status == "OK" else "quase sem texto (PDF escaneado?): não será estruturado"
    return PdfLido(arquivo, sha, limitar(texto, MAX_CARACTERES_TEXTO), status, link, motivo)


def sinal_do_pdf(pdf: PdfLido) -> SinalDescoberta:
    titulo = titulo_do_arquivo(pdf.arquivo)
    tipo = classificar_tipo_documento(titulo)
    arquivo = {
        "titulo": titulo,
        "url": pdf.url_documento,
        "data": None,
        "pdf": True,
        # Nome de arquivo raramente diz "edital de abertura"; o que não for retificação/comunicado é edital.
        "tipo": "EDITAL" if tipo == "OUTRO" else tipo,
    }
    return SinalDescoberta(
        titulo=titulo,
        url=pdf.link or pdf.url_documento,
        payload={
            "titulo": titulo,
            "situacao_site": "MANUAL",
            "descricao": f"Importado manualmente de {pdf.arquivo.name}",
            "link_inscricao": None,
            "arquivos": [arquivo],
        },
    )


def importar_pasta(repo: Repositorio, pasta: Path, banca: str, link: str | None, max_bytes: int) -> ResumoEtapa:
    if not pasta.is_dir():
        raise ImportacaoInvalida(f"pasta não encontrada: {pasta}")
    fonte = repo.fonte_manual(banca)
    if fonte is None:
        raise ImportacaoInvalida(f"banca {banca!r} sem fonte manual cadastrada (use a sigla, ex.: FCC, VUNESP, OUTRA)")
    arquivos = sorted(p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if not arquivos:
        raise ImportacaoInvalida(f"nenhum PDF em {pasta}")

    lidos = [ler_pdf(arquivo, max_bytes, link) for arquivo in arquivos]
    for pdf in lidos:
        log.info("%s: %s%s", pdf.arquivo.name, pdf.status, f" ({pdf.motivo})" if pdf.motivo else "")
    validos = [p for p in lidos if p.status != "FALHA"]

    with repo.transacao():
        for pdf in validos:
            repo.gravar_sinal(fonte.id, sinal_do_pdf(pdf))
    executar_vinculacao(repo)
    for pdf in validos:
        documento_id = repo.documento_por_url(pdf.url_documento)
        if documento_id is None:  # vinculação falhou para este sinal (já registrado no log da etapa)
            continue
        repo.salvar_extracao(documento_id, pdf.sha256, pdf.texto, pdf.status)

    falhas = [f"{p.arquivo.name}: {p.motivo}" for p in lidos if p.status == "FALHA"]
    status = "SUCESSO" if not falhas else ("FALHA" if not validos else "PARCIAL")
    return ResumoEtapa("IMPORTACAO_MANUAL", status, len(validos), "; ".join(falhas) or None, fonte.nome)
