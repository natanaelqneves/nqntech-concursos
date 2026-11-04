"""Busca assistida de concursos abertos das bancas sem coleta automática (roda no computador do administrador).

O Gemini usa a Busca Google (grounding) e devolve sugestões; o script nunca acessa o site das bancas, e quem abre
os links e baixa os PDFs é a pessoa, no navegador (depois: `importar-pdfs`). Contra links inventados:
- cada sugestão diz se o domínio do link apareceu nas fontes que a busca devolveu ("confirmado pela busca");
- e se o domínio é da banca ou de órgão público ("oficial"). Nada daqui vai para o banco nem para o site.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from coletor.ia.provedores import GEMINI_URL, FalhaIA, LimiteAtingido

log = logging.getLogger(__name__)

DOMINIOS_BANCAS: Mapping[str, tuple[str, ...]] = {
    "FCC": ("concursosfcc.com.br", "fcc.org.br"),
    "CESGRANRIO": ("cesgranrio.org.br",),
    "VUNESP": ("vunesp.com.br",),
    "IBFC": ("ibfc.org.br",),
    "CONSULPLAN": ("institutoconsulplan.org.br", "consulplan.net"),
    "QUADRIX": ("quadrix.org.br",),
    "IDECAN": ("idecan.org.br",),
    "AOCP": ("institutoaocp.org.br",),
    "FUNDEP": ("gestaodeconcursos.com.br", "fundep.ufmg.br", "fundep.selecao.net.br"),
    "FUMARC": ("fumarc.com.br",),
    "CPCON": ("cpcon.uepb.edu.br", "uepb.edu.br"),
    "SELECON": ("selecon.org.br",),
}
# Sites de órgãos públicos também contam como oficiais (o edital costuma estar lá).
_SUFIXOS_PUBLICOS = (".gov.br", ".leg.br", ".jus.br", ".mp.br", ".def.br", ".edu.br")

INSTRUCOES = """Você pesquisa concursos públicos brasileiros. Use a busca para encontrar concursos da banca {banca}
com INSCRIÇÕES ABERTAS hoje ({hoje}) ou com edital publicado e inscrições ainda por abrir, ou com prazo de pedido
de isenção da taxa em andamento. Ignore encerrados, resultados, gabaritos e convocações.
Responda SOMENTE com um array JSON (sem texto antes ou depois, sem markdown), no máximo {limite} itens, cada um:
{{"orgao": "...", "cargos": "...", "inscricoes_ate": "AAAA-MM-DD ou null", "isencao_ate": "AAAA-MM-DD ou null",
"link": "URL da página oficial do concurso ou do edital (https)", "observacao": "..."}}
Use apenas links que apareceram nos resultados da busca; nunca invente URL. Se não achar nada, responda []."""


@dataclass(frozen=True)
class Sugestao:
    banca: str
    orgao: str
    cargos: str
    inscricoes_ate: str | None
    isencao_ate: str | None
    link: str
    oficial: bool
    confirmado: bool
    observacao: str


def dominio(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def eh_oficial(url: str, banca: str) -> bool:
    host = dominio(url)
    dominios = DOMINIOS_BANCAS.get(banca, ())
    return any(host == d or host.endswith("." + d) for d in dominios) or host.endswith(_SUFIXOS_PUBLICOS)


def dominios_das_fontes(metadados: Mapping[str, Any]) -> set[str]:
    """Domínios das fontes da busca. O `uri` costuma ser um redirecionamento do Google; o `title` traz o domínio."""
    achados: set[str] = set()
    for chunk in metadados.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        for valor in (web.get("title") or "", dominio(web.get("uri") or "")):
            valor = valor.strip().lower().removeprefix("www.")
            if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", valor) and "vertexaisearch" not in valor:
                achados.add(valor)
    return achados


def _array_json(texto: str) -> list[Any]:
    inicio, fim = texto.find("["), texto.rfind("]")
    if inicio < 0 or fim < inicio:
        raise FalhaIA("a resposta não trouxe um array JSON")
    try:
        dados = json.loads(texto[inicio : fim + 1])
    except json.JSONDecodeError as erro:
        raise FalhaIA(f"JSON inválido na resposta ({erro})") from erro
    if not isinstance(dados, list):
        raise FalhaIA("a resposta não é um array")
    return dados


def _data(valor: Any) -> str | None:
    texto = str(valor or "").strip()
    return texto if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto) else None


def interpretar(banca: str, texto: str, metadados: Mapping[str, Any]) -> list[Sugestao]:
    fontes = dominios_das_fontes(metadados)
    sugestoes: list[Sugestao] = []
    for item in _array_json(texto):
        if not isinstance(item, dict):
            continue
        link = str(item.get("link") or "").strip()
        if not re.fullmatch(r"https://[^\s<>\"']{4,500}", link):
            continue  # sem link https não há o que conferir
        host = dominio(link)
        sugestoes.append(
            Sugestao(
                banca=banca,
                orgao=str(item.get("orgao") or "").strip()[:200] or "?",
                cargos=str(item.get("cargos") or "").strip()[:300],
                inscricoes_ate=_data(item.get("inscricoes_ate")),
                isencao_ate=_data(item.get("isencao_ate")),
                link=link,
                oficial=eh_oficial(link, banca),
                confirmado=any(host == f or host.endswith("." + f) or f.endswith("." + host) for f in fontes),
                observacao=str(item.get("observacao") or "").strip()[:300],
            )
        )
    return sugestoes


class BuscaGemini:
    def __init__(self, chave: str, modelo: str, http: httpx.Client) -> None:
        self._chave = chave
        self._modelo = modelo
        self._http = http

    def buscar(self, banca: str, hoje: date, limite: int = 15) -> list[Sugestao]:
        pedido = INSTRUCOES.format(banca=banca, hoje=hoje, limite=limite)
        corpo = {
            "contents": [{"role": "user", "parts": [{"text": pedido}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 8192},
        }
        resposta = self._http.post(GEMINI_URL.format(modelo=self._modelo), json=corpo,
                                   headers={"x-goog-api-key": self._chave})  # fmt: skip
        if resposta.status_code == 429:
            raise LimiteAtingido("gemini: limite da busca atingido (429)")
        if resposta.status_code >= 400:
            raise FalhaIA(f"gemini: HTTP {resposta.status_code}: {resposta.text[:300]}")
        try:
            candidato = resposta.json()["candidates"][0]
            texto = "".join(p.get("text", "") for p in candidato["content"]["parts"])
        except (KeyError, IndexError, TypeError, ValueError) as erro:
            raise FalhaIA(f"gemini: resposta sem conteúdo ({erro})") from erro
        return interpretar(banca, texto, candidato.get("groundingMetadata") or {})


def gravar(sugestoes: Sequence[Sugestao], pasta: Path, hoje: date) -> tuple[Path, Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    base = pasta / f"concursos-sugeridos-{hoje.isoformat()}"
    campos = list(Sugestao.__dataclass_fields__)
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos, delimiter=";")
        escritor.writeheader()
        for s in sugestoes:
            escritor.writerow({c: getattr(s, c) for c in campos})
    linhas = [f"# Concursos sugeridos pela busca ({hoje:%d/%m/%Y})", "",
              "Confira cada link no navegador antes de baixar. ✅ oficial = domínio da banca ou de órgão público; "
              "🔎 = domínio apareceu nas fontes da busca. Sem 🔎, o link pode ter sido inventado.", ""]  # fmt: skip
    for banca in dict.fromkeys(s.banca for s in sugestoes):
        linhas += [f"## {banca}", ""]
        for s in (x for x in sugestoes if x.banca == banca):
            marcas = ("✅" if s.oficial else "⚠️ não oficial") + (" 🔎" if s.confirmado else "")
            prazos = ", ".join(p for p in (
                f"inscrições até {s.inscricoes_ate}" if s.inscricoes_ate else "",
                f"isenção até {s.isencao_ate}" if s.isencao_ate else "") if p)  # fmt: skip
            linhas.append(f"- {marcas} **{s.orgao}** — {s.cargos or 'cargos no edital'}"
                          f"{' — ' + prazos if prazos else ''}  \n  {s.link}")  # fmt: skip
        linhas.append("")
    base.with_suffix(".md").write_text("\n".join(linhas), encoding="utf-8")
    return base.with_suffix(".csv"), base.with_suffix(".md")


def buscar_bancas(busca: BuscaGemini, bancas: Iterable[str], hoje: date) -> tuple[list[Sugestao], list[str]]:
    sugestoes: list[Sugestao] = []
    falhas: list[str] = []
    for banca in bancas:
        try:
            achadas = busca.buscar(banca, hoje)
        except LimiteAtingido as erro:
            falhas.append(f"{banca}: {erro}")
            break  # cota do dia acabou: não adianta insistir
        except (FalhaIA, httpx.HTTPError) as erro:
            falhas.append(f"{banca}: {erro}")
            continue
        log.info("%s: %d sugestões (%d oficiais)", banca, len(achadas), sum(s.oficial for s in achadas))
        sugestoes += achadas
    vistos: set[str] = set()
    unicas = [s for s in sugestoes if not (s.link in vistos or vistos.add(s.link))]
    return unicas, falhas
