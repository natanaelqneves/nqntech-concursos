"""Etapa 5: área e escolaridade de cada cargo, recorte geográfico do concurso e destaque do CNU.

Recalcula tudo a cada execução (são poucos milhares de linhas) e grava só o que mudou, então uma regra nova em
config/*.yml vale para os concursos antigos já na execução seguinte, sem reprocessar editais.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from coletor.classificacao.areas import AREA_PADRAO, ClassificadorArea
from coletor.classificacao.destaques import DetectorCNU
from coletor.classificacao.escolaridade import InferidorEscolaridade
from coletor.classificacao.local import IndiceMunicipios, Local, ResolvedorLocal
from coletor.classificacao.orgao import OrgaoInferido, inferir_orgao
from coletor.classificacao.regras import carregar_yaml
from coletor.db import Linha, Repositorio
from coletor.pipeline.comum import ResumoEtapa, agora
from coletor.pipeline.vinculacao import DIAS_ENCERRADO_NO_SITE

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Classificadores:
    areas: ClassificadorArea
    escolaridade: InferidorEscolaridade
    cnu: DetectorCNU
    local: ResolvedorLocal

    @classmethod
    def padrao(cls, repo: Repositorio) -> Classificadores:
        return cls(
            areas=ClassificadorArea.de_dados(carregar_yaml("areas.yml"), areas_validas=repo.codigos_area()),
            escolaridade=InferidorEscolaridade.padrao(),
            cnu=DetectorCNU.padrao(),
            local=ResolvedorLocal(IndiceMunicipios(repo.municipios())),
        )


def orgao_do_concurso(concurso: Linha) -> OrgaoInferido | None:
    if concurso["orgao_nome"]:
        return OrgaoInferido(
            nome=concurso["orgao_nome"],
            esfera=concurso["orgao_esfera"],
            uf=concurso["orgao_uf"],
            municipio=concurso["orgao_municipio"],
        )
    return inferir_orgao(concurso["titulo"])


def executar_classificacao(repo: Repositorio, classificadores: Classificadores | None = None) -> ResumoEtapa:
    inicio = agora()
    classificadores = classificadores or Classificadores.padrao(repo)
    concursos = repo.concursos_para_classificar(DIAS_ENCERRADO_NO_SITE)
    cargos_por_concurso: dict[int, list[Linha]] = defaultdict(list)
    for cargo in repo.cargos_dos_concursos([c["id"] for c in concursos]):
        cargos_por_concurso[cargo["concurso_id"]].append(cargo)
    repo.conn.commit()

    alterados = 0
    sem_local = 0
    sem_area = 0
    falhas: list[str] = []
    for concurso in concursos:
        try:
            with repo.transacao():
                alterado, local_ok, cargos_sem_area = _classificar(repo, classificadores, concurso, cargos_por_concurso)
            alterados += alterado
            sem_local += not local_ok
            sem_area += cargos_sem_area
        except Exception as erro:
            log.exception("falha ao classificar o concurso %d", concurso["id"])
            falhas.append(f"concurso {concurso['id']}: {erro}")

    log.info(
        "classificação: %d concursos, %d alterados, %d sem local definido, %d cargos em %s",
        len(concursos),
        alterados,
        sem_local,
        sem_area,
        AREA_PADRAO,
    )
    status = "SUCESSO" if not falhas else ("FALHA" if len(falhas) == len(concursos) else "PARCIAL")
    mensagem = "; ".join(falhas[:10]) or None
    repo.registrar_execucao("CLASSIFICACAO", inicio, status, alterados, mensagem)
    return ResumoEtapa("CLASSIFICACAO", status, alterados, mensagem)


def _classificar(
    repo: Repositorio,
    classificadores: Classificadores,
    concurso: Linha,
    cargos_por_concurso: dict[int, list[Linha]],
) -> tuple[bool, bool, int]:
    """Devolve (algo mudou, local identificado, cargos sem área)."""
    orgao = orgao_do_concurso(concurso)
    unificado = classificadores.cnu.eh_cnu(concurso["titulo"], concurso["link_oficial"])
    contexto = " ".join(t for t in (concurso["descricao"], concurso["edital_inicio"]) if t)
    local = classificadores.local.resolver(orgao, unificado, contexto)
    if local.aviso:
        log.info("concurso %d (%s): %s", concurso["id"], concurso["titulo"][:80], local.aviso)
    if local.abrangencia is None:
        # Sem resposta nova, vale a anterior: um concurso já publicado não pode perder o local (o banco recusa).
        local = Local(concurso["abrangencia"], concurso["uf"], concurso["municipio_ibge"])

    alterado = repo.aplicar_local(concurso["id"], local, unificado)
    if concurso["orgao_id"] and local.municipio_ibge and local.uf:
        repo.completar_municipio_do_orgao(concurso["orgao_id"], local.uf, local.municipio_ibge)

    sem_area = 0
    for cargo in cargos_por_concurso.get(concurso["id"], []):
        area = classificadores.areas.classificar(cargo["nome"], cargo["especialidade"], orgao.nome if orgao else None)
        if not area.identificada:
            sem_area += 1
            # Aviso para afinar config/areas.yml: o cargo fica em OUTRAS até uma regra o reconhecer.
            log.info("cargo sem área identificada: %s / %s", cargo["nome"], cargo["especialidade"] or "-")
        escolaridade = cargo["escolaridade"] or classificadores.escolaridade.inferir(
            cargo["nome"], cargo["especialidade"]
        )
        alterado |= repo.aplicar_classificacao_cargo(cargo["id"], area.codigo, escolaridade)
    return alterado, local.abrangencia is not None, sem_area
