"""Etapa 2: sinal → concurso (novo ou existente) + documentos listados na página.

Vinculação simples desta fase: a página oficial do concurso (URL do sinal) identifica o concurso.
A deduplicação entre fontes diferentes (fase 8) entra aqui depois, sem mudar o contrato.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from coletor.db import OrgaoInferido, Repositorio
from coletor.fontes.base import DadosEstruturados
from coletor.pipeline.comum import ResumoEtapa, agora, hoje
from coletor.texto import colapsar_espacos, normalizar, uf_por_nome

log = logging.getLogger(__name__)

_PREFIXO_TITULO = re.compile(
    r"^(?:[ivxlc]+\s+)?(?:concurso p[uú]blico|processo seletivo(?: p[uú]blico| simplificado)?|sele[cç][aã]o p[uú]blica)"
    r"(?:\s+nacional\s+unificado)?(?:\s+para\s+(?:provimento\s+de\s+cargos?\s+de\s+.+?\s+(?:d[oa]s?|n[oa]s?)\s+)?)?"
    r"(?:\s*(?:para|d[oa]s?|n[oa]s?|a|o)\s+)*",
    re.IGNORECASE,
)
_SUFIXO_TITULO = re.compile(r"\s*(?:[-–(].*|\d{4}.*)$")
_MUNICIPAL = re.compile(r"\b(prefeitura|camara municipal|municipio|guarda municipal|secretaria municipal)\b")
_FEDERAL = re.compile(
    r"\b(federal|nacional|da uniao|ministerio|receita federal|trf|trt|tre|tst|stj|stf|cnj|csjt|inss|ibge|"
    r"dataprev|serpro|banco do brasil|caixa economica|petrobras|correios|nav brasil|nucleares do brasil|abdi)\b"
)
_ESTADUAL = re.compile(
    r"\b(do estado|estadual|governo d[oe]|assembleia legislativa|tribunal de justica|tribunal de contas do estado|"
    r"ministerio publico do estado|defensoria publica do estado|procuradoria-geral do estado|policia (militar|civil)|"
    r"secretaria (de estado|da fazenda|estadual)|controladoria-geral do estado)\b"
)
_MUNICIPIO_NOME = re.compile(r"(?:prefeitura|camara)\s+(?:municipal\s+)?d[eoa]s?\s+(.+)$", re.IGNORECASE)

_TIPO_RETIFICACAO = re.compile(r"retifica")
_TIPO_COMUNICADO = re.compile(
    r"comunicado|aviso|convoca|resultado|gabarito|homologa|classifica|local de prova|"
    r"cartao|recurso|padrao de resposta|nomea|lista|ata\b"
)


def classificar_tipo_documento(titulo: str) -> str:
    normal = normalizar(titulo)
    if normal.startswith("edital") and not _TIPO_COMUNICADO.search(normal):
        return "EDITAL"  # inclui "Edital (retificado em ...)", a versão consolidada
    if _TIPO_RETIFICACAO.search(normal):
        return "RETIFICACAO"
    if "edital" in normal and re.search(r"abertura|normativo|de inscric", normal):
        return "EDITAL"
    if _TIPO_COMUNICADO.search(normal):
        return "COMUNICADO"
    return "OUTRO"


def inferir_orgao(titulo_concurso: str) -> OrgaoInferido | None:
    """'Concurso Público para o Tribunal de Justiça do Estado da Paraíba' → órgão, esfera e UF."""
    nome = colapsar_espacos(_PREFIXO_TITULO.sub("", colapsar_espacos(titulo_concurso)))
    nome = _SUFIXO_TITULO.sub("", nome).strip(" -–,.")
    if len(nome) < 4:
        return None
    nome = nome[0].upper() + nome[1:]
    normal = normalizar(titulo_concurso)  # esfera pelo título inteiro: a sigla no fim ("- Dataprev") ajuda
    if _MUNICIPAL.search(normal):
        municipio = _MUNICIPIO_NOME.search(nome)
        return OrgaoInferido(nome, "MUNICIPAL", uf_por_nome(nome), municipio.group(1).strip() if municipio else None)
    if _ESTADUAL.search(normal) or uf_por_nome(nome):
        return OrgaoInferido(nome, "ESTADUAL", uf_por_nome(nome), None)
    if _FEDERAL.search(normal):
        return OrgaoInferido(nome, "FEDERAL", None, None)
    return OrgaoInferido(nome, None, None, None)


def orgao_do_sinal(titulo: str, estruturado: DadosEstruturados | None) -> OrgaoInferido | None:
    """Órgão informado pela página da banca, completado pela inferência a partir do nome; senão, do título."""
    if estruturado is None or not estruturado.orgao:
        return inferir_orgao(titulo)
    inferido = inferir_orgao(estruturado.orgao)
    return OrgaoInferido(
        nome=estruturado.orgao,
        esfera=estruturado.esfera or (inferido.esfera if inferido else None),
        uf=estruturado.uf or (inferido.uf if inferido else None),
        municipio=estruturado.municipio or (inferido.municipio if inferido else None),
    )


def situacao_da_fonte(dados: DadosEstruturados, referencia: date) -> str:
    """A situação informada pela banca, corrigida pelas datas (a página às vezes demora a atualizar)."""
    situacao = dados.situacao or "EM_ANDAMENTO"
    if situacao in ("ENCERRADO", "PREVISTO"):
        return situacao
    if dados.inscricao_fim is not None:
        return "INSCRICOES_ABERTAS" if referencia <= dados.inscricao_fim else "EM_ANDAMENTO"
    return situacao


def eh_pdf(url: str) -> bool:
    return url.lower().split("?")[0].split("#")[0].endswith(".pdf")


def executar_vinculacao(repo: Repositorio, janela: timedelta = timedelta(hours=36)) -> ResumoEtapa:
    inicio = agora()
    sinais = repo.sinais_para_vincular(inicio - janela)
    novos_concursos = 0
    novos_documentos = 0
    falhas: list[str] = []
    for sinal in sinais:
        payload = sinal["payload"] or {}
        try:
            with repo.transacao():
                arquivos_pdf = [a for a in payload.get("arquivos", []) if a.get("pdf", eh_pdf(a.get("url", "")))]
                estruturado = (
                    DadosEstruturados.de_payload(payload["estruturado"]) if payload.get("estruturado") else None
                )
                orgao = orgao_do_sinal(sinal["titulo"], estruturado)
                orgao_id = repo.garantir_orgao(orgao) if orgao else None
                ja_existia = sinal["concurso_id"] is not None
                concurso_id = repo.garantir_concurso(
                    titulo=sinal["titulo"],
                    link_oficial=sinal["url"],
                    banca_id=sinal["banca_id"],
                    orgao_id=orgao_id,
                    link_inscricao=payload.get("link_inscricao"),
                    tem_edital=bool(arquivos_pdf),
                )
                novos_concursos += not ja_existia
                for arquivo in arquivos_pdf:
                    data = date.fromisoformat(arquivo["data"]) if arquivo.get("data") else None
                    novos_documentos += repo.garantir_documento(
                        concurso_id,
                        classificar_tipo_documento(arquivo.get("titulo", "")),
                        arquivo.get("titulo") or "Documento",
                        arquivo["url"],
                        data,
                    )
                if estruturado is not None:
                    repo.aplicar_dados_fonte(concurso_id, estruturado, situacao_da_fonte(estruturado, hoje()))
                repo.marcar_sinal_vinculado(sinal["id"], concurso_id)
        except Exception as erro:
            log.exception("falha ao vincular o sinal %s", sinal["url"])
            falhas.append(f"{sinal['url']}: {erro}")

    status = "SUCESSO" if not falhas else ("FALHA" if len(falhas) == len(sinais) else "PARCIAL")
    mensagem = "; ".join(falhas[:10]) or None
    repo.registrar_execucao("VINCULACAO", inicio, status, novos_documentos, mensagem)
    log.info(
        "vinculação: %d sinais, %d concursos novos, %d documentos novos", len(sinais), novos_concursos, novos_documentos
    )
    return ResumoEtapa("VINCULACAO", status, novos_documentos, mensagem)
