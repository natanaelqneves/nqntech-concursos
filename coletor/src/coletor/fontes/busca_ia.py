"""Fonte "busca-ia": cada concurso achado pela busca na web vira um sinal com o pré-cadastro (dados estruturados).

Daí em diante o caminho é o de qualquer fonte: vinculação (com deduplicação contra o que as outras fontes já
trouxeram), edital (baixado sozinho ou enviado pelo Drive), leitura do edital, classificação, resumo e site.
A fonte não acessa o site das bancas: quem pesquisa é a IA. O que fica de fora:
- página não confirmada pelas fontes da busca ou não oficial (link possivelmente inventado);
- concurso cujas inscrições já terminaram (a busca às vezes traz encerrados).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from coletor.extratores.base import CargoExtraido
from coletor.fontes.base import DadosEstruturados, ResultadoDescoberta, SinalDescoberta
from coletor.http_cliente import ClienteHttp
from coletor.ia.busca_web import AlvoBusca, Buscador, ResultadoAlvo, Sugestao, buscar_alvos, eh_oficial

log = logging.getLogger(__name__)

NOME_FONTE = "busca-ia"
AVISO_BUSCA = "dados preliminares da busca na web: confira o edital"


@dataclass(frozen=True)
class AgendaBusca:
    """Quais alvos estão vencidos e onde registrar cada busca (o banco, via repositório)."""

    vencidos: Callable[[Sequence[str]], list[str]]
    registrar: Callable[[ResultadoAlvo], None]


def aceitar(sugestao: Sugestao, hoje: date) -> str | None:
    """Motivo para descartar a sugestão, ou None se ela vira sinal."""
    if not sugestao.confirmado:
        return "página não apareceu nas fontes da busca"
    if not sugestao.oficial:
        return "página não é da banca nem de órgão público"
    if sugestao.inscricoes_fim is not None and sugestao.inscricoes_fim < hoje and sugestao.situacao == "ABERTO":
        isencao_em_curso = sugestao.isencao_fim is not None and sugestao.isencao_fim >= hoje
        if not isencao_em_curso:
            return "inscrições já encerradas"
    return None


def sinal_da_sugestao(sugestao: Sugestao, hoje: date, dominios_banca: Sequence[str] = ()) -> SinalDescoberta:
    previsto = sugestao.situacao == "PREVISTO"
    titulo = sugestao.orgao if not sugestao.ano else f"{sugestao.orgao} {sugestao.ano}"
    arquivos = []
    if sugestao.link_edital and not previsto:
        arquivos.append({
            "titulo": "Edital de abertura",
            "url": sugestao.link_edital,
            "data": None,
            "pdf": True,
            "tipo": "EDITAL",
            "oficial": eh_oficial(sugestao.link_edital, dominios_banca),
        })  # fmt: skip
    escolaridade_unica = sugestao.escolaridades[0] if len(sugestao.escolaridades) == 1 else None
    estruturado = DadosEstruturados(
        orgao=sugestao.orgao,
        esfera=sugestao.esfera,
        uf=None if sugestao.esfera == "FEDERAL" else sugestao.uf,
        municipio=sugestao.municipio if sugestao.esfera == "MUNICIPAL" else None,
        ano=sugestao.ano,
        situacao="PREVISTO" if previsto else "INSCRICOES_ABERTAS",
        inscricao_inicio=sugestao.inscricoes_inicio,
        inscricao_fim=sugestao.inscricoes_fim,
        data_prova=sugestao.data_prova,
        taxa_max=sugestao.taxa_max,
        cargos=tuple(
            CargoExtraido(
                nome=nome,
                escolaridade=escolaridade_unica,
                salario=sugestao.salario_max if len(sugestao.cargos) == 1 else None,
            )
            for nome in sugestao.cargos
        ),
        avisos=(AVISO_BUSCA,),
    )
    return SinalDescoberta(
        titulo=titulo,
        url=sugestao.link_pagina,
        data_publicacao=hoje,
        payload={
            "titulo": titulo,
            "situacao_site": "PREVISTO" if previsto else "ABERTO",
            "descricao": f"busca na web ({sugestao.alvo})",
            "link_inscricao": None,
            "arquivos": arquivos,
            "banca_sigla": sugestao.banca,
            "busca": sugestao.para_json(),
        },
        estruturado=estruturado,
    )


class FonteBuscaIA:
    nome = NOME_FONTE
    dominios: frozenset[str] = frozenset()  # não acessa sites: a pesquisa é feita pelo provedor de IA

    def __init__(
        self,
        criar_buscadores: Callable[[], tuple[Sequence[Buscador], Callable[[], None]]],
        alvos: Sequence[AlvoBusca],
        agenda: AgendaBusca,
        hoje: Callable[[], date],
        max_alvos: int,
    ) -> None:
        self._criar_buscadores = criar_buscadores
        self._alvos = list(alvos)
        self._agenda = agenda
        self._hoje = hoje
        self._max_alvos = max_alvos
        self._dominios_banca: Mapping[str, Sequence[str]] = {a.banca: a.dominios for a in alvos if a.banca}

    def descobrir(self, http: ClienteHttp, pular: frozenset[str] = frozenset()) -> ResultadoDescoberta:
        codigos = self._agenda.vencidos([a.codigo for a in self._alvos])[: self._max_alvos]
        if not codigos:
            log.info("busca-ia: nenhum alvo vencido nesta execução")
            return ResultadoDescoberta(())
        alvos = [a for a in self._alvos if a.codigo in set(codigos)]
        dia = self._hoje()
        buscadores, fechar = self._criar_buscadores()
        try:
            if not buscadores:
                raise RuntimeError("busca-ia sem provedor: defina GEMINI_API_KEY e/ou OPENROUTER_API_KEY")
            resultados = buscar_alvos(buscadores, alvos, dia, self._dominios_banca)
        finally:
            fechar()
        sinais: list[SinalDescoberta] = []
        falhas: list[str] = []
        for resultado in resultados:
            self._agenda.registrar(resultado)
            if resultado.erro:
                falhas.append(f"{resultado.alvo.codigo}: {resultado.erro}")
            for sugestao in resultado.sugestoes:
                motivo = aceitar(sugestao, dia)
                if motivo:
                    log.info("busca-ia: descartado %s (%s): %s", sugestao.orgao, sugestao.link_pagina, motivo)
                    continue
                sinais.append(sinal_da_sugestao(sugestao, dia, self._dominios_banca.get(sugestao.banca or "", ())))
        sem_cota = len(alvos) - len(resultados)
        if sem_cota:  # cota esgotada não é falha: os alvos continuam vencidos e entram na próxima execução
            log.warning("busca-ia: %d alvo(s) sem busca nesta execução (provedores sem cota)", sem_cota)
        vistos: set[str] = set()
        unicos = tuple(s for s in sinais if not (s.url in vistos or vistos.add(s.url)))
        return ResultadoDescoberta(unicos, tuple(falhas))
