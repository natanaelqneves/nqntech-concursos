"""Fonte Instituto AOCP: API JSON pública que alimenta o próprio site (www.institutoaocp.org.br/api/concursos).

Observado em 04/11/2026 (sondagem `captura-sondagem`, a partir do GitHub Actions): uma lista com todos os processos
e `status` FINISHED, RESULT_AVAILABLE, IN_PROGRESS ou SUBSCRIBE (inscrições abertas); traz órgão, chamada, tipo,
início/fim das inscrições e data da prova. robots.txt inexistente (404). Os editais não vêm na API (o site legado
os mostra em outra plataforma), então a AOCP entra só com os dados da listagem e o link oficial.

Só SUBSCRIBE (e status de "novos", se aparecerem) vira sinal: encerrados e em andamento nem são considerados.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any

from coletor.extratores.base import CargoExtraido
from coletor.fontes.base import DadosEstruturados, ResultadoDescoberta, SinalDescoberta
from coletor.http_cliente import ClienteHttp, ErroHttp
from coletor.texto import colapsar_espacos, titulo_portugues

log = logging.getLogger(__name__)

API = "https://www.institutoaocp.org.br/api/concursos"
PAGINA = "https://www.institutoaocp.org.br/concursos/{id}"
STATUS_ABERTOS = frozenset({"SUBSCRIBE"})
STATUS_NOVOS = frozenset({"NEW", "COMING_SOON", "SOON", "NOVOS"})
AVISO = "cargos, vagas, salários e taxa só no edital: confira o edital"

_SIGLA_E_NOME = re.compile(r"^(?P<sigla>[A-ZÀ-Ü0-9/.\-]{2,20})\s+-\s+(?P<nome>.+)$")
# "Contador - Processo Seletivo Simplificado ..." → cargo antes do primeiro " - ", se não for o próprio tipo.
_CARGO_NA_CHAMADA = re.compile(r"^(?P<cargo>[^–\-]{3,60}?)\s+[–-]\s+(?:processo seletivo|concurso)", re.IGNORECASE)


def _data(valor: Any) -> date | None:
    try:
        return datetime.strptime(str(valor).strip()[:10], "%d/%m/%Y").date() if valor else None
    except ValueError:
        return None


def orgao(nome: str) -> tuple[str, str | None]:
    """'PMPE - POLÍCIA MILITAR DE PERNAMBUCO' → ('Polícia Militar de Pernambuco', 'PMPE')."""
    nome = re.sub(r"\s+-\s+[A-Z]{2}$", "", colapsar_espacos(nome))  # "... DA BAHIA - BA": a UF já está no nome
    m = _SIGLA_E_NOME.match(nome)
    if m is None:
        return titulo_portugues(nome), None
    return titulo_portugues(m.group("nome")), m.group("sigla")


def parse_concurso(item: dict[str, Any]) -> SinalDescoberta | None:
    status = str(item.get("status") or "").upper()
    if status not in STATUS_ABERTOS | STATUS_NOVOS:
        return None
    ident = str(item.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", ident):
        return None
    nome_orgao, sigla = orgao(str(item.get("nome") or ""))
    chamada = colapsar_espacos(str(item.get("chamada") or ""))
    inicio, fim = _data(item.get("dataInicioInscricao")), _data(item.get("dataInscricao"))
    avisos = [AVISO]
    if inicio and fim and fim < inicio:  # a API já trouxe fim em 2020 para inscrição aberta em 2026
        avisos.append("período de inscrição incoerente na página da banca: confira o edital")
        fim = None
    cargo = _CARGO_NA_CHAMADA.match(chamada)
    cargos = (CargoExtraido(nome=titulo_portugues(cargo.group("cargo").strip())),) if cargo else ()
    situacao = "INSCRICOES_ABERTAS" if status in STATUS_ABERTOS else "PREVISTO"
    titulo = f"{nome_orgao} – {cargo.group('cargo').strip()}" if cargo else nome_orgao
    numero = colapsar_espacos(str(item.get("numeroEdital") or "")) or None
    return SinalDescoberta(
        titulo=titulo,
        url=PAGINA.format(id=ident),
        data_publicacao=inicio,
        payload={
            "titulo": titulo,
            "situacao_site": status,
            "descricao": chamada[:1000],
            "link_inscricao": PAGINA.format(id=ident) if situacao == "INSCRICOES_ABERTAS" else None,
            "arquivos": [],
            "sigla_orgao": sigla,
            "tipo_processo": item.get("tipoProcesso"),
        },
        estruturado=DadosEstruturados(
            orgao=nome_orgao,
            numero_edital=numero[:40] if numero else None,
            situacao=situacao,
            inscricao_inicio=inicio,
            inscricao_fim=fim,
            data_prova=_data(item.get("dataProva")),
            cargos=cargos,
            avisos=tuple(avisos),
        ),
    )


class FonteAOCP:
    nome = "aocp"
    dominios = frozenset({"www.institutoaocp.org.br"})

    def descobrir(self, http: ClienteHttp, pular: frozenset[str] = frozenset()) -> ResultadoDescoberta:
        try:
            lista = json.loads(http.obter_texto(API))
        except json.JSONDecodeError as erro:
            raise ErroHttp(f"API da AOCP não devolveu JSON: {erro}") from erro
        if not isinstance(lista, list):
            raise ErroHttp("API da AOCP mudou de formato (esperava uma lista)")
        sinais = [s for s in (parse_concurso(i) for i in lista if isinstance(i, dict)) if s and s.url not in pular]
        log.info("AOCP: %d processos na API, %d com inscrições abertas ou novos", len(lista), len(sinais))
        return ResultadoDescoberta(tuple(sinais))
