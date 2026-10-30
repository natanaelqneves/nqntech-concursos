"""Etapa 6: resumo por regras, campos desnormalizados para o site, slug estável e publicação.

Publicado = tem o mínimo para a página (slug, abrangência, resumo) E é oportunidade (seção 4.3). Concurso que
deixa de ser oportunidade sai do site na mesma execução; o slug fica, para voltar à mesma URL se reabrir.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from coletor.db import Linha, Repositorio
from coletor.pipeline.comum import ResumoEtapa, agora, hoje
from coletor.resumo import DadosConcurso, e_oportunidade, gerar_resumo, gerar_slug
from coletor.resumo.gerador import ORDEM_NIVEIS

log = logging.getLogger(__name__)


def dados_do_concurso(linha: Linha) -> DadosConcurso:
    salario_max = linha["cargos_salario_max"]
    return DadosConcurso(
        titulo=linha["titulo"],
        situacao=linha["situacao"],
        banca=linha["banca"],
        orgao=linha["orgao"],
        abrangencia=linha["abrangencia"],
        uf=linha["uf"],
        municipio=linha["municipio"],
        ano=linha["ano"],
        total_vagas=linha["cargos_vagas"],
        cadastro_reserva=bool(linha["cargos_reserva"]),
        salario_min=linha["cargos_salario_min"],
        salario_max=Decimal(salario_max) if salario_max is not None else None,
        escolaridades=tuple(linha["cargos_escolaridades"]),
        areas=tuple(linha["cargos_areas"]),
        inscricao_inicio=linha["inscricao_inicio"],
        inscricao_fim=linha["inscricao_fim"],
        data_prova=linha["data_prova"],
        taxa_min=linha["taxa_min"],
        taxa_max=linha["taxa_max"],
        isencoes=tuple(linha["isencoes"]),
        isencao_fim=linha["isencao_fim"],
        tem_avisos=bool(linha["tem_avisos"]),
        unificado=bool(linha["unificado"]),
    )


def executar_resumo(repo: Repositorio) -> ResumoEtapa:
    inicio = agora()
    dia = hoje()
    concursos = repo.concursos_para_resumir()
    ocupados = repo.slugs_ocupados()
    repo.conn.commit()

    alterados = 0
    publicados = 0
    falhas: list[str] = []
    for linha in concursos:
        try:
            dados = dados_do_concurso(linha)
            slug = linha["slug"]
            if slug is None:
                slug = gerar_slug(dados, ocupados, linha["ano_criacao"] or dia.year)
                ocupados.add(slug)
            resumo = gerar_resumo(dados, dia)
            oportunidade = e_oportunidade(linha["situacao"], linha["isencao_fim"], dia)
            publicado = linha["abrangencia"] is not None and oportunidade
            campos = {
                "slug": slug,
                "total_vagas": dados.total_vagas,
                "salario_max": dados.salario_max,
                "escolaridades": [n for n in ORDEM_NIVEIS if n in dados.escolaridades],
                "areas": sorted(dados.areas),
                "resumo": resumo,
                "publicado": publicado,
            }
            with repo.transacao():
                alterados += repo.aplicar_resumo(linha["id"], campos)
            publicados += publicado
        except Exception as erro:
            log.exception("falha ao resumir o concurso %d", linha["id"])
            falhas.append(f"concurso {linha['id']}: {erro}")

    log.info("resumo: %d concursos, %d alterados, %d publicados no site", len(concursos), alterados, publicados)
    status = "SUCESSO" if not falhas else ("FALHA" if len(falhas) == len(concursos) else "PARCIAL")
    mensagem = "; ".join(falhas[:10]) or None
    repo.registrar_execucao("RESUMO", inicio, status, alterados, mensagem)
    return ResumoEtapa("RESUMO", status, alterados, mensagem)
