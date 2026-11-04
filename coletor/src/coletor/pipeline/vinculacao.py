"""Etapa 2: sinal → concurso (novo ou existente) + documentos listados na página.

Vinculação simples desta fase: a página oficial do concurso (URL do sinal) identifica o concurso.
A deduplicação entre fontes diferentes (fase 8) entra aqui depois, sem mudar o contrato.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from typing import Any

from coletor.classificacao.escolaridade import InferidorEscolaridade
from coletor.classificacao.orgao import OrgaoInferido, inferir_orgao
from coletor.db import Linha, Repositorio
from coletor.fontes.base import DadosEstruturados
from coletor.pipeline.comum import FUSO, ResumoEtapa, agora, hoje
from coletor.pipeline.deduplicacao import Candidato, procurar_equivalente
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


def _registrar_documentos(repo: Repositorio, concurso_id: int, arquivos_pdf: list[dict[str, Any]]) -> tuple[int, bool]:
    novos = 0
    tinha_texto = False
    for arquivo in arquivos_pdf:
        data = date.fromisoformat(arquivo["data"]) if arquivo.get("data") else None
        novos += repo.garantir_documento(
            concurso_id,
            # A fonte pode dizer o tipo (Cebraspe: todo documento começa com "Edital nº N").
            arquivo.get("tipo") or classificar_tipo_documento(arquivo.get("titulo", "")),
            arquivo.get("titulo") or "Documento",
            arquivo["url"],
            data,
            bool(arquivo.get("oficial", True)),
        )
        if arquivo.get("texto"):  # diários oficiais: o texto vem da API, não há PDF para baixar
            repo.gravar_texto_se_pendente(arquivo["url"], arquivo["texto"])
            tinha_texto = True
    return novos, tinha_texto


def _vincular_busca(
    repo: Repositorio,
    sinal: Linha,
    payload: dict[str, Any],
    candidatos: list[Candidato],
    inferidor: InferidorEscolaridade,
) -> tuple[int, bool, int]:
    """Sinal da busca na web. Se outra fonte já trouxe o concurso, só guarda o pré-cadastro (e o link do edital,
    se ainda não houver um); a fonte da banca continua mandando no título, no órgão e nas datas."""
    estruturado = DadosEstruturados.de_payload(payload["estruturado"])
    orgao = orgao_do_sinal(sinal["titulo"], estruturado)
    banca_id = repo.banca_por_sigla(payload.get("banca_sigla"))
    concurso_id = sinal["concurso_id"] or repo.concurso_por_link(sinal["url"])
    ambiguo = False
    if concurso_id is None:
        equivalencia = procurar_equivalente(
            orgao.nome if orgao else None, orgao.uf if orgao else None, banca_id, estruturado.ano, candidatos
        )
        concurso_id, ambiguo = equivalencia.concurso_id, equivalencia.ambiguo
    arquivos_pdf = [a for a in payload.get("arquivos", []) if a.get("pdf", eh_pdf(a.get("url", "")))]
    novo = concurso_id is None
    so_busca = novo or any(c.id == concurso_id and c.so_busca for c in candidatos)
    if novo:
        concurso_id = repo.garantir_concurso(
            titulo=sinal["titulo"],
            link_oficial=sinal["url"],
            banca_id=banca_id,
            orgao_id=repo.garantir_orgao(orgao) if orgao else None,
            link_inscricao=None,
            tem_edital=bool(arquivos_pdf),
        )
        if ambiguo:
            repo.marcar_possivel_duplicado(concurso_id)
        candidatos.append(Candidato(concurso_id, orgao.nome if orgao else None, orgao.uf if orgao else None,
                                    banca_id, estruturado.ano, True))  # fmt: skip
    assert concurso_id is not None
    repo.gravar_dados_busca(concurso_id, payload.get("busca") or {})
    documentos = 0
    if arquivos_pdf and not repo.tem_edital(concurso_id):
        documentos, _ = _registrar_documentos(repo, concurso_id, arquivos_pdf)
    if so_busca:
        estruturado = completar_escolaridade(estruturado, inferidor)
        repo.aplicar_dados_fonte(concurso_id, estruturado, situacao_da_fonte(estruturado, hoje()))
    repo.marcar_sinal_vinculado(sinal["id"], concurso_id)
    return concurso_id, novo, documentos


def executar_vinculacao(
    repo: Repositorio,
    janela: timedelta = timedelta(hours=36),
    inferidor: InferidorEscolaridade | None = None,
) -> ResumoEtapa:
    inicio = agora()
    inferidor = inferidor or InferidorEscolaridade.padrao()
    sinais = repo.sinais_para_vincular(inicio - janela)
    candidatos = [Candidato.da_linha(linha) for linha in repo.candidatos_deduplicacao()] if sinais else []
    novos_concursos = 0
    novos_documentos = 0
    descartados = 0
    falhas: list[str] = []
    for sinal in sinais:
        payload = sinal["payload"] or {}
        encerrado = bool(payload.get("encerrado"))
        try:
            with repo.transacao():
                if sinal.get("fonte_tipo") == "BUSCA_IA" and payload.get("estruturado"):
                    _, novo, documentos = _vincular_busca(repo, sinal, payload, candidatos, inferidor)
                    novos_concursos += novo
                    novos_documentos += documentos
                    continue
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
                if not ja_existia and orgao is not None and repo.concurso_por_link(sinal["url"]) is None:
                    # Concurso que só a busca na web conhecia: a página da banca vira a oficial (sem duplicar).
                    equivalencia = procurar_equivalente(orgao.nome, orgao.uf, sinal["banca_id"],
                                                        estruturado.ano if estruturado else None, candidatos,
                                                        somente_busca=True)  # fmt: skip
                    if equivalencia.concurso_id is not None:
                        repo.adotar_link_oficial(equivalencia.concurso_id, sinal["url"], sinal["banca_id"])
                        log.info("concurso %d (busca na web) passa a usar a página %s", equivalencia.concurso_id,
                                 sinal["url"])  # fmt: skip
                concurso_id = repo.garantir_concurso(
                    titulo=sinal["titulo"],
                    link_oficial=sinal["url"],
                    banca_id=sinal["banca_id"],
                    orgao_id=orgao_id,
                    link_inscricao=payload.get("link_inscricao"),
                    tem_edital=bool(arquivos_pdf),
                )
                novos_concursos += not ja_existia
                documentos, tinha_texto = _registrar_documentos(repo, concurso_id, arquivos_pdf)
                novos_documentos += documentos
                if tinha_texto:
                    repo.tirar_texto_do_sinal(sinal["id"])  # o texto fica só no documento
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
