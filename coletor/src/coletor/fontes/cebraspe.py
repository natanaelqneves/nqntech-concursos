"""Fonte Cebraspe: API JSON pública usada pelo próprio app de concursos (www.cebraspe.org.br/concursos/).

Rotas observadas em 04/11/2026 (sondagem `captura-cebraspe`, a partir do GitHub Actions):
- `apis.cebraspe.org.br/cebraspe/eventos/tipo/concursos/fase/{novos|inscricoes-abertas}`: lista por fase, já
  filtrada pela banca (encerrados e em andamento nem são pedidos);
- `apis.cebraspe.org.br/cebraspe/eventos/{eventoURL}`: detalhe com período de inscrição, cargos e arquivos;
- PDFs em `cdn.cebraspe.org.br/concursos/{eventoURL}/arquivos/{nomeArquivo}` (ou `cdn.../{nomeArquivo}` quando
  `isGuid`), mesma montagem do app.
robots.txt: www libera tudo; apis e cdn não têm robots.txt (404) em 04/11/2026.

Só o edital de abertura vai para download (de preferência a versão "atualizado conforme retificações"): todos os
documentos da Cebraspe começam com "Edital nº N" (retificação, sorteio, suspensão), então o tipo é decidido aqui.
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
from coletor.texto import colapsar_espacos, normalizar, titulo_portugues, todas_as_datas

log = logging.getLogger(__name__)

API = "https://apis.cebraspe.org.br/cebraspe/eventos"
CDN = "https://cdn.cebraspe.org.br/"
PAGINA = "https://www.cebraspe.org.br/concursos/{identificador}"
FASES = {"inscricoes-abertas": "INSCRICOES_ABERTAS", "novos": "PREVISTO"}

_CARGO = re.compile(r"^CARGO\s*\d+\s*:\s*(?P<nome>.+?)(?:\s*[–-]\s*(?P<resto>(?:ESPECIALIDADE|[ÁA]REA|PERFIL).*))?$")
_ROTULOS = re.compile(r"\s*[–-]?\s*(?:ESPECIALIDADE|[ÁA]REA|PERFIL)\s*:\s*", re.IGNORECASE)
_ABERTURA = re.compile(r"^edital n\W*o?\s*0*1\b.*\babertura\b")
_SUSPENSO = re.compile(r"\b(suspens|cancelament|anulac)")


def _json(http: ClienteHttp, url: str) -> Any:
    try:
        return json.loads(http.obter_texto(url))
    except json.JSONDecodeError as erro:
        raise ErroHttp(f"resposta não é JSON em {url}: {erro}") from erro


def identificadores(lista: Any) -> list[str]:
    """`eventoURL` de cada concurso da resposta da lista (agrupada por fase)."""
    saida: list[str] = []
    for grupo in lista if isinstance(lista, list) else []:
        for evento in (grupo or {}).get("eventos") or []:
            ident = evento.get("eventoURL") if isinstance(evento, dict) else None
            if (
                ident
                and evento.get("eventoTipo", "concursos") == "concursos"
                and re.fullmatch(r"[A-Za-z0-9_-]+", ident)
            ):
                saida.append(ident)
    return list(dict.fromkeys(saida))


def link_arquivo(identificador: str, arquivo: dict[str, Any]) -> str:
    nome = str(arquivo.get("nomeArquivo") or "")
    return f"{CDN}{nome}" if arquivo.get("isGuid") else f"{CDN}concursos/{identificador}/arquivos/{nome}"


def edital_de_abertura(arquivos: list[dict[str, Any]]) -> dict[str, Any] | None:
    pdfs = [a for a in arquivos if str(a.get("tipoExtensaoArquivo", "")).endswith("pdf") and a.get("nomeArquivo")]
    abertura = [a for a in pdfs if _ABERTURA.search(normalizar(str(a.get("descricaoArquivo") or "")))]
    consolidado = [a for a in abertura if "atualizado" in normalizar(str(a.get("descricaoArquivo")))]
    return (consolidado or abertura or [None])[0]


def cargos(evento: dict[str, Any]) -> tuple[CargoExtraido, ...]:
    saida = []
    for item in evento.get("eventoCargos") or []:
        texto = colapsar_espacos(str((item or {}).get("area") or ""))
        m = _CARGO.match(texto)
        if m is None:
            continue  # ex.: "Provimento"/"Remoção" (cartórios) não são cargos
        partes = [p for p in _ROTULOS.split(m.group("resto") or "") if p.strip()]
        saida.append(
            CargoExtraido(
                nome=titulo_portugues(m.group("nome").strip(" –-")),
                especialidade=titulo_portugues(" – ".join(p.strip(" –-") for p in partes)) if partes else None,
            )
        )
    return tuple(saida)


def periodo(evento: dict[str, Any]) -> tuple[date | None, date | None]:
    datas = todas_as_datas(str(evento.get("periodoInscricao") or ""))
    return (datas[0], datas[1]) if len(datas) >= 2 else (None, None)


def parse_evento(evento: dict[str, Any], fase: str) -> SinalDescoberta | None:
    """Sinal do concurso, ou None se não for oportunidade (suspenso, cancelado) ou não tiver identificador."""
    ident = str(evento.get("eventoURL") or "")
    if not ident:
        return None
    arquivos = [a for a in evento.get("arquivosEdital") or [] if isinstance(a, dict)]
    pdfs = [a for a in arquivos if str(a.get("tipoExtensaoArquivo", "")).endswith("pdf")]
    if pdfs and _SUSPENSO.search(normalizar(str(pdfs[0].get("descricaoArquivo") or ""))):
        log.info("Cebraspe: %s suspenso/cancelado pela última publicação; ignorado", ident)
        return None

    nome = colapsar_espacos(str(evento.get("eventoNomeCompleto") or evento.get("eventoNomeAbreviado") or ident))
    inicio, fim = periodo(evento)
    abertura = edital_de_abertura(arquivos)
    arquivos_payload = []
    data_publicacao = None
    if abertura is not None:
        data_publicacao = _data(abertura.get("dataArquivoObj"))
        arquivos_payload.append(
            {
                "titulo": colapsar_espacos(str(abertura.get("descricaoArquivo"))),
                "url": link_arquivo(ident, abertura),
                "data": data_publicacao.isoformat() if data_publicacao else None,
                "pdf": True,
                "tipo": "EDITAL",
            }
        )
    situacao = "INSCRICOES_ABERTAS" if fim or fase == "inscricoes-abertas" else FASES.get(fase, "PREVISTO")
    estruturado = DadosEstruturados(
        ano=evento.get("eventoAno") if isinstance(evento.get("eventoAno"), int) else None,
        situacao=situacao,
        inscricao_inicio=inicio,
        inscricao_fim=fim,
        cargos=cargos(evento),
        avisos=("vagas, salários e datas completos só no edital: confira o PDF",),
    )
    pagina = PAGINA.format(identificador=ident)
    vagas, inscricoes = evento.get("eventoTotalVagas") or "?", evento.get("periodoInscricao") or ""
    descricao = colapsar_espacos(f"{vagas} vagas; {inscricoes}")
    return SinalDescoberta(
        titulo=titulo_portugues(nome),
        url=pagina,
        data_publicacao=data_publicacao,
        payload={
            "titulo": titulo_portugues(nome),
            "situacao_site": fase,
            "descricao": descricao,
            "link_inscricao": "https://areadocandidato.cebraspe.org.br/" if evento.get("isInscricaoAberta") else None,
            "arquivos": arquivos_payload,
        },
        estruturado=estruturado,
    )


def _data(valor: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(valor)).date() if valor else None
    except ValueError:
        return None


class FonteCebraspe:
    nome = "cebraspe"
    dominios = frozenset({"www.cebraspe.org.br", "apis.cebraspe.org.br", "cdn.cebraspe.org.br"})

    def descobrir(self, http: ClienteHttp, pular: frozenset[str] = frozenset()) -> ResultadoDescoberta:
        vistos: dict[str, str] = {}
        for fase in FASES:  # a primeira página é obrigatória: se a API falhar, a fonte inteira falha
            for ident in identificadores(_json(http, f"{API}/tipo/concursos/fase/{fase}")):
                vistos.setdefault(ident, fase)
        log.info("Cebraspe: %d concursos novos ou com inscrições abertas", len(vistos))
        sinais: list[SinalDescoberta] = []
        falhas: list[str] = []
        for ident, fase in vistos.items():
            if PAGINA.format(identificador=ident) in pular:
                continue
            try:
                sinal = parse_evento(_json(http, f"{API}/{ident}"), fase)
            except ErroHttp as erro:
                log.warning("Cebraspe: falha ao ler %s: %s", ident, erro)
                falhas.append(f"{ident}: {erro}")
                continue
            if sinal is not None:
                sinais.append(sinal)
        return ResultadoDescoberta(tuple(sinais), tuple(falhas))
