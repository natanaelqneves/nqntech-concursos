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
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from coletor.ia.provedores import GEMINI_URL, OPENROUTER_URL, FalhaIA, LimiteAtingido

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


# Ordem: os "Lite" têm cota diária bem maior na faixa gratuita (500/dia) e vão primeiro; quem esgotar sai da rodada.
# (04/11/2026: gemini-3-flash e gemini-2.5-* respondem 404 para contas novas e saíram da lista.)
MODELOS_BUSCA_PADRAO = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
)
OPENROUTER_MODELO_BUSCA = "openrouter/free"


def _motivo(resposta: httpx.Response) -> str:
    """Mensagem do provedor para o erro (qual cota estourou, modelo inexistente etc.)."""
    try:
        erro = resposta.json().get("error") or {}
    except ValueError:
        return resposta.text[:300]
    return str(erro.get("message") if isinstance(erro, dict) else erro)[:300]


class Buscador(Protocol):
    nome: str

    def buscar(self, banca: str, hoje: date, limite: int = 15) -> list[Sugestao]:
        """Sugestões da banca; LimiteAtingido tira o buscador da rodada, FalhaIA passa a banca ao próximo."""
        ...


class _Ritmo:
    """Intervalo mínimo entre chamadas do mesmo buscador (cabe no limite por minuto da faixa gratuita)."""

    def __init__(self, intervalo_s: float, dormir: Callable[[float], None], relogio: Callable[[], float]) -> None:
        self._intervalo_s, self._dormir, self._relogio = intervalo_s, dormir, relogio
        self._ultima: float | None = None

    def esperar(self) -> None:
        if self._ultima is not None:
            falta = self._ultima + self._intervalo_s - self._relogio()
            if falta > 0:
                self._dormir(falta)
        self._ultima = self._relogio()


class BuscaGemini:
    def __init__(self, chave: str, modelo: str, http: httpx.Client, espera_429_s: float = 65.0,
                 intervalo_s: float = 13.0, dormir: Callable[[float], None] = time.sleep,
                 relogio: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self._chave = chave
        self._modelo = modelo
        self._http = http
        self._espera_429_s = espera_429_s
        self._dormir = dormir
        self._ritmo = _Ritmo(intervalo_s, dormir, relogio)
        self.nome = f"gemini:{modelo}"

    def buscar(self, banca: str, hoje: date, limite: int = 15) -> list[Sugestao]:
        pedido = INSTRUCOES.format(banca=banca, hoje=hoje, limite=limite)
        corpo = {
            "contents": [{"role": "user", "parts": [{"text": pedido}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 8192},
        }
        resposta = self._postar(corpo)
        if resposta.status_code == 429 and "minute" in _motivo(resposta).lower():
            self._dormir(self._espera_429_s)  # limite por minuto passa com uma espera; o diário, não
            resposta = self._postar(corpo)
        if resposta.status_code in (404, 429) or (resposta.status_code == 400 and "not" in _motivo(resposta)):
            raise LimiteAtingido(f"{self.nome}: HTTP {resposta.status_code}: {_motivo(resposta)}")
        if resposta.status_code >= 400:
            raise FalhaIA(f"{self.nome}: HTTP {resposta.status_code}: {_motivo(resposta)}")
        try:
            candidato = resposta.json()["candidates"][0]
            texto = "".join(p.get("text", "") for p in candidato["content"]["parts"])
        except (KeyError, IndexError, TypeError, ValueError) as erro:
            raise FalhaIA(f"{self.nome}: resposta sem conteúdo ({erro})") from erro
        return interpretar(banca, texto, candidato.get("groundingMetadata") or {})

    def _postar(self, corpo: Mapping[str, Any]) -> httpx.Response:
        self._ritmo.esperar()
        return self._http.post(GEMINI_URL.format(modelo=self._modelo), json=corpo,
                               headers={"x-goog-api-key": self._chave})  # fmt: skip


class BuscaOpenRouter:
    """Reserva: plugin de busca na web do OpenRouter (cobra créditos da conta; sem crédito vem 402 e ele sai)."""

    def __init__(self, chave: str, modelo: str, http: httpx.Client, intervalo_s: float = 4.0,
                 dormir: Callable[[float], None] = time.sleep,
                 relogio: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self._chave, self._modelo, self._http = chave, modelo, http
        self._ritmo = _Ritmo(intervalo_s, dormir, relogio)
        self.nome = f"openrouter:{modelo}"

    def buscar(self, banca: str, hoje: date, limite: int = 15) -> list[Sugestao]:
        self._ritmo.esperar()
        corpo = {
            "model": self._modelo,
            "temperature": 0,
            "messages": [{"role": "user", "content": INSTRUCOES.format(banca=banca, hoje=hoje, limite=limite)}],
            "plugins": [{"id": "web", "max_results": 8}],
        }
        resposta = self._http.post(OPENROUTER_URL, json=corpo, headers={
            "Authorization": f"Bearer {self._chave}", "X-Title": "NqnTech Concursos"})  # fmt: skip
        if resposta.status_code in (402, 404, 429):
            raise LimiteAtingido(f"{self.nome}: HTTP {resposta.status_code}: {_motivo(resposta)}")
        if resposta.status_code >= 400:
            raise FalhaIA(f"{self.nome}: HTTP {resposta.status_code}: {_motivo(resposta)}")
        try:
            mensagem = resposta.json()["choices"][0]["message"]
            texto = mensagem.get("content") or ""
        except (KeyError, IndexError, TypeError, ValueError) as erro:
            raise FalhaIA(f"{self.nome}: resposta sem conteúdo ({erro})") from erro
        # As citações da busca viram o mesmo formato de fontes do Gemini, para a marca 🔎.
        fontes = [{"web": {"uri": (a.get("url_citation") or {}).get("url", ""), "title": ""}}
                  for a in mensagem.get("annotations") or [] if a.get("type") == "url_citation"]  # fmt: skip
        return interpretar(banca, texto, {"groundingChunks": fontes})


def criar_buscadores(env: Mapping[str, str], http: httpx.Client) -> list[Buscador]:
    buscadores: list[Buscador] = []
    if env.get("GEMINI_API_KEY"):
        modelos = [m.strip() for m in (env.get("COLETOR_BUSCA_MODELOS") or "").split(",") if m.strip()]
        for modelo in modelos or MODELOS_BUSCA_PADRAO:
            buscadores.append(BuscaGemini(env["GEMINI_API_KEY"], modelo, http))
    if env.get("OPENROUTER_API_KEY"):
        modelo = env.get("COLETOR_BUSCA_OPENROUTER_MODELO") or OPENROUTER_MODELO_BUSCA
        buscadores.append(BuscaOpenRouter(env["OPENROUTER_API_KEY"], modelo, http))
    return buscadores


def gravar(sugestoes: Sequence[Sugestao], pasta: Path, hoje: date, falhas: Sequence[str] = ()) -> tuple[Path, Path]:
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
    if falhas:
        linhas += ["## Falhas da busca", "", *(f"- {f}" for f in falhas), ""]
    if not sugestoes and not falhas:
        linhas += ["Nenhum concurso aberto encontrado hoje.", ""]
    base.with_suffix(".md").write_text("\n".join(linhas), encoding="utf-8")
    return base.with_suffix(".csv"), base.with_suffix(".md")


def buscar_bancas(
    buscadores: Sequence[Buscador], bancas: Iterable[str], hoje: date
) -> tuple[list[Sugestao], list[str]]:
    """Cada banca vai ao primeiro buscador disponível; se ele esgotar ou falhar, a mesma banca tenta o próximo."""
    ativos = list(buscadores)
    sugestoes: list[Sugestao] = []
    falhas: list[str] = []
    for banca in bancas:
        achadas: list[Sugestao] | None = None
        for buscador in list(ativos):
            try:
                achadas = buscador.buscar(banca, hoje)
            except LimiteAtingido as erro:
                log.warning("%s; seguindo para o próximo", erro)
                falhas.append(f"{banca}: {erro} (saiu da rodada)")
                ativos.remove(buscador)
                continue
            except (FalhaIA, httpx.HTTPError) as erro:
                log.warning("%s: %s", banca, erro)
                falhas.append(f"{banca}: {erro}")
                continue
            log.info("%s via %s: %d sugestões (%d oficiais)", banca, buscador.nome, len(achadas),
                     sum(s.oficial for s in achadas))  # fmt: skip
            break
        if achadas is None:
            if not ativos:
                falhas.append("todos os provedores de busca esgotaram a cota de hoje")
                break
            continue
        sugestoes += achadas
    vistos: set[str] = set()
    unicas = [s for s in sugestoes if not (s.link in vistos or vistos.add(s.link))]
    return unicas, falhas
