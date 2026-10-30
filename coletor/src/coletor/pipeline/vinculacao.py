"""Etapa 2: sinal → concurso (novo ou existente) + documentos listados na página.

Vinculação simples desta fase: a página oficial do concurso (URL do sinal) identifica o concurso.
A deduplicação entre fontes diferentes (fase 8) entra aqui depois, sem mudar o contrato.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import date, datetime, time, timedelta

from coletor.classificacao.escolaridade import InferidorEscolaridade
from coletor.classificacao.orgao import OrgaoInferido, inferir_orgao
from coletor.db import Repositorio
from coletor.fontes.base import DadosEstruturados
from coletor.pipeline.comum import FUSO, ResumoEtapa, agora, hoje
from coletor.texto import normalizar

log = logging.getLogger(__name__)

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


def completar_escolaridade(dados: DadosEstruturados, inferidor: InferidorEscolaridade) -> DadosEstruturados:
    """Cargos sem escolaridade na página da banca recebem a inferida pelo nome (mesma regra da classificação),
    para que a comparação com o que já está gravado não veja mudança onde não houve."""
    cargos = tuple(
        c if c.escolaridade else replace(c, escolaridade=inferidor.inferir(c.nome, c.especialidade))
        for c in dados.cargos
    )
    return replace(dados, cargos=cargos)


def situacao_da_fonte(dados: DadosEstruturados, referencia: date) -> str:
    """A situação informada pela banca, corrigida pelas datas (a página às vezes demora a atualizar)."""
    situacao = dados.situacao or "EM_ANDAMENTO"
    if situacao in ("ENCERRADO", "PREVISTO"):
        return situacao
    if dados.inscricao_fim is not None:
        return "INSCRICOES_ABERTAS" if referencia <= dados.inscricao_fim else "EM_ANDAMENTO"
    return situacao


# Encerrados que nunca acompanhamos só interessam se ainda vão aparecer no site (seção 2 do contexto: encerrados
# há mais de 180 dias saem das páginas). Mais antigos que isso são descartados sem criar concurso.
DIAS_ENCERRADO_NO_SITE = 180


def inicio_do_dia(dia: date | None) -> datetime | None:
    return datetime.combine(dia, time.min, tzinfo=FUSO) if dia else None


def encerrado_recente(data_publicacao: date | None, referencia: date) -> bool:
    return data_publicacao is not None and (referencia - data_publicacao).days <= DIAS_ENCERRADO_NO_SITE


def eh_pdf(url: str) -> bool:
    return url.lower().split("?")[0].split("#")[0].endswith(".pdf")


def executar_vinculacao(
    repo: Repositorio,
    janela: timedelta = timedelta(hours=36),
    inferidor: InferidorEscolaridade | None = None,
) -> ResumoEtapa:
    inicio = agora()
    inferidor = inferidor or InferidorEscolaridade.padrao()
    sinais = repo.sinais_para_vincular(inicio - janela)
    novos_concursos = 0
    novos_documentos = 0
    descartados = 0
    falhas: list[str] = []
    for sinal in sinais:
        payload = sinal["payload"] or {}
        encerrado = bool(payload.get("encerrado"))
        try:
            with repo.transacao():
                antigo = not encerrado_recente(sinal["data_publicacao"], hoje())
                if encerrado and sinal["concurso_id"] is None and antigo:
                    repo.descartar_sinal(sinal["id"])
                    descartados += 1
                    continue
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
                    estruturado = completar_escolaridade(estruturado, inferidor)
                    repo.aplicar_dados_fonte(concurso_id, estruturado, situacao_da_fonte(estruturado, hoje()))
                if encerrado:
                    repo.marcar_encerrado(concurso_id, inicio_do_dia(sinal["data_publicacao"]))
                elif payload.get("encerrado") is False:
                    # Só fontes que separam "em andamento" de "realizados" (FGV) podem reabrir um concurso;
                    # nas demais a situação vem dos dados estruturados.
                    repo.reabrir(concurso_id)
                repo.marcar_sinal_vinculado(sinal["id"], concurso_id)
        except Exception as erro:
            log.exception("falha ao vincular o sinal %s", sinal["url"])
            falhas.append(f"{sinal['url']}: {erro}")

    status = "SUCESSO" if not falhas else ("FALHA" if len(falhas) == len(sinais) else "PARCIAL")
    mensagem = "; ".join(falhas[:10]) or None
    repo.registrar_execucao("VINCULACAO", inicio, status, novos_documentos, mensagem)
    log.info(
        "vinculação: %d sinais, %d concursos novos, %d documentos novos, %d encerrados antigos descartados",
        len(sinais),
        novos_concursos,
        novos_documentos,
        descartados,
    )
    return ResumoEtapa("VINCULACAO", status, novos_documentos, mensagem)
