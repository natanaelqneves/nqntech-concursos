"""Busca na web com IA: primeira etapa do fluxo único (pré-cadastro de concursos abertos e previstos).

O Gemini usa a Busca Google (grounding) e devolve os dados que achou de cada concurso; o OpenRouter com o plugin de
busca é a reserva. Nada daqui é tomado como certo: o pré-cadastro só vai ao site como "previsto" (que não tem
edital) e, para concursos abertos, depois que o edital é lido; o edital sempre prevalece. Contra dados inventados:
- só fica a sugestão cuja página aparece nas fontes que a própria busca devolveu ("confirmada") e é oficial
  (domínio da banca ou de órgão público);
- datas, valores, UF e listas são validados; o que estiver fora de faixa vira nulo.
O link do PDF do edital pode ser de qualquer site: ele só serve para baixar e ler o texto.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
import yaml

from coletor.ia.provedores import GEMINI_URL, OPENROUTER_URL, FalhaIA, LimiteAtingido
from coletor.texto import UFS

log = logging.getLogger(__name__)

# Sites de órgãos públicos são oficiais para qualquer alvo (o edital costuma estar lá).
SUFIXOS_PUBLICOS = (".gov.br", ".leg.br", ".jus.br", ".mp.br", ".def.br", ".edu.br", ".mil.br")
_SIGLAS_UF = frozenset(UFS.values())
_ESFERAS = frozenset({"FEDERAL", "ESTADUAL", "MUNICIPAL"})
_ESCOLARIDADES = frozenset({"FUNDAMENTAL", "MEDIO", "TECNICO", "SUPERIOR"})
_LINK = re.compile(r"https://[^\s<>\"'\\]{4,500}")


@dataclass(frozen=True)
class AlvoBusca:
    codigo: str
    pesquisa: str
    banca: str | None = None
    dominios: tuple[str, ...] = ()


def carregar_alvos(caminho: Path) -> list[AlvoBusca]:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    alvos = [
        AlvoBusca(
            codigo=str(a["codigo"]).strip(),
            pesquisa=str(a["pesquisa"]).strip(),
            banca=(str(a["banca"]).strip().upper() if a.get("banca") else None),
            dominios=tuple(str(d).lower().strip() for d in a.get("dominios") or ()),
        )
        for a in dados.get("alvos") or ()
    ]
    codigos = [a.codigo for a in alvos]
    if len(codigos) != len(set(codigos)):
        raise ValueError(f"{caminho}: código de alvo repetido")
    return alvos


def dominios_por_banca(alvos: Iterable[AlvoBusca]) -> dict[str, tuple[str, ...]]:
    return {a.banca: a.dominios for a in alvos if a.banca}


INSTRUCOES = """Você pesquisa concursos públicos brasileiros. Use a busca para encontrar {pesquisa} que hoje ({hoje})
estejam em uma destas situações:
- "ABERTO": inscrições abertas, ou edital de abertura publicado com inscrições ainda por abrir;
- "PREVISTO": concurso autorizado oficialmente, ainda sem edital.
Ignore concursos encerrados e publicações de resultado, gabarito, convocação, homologação ou nomeação.
Responda SOMENTE com um array JSON (sem texto antes ou depois, sem markdown), no máximo {limite} itens, cada um:
{{"orgao": "nome completo do órgão", "banca": "sigla da banca organizadora ou null",
"esfera": "FEDERAL, ESTADUAL ou MUNICIPAL", "uf": "sigla da UF ou null (null para órgão federal nacional)",
"municipio": "nome do município ou null", "situacao": "ABERTO ou PREVISTO", "ano": 2026,
"inscricoes_inicio": "AAAA-MM-DD ou null", "inscricoes_fim": "AAAA-MM-DD ou null",
"isencao_inicio": "AAAA-MM-DD ou null", "isencao_fim": "AAAA-MM-DD ou null", "data_prova": "AAAA-MM-DD ou null",
"taxa_max": 120.00, "vagas": 50, "salario_max": 7526.14,
"cargos": ["nomes dos cargos, no máximo 15"], "escolaridades": ["FUNDAMENTAL", "MEDIO", "TECNICO", "SUPERIOR"],
"link_pagina": "https://... página OFICIAL do concurso (site da banca ou do órgão)",
"link_edital": "https://... endereço direto do PDF do edital de abertura (de qualquer site) ou null"}}
Use null para o que não souber; números sem separador de milhar. Use apenas links que apareceram nos resultados
da busca; nunca invente URL. Se não achar nada, responda []."""


@dataclass(frozen=True)
class Sugestao:
    alvo: str
    orgao: str
    banca: str | None
    esfera: str | None
    uf: str | None
    municipio: str | None
    situacao: str  # ABERTO ou PREVISTO
    ano: int | None
    inscricoes_inicio: date | None
    inscricoes_fim: date | None
    isencao_inicio: date | None
    isencao_fim: date | None
    data_prova: date | None
    taxa_max: Decimal | None
    vagas: int | None
    salario_max: Decimal | None
    cargos: tuple[str, ...]
    escolaridades: tuple[str, ...]
    link_pagina: str
    link_edital: str | None
    oficial: bool
    confirmado: bool

    def para_json(self) -> dict[str, Any]:
        def texto(valor: Any) -> Any:
            return None if valor is None else str(valor)

        return {
            "alvo": self.alvo,
            "orgao": self.orgao,
            "banca": self.banca,
            "esfera": self.esfera,
            "uf": self.uf,
            "municipio": self.municipio,
            "situacao": self.situacao,
            "ano": self.ano,
            "inscricoes_inicio": texto(self.inscricoes_inicio),
            "inscricoes_fim": texto(self.inscricoes_fim),
            "isencao_inicio": texto(self.isencao_inicio),
            "isencao_fim": texto(self.isencao_fim),
            "data_prova": texto(self.data_prova),
            "taxa_max": texto(self.taxa_max),
            "vagas": self.vagas,
            "salario_max": texto(self.salario_max),
            "cargos": list(self.cargos),
            "escolaridades": list(self.escolaridades),
            "link_pagina": self.link_pagina,
            "link_edital": self.link_edital,
        }


def dominio(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _no_dominio(host: str, dominios: Iterable[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in dominios)


def eh_oficial(url: str, dominios_banca: Iterable[str] = ()) -> bool:
    host = dominio(url)
    return _no_dominio(host, dominios_banca) or host.endswith(SUFIXOS_PUBLICOS)


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


def _data(valor: Any, hoje: date) -> date | None:
    texto = str(valor or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        return None
    try:
        dia = date.fromisoformat(texto)
    except ValueError:
        return None
    return dia if abs((dia - hoje).days) <= 730 else None  # fora de dois anos é erro de leitura


def _numero(valor: Any, minimo: Decimal, maximo: Decimal) -> Decimal | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = Decimal(str(valor).strip().replace("R$", "").strip())
    except InvalidOperation:
        return None
    return numero.quantize(Decimal("0.01")) if minimo <= numero <= maximo else None


def _inteiro(valor: Any, minimo: int, maximo: int) -> int | None:
    if isinstance(valor, bool):
        return None
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if minimo <= numero <= maximo else None


def _texto(valor: Any, maximo: int) -> str | None:
    texto = re.sub(r"\s+", " ", str(valor or "")).strip()
    return texto[:maximo] if texto and texto.lower() != "null" else None


def _link(valor: Any) -> str | None:
    texto = str(valor or "").strip()
    return texto if _LINK.fullmatch(texto) else None


def interpretar(
    alvo: AlvoBusca,
    texto: str,
    metadados: Mapping[str, Any],
    hoje: date,
    dominios_banca: Mapping[str, Sequence[str]] | None = None,
) -> list[Sugestao]:
    """Sugestões válidas da resposta. `dominios_banca` dá os sites oficiais da banca citada em cada item."""
    fontes = dominios_das_fontes(metadados)
    dominios_banca = dominios_banca or {}
    sugestoes: list[Sugestao] = []
    for item in _array_json(texto):
        if not isinstance(item, dict):
            continue
        pagina = _link(item.get("link_pagina") or item.get("link"))
        orgao = _texto(item.get("orgao"), 200)
        if pagina is None or orgao is None:
            continue  # sem página https e órgão não há o que conferir nem como identificar
        banca_item = (_texto(item.get("banca"), 30) or "").upper()
        banca = alvo.banca or (banca_item if banca_item in dominios_banca else None)
        host = dominio(pagina)
        uf = (_texto(item.get("uf"), 2) or "").upper()
        esfera = (_texto(item.get("esfera"), 10) or "").upper()
        situacao = (_texto(item.get("situacao"), 10) or "").upper()
        cargos = item.get("cargos") if isinstance(item.get("cargos"), list) else []
        escolaridades = item.get("escolaridades") if isinstance(item.get("escolaridades"), list) else []
        sugestoes.append(
            Sugestao(
                alvo=alvo.codigo,
                orgao=orgao,
                banca=banca,
                esfera=esfera if esfera in _ESFERAS else None,
                uf=uf if uf in _SIGLAS_UF else None,
                municipio=_texto(item.get("municipio"), 120),
                situacao="PREVISTO" if situacao == "PREVISTO" else "ABERTO",
                ano=_inteiro(item.get("ano"), hoje.year - 1, hoje.year + 2),
                inscricoes_inicio=_data(item.get("inscricoes_inicio"), hoje),
                inscricoes_fim=_data(item.get("inscricoes_fim") or item.get("inscricoes_ate"), hoje),
                isencao_inicio=_data(item.get("isencao_inicio"), hoje),
                isencao_fim=_data(item.get("isencao_fim") or item.get("isencao_ate"), hoje),
                data_prova=_data(item.get("data_prova"), hoje),
                taxa_max=_numero(item.get("taxa_max"), Decimal("0"), Decimal("1000")),
                vagas=_inteiro(item.get("vagas"), 1, 100_000),
                salario_max=_numero(item.get("salario_max"), Decimal("500"), Decimal("100000")),
                cargos=tuple(dict.fromkeys(c for c in (_texto(x, 150) for x in cargos[:15]) if c)),
                escolaridades=tuple(
                    e for e in dict.fromkeys(str(x).upper() for x in escolaridades) if e in _ESCOLARIDADES
                ),
                link_pagina=pagina,
                link_edital=_link(item.get("link_edital")),
                oficial=eh_oficial(pagina, (*alvo.dominios, *dominios_banca.get(banca or "", ()))),
                confirmado=any(host == f or host.endswith("." + f) or f.endswith("." + host) for f in fontes),
            )
        )
    return sugestoes


# Ordem: os "Lite" têm cota diária bem maior na faixa gratuita e vão primeiro; quem esgotar sai da rodada.
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


@dataclass(frozen=True)
class RespostaBusca:
    texto: str
    metadados: Mapping[str, Any]


class Buscador(Protocol):
    nome: str

    def buscar(self, pedido: str) -> RespostaBusca:
        """Texto da resposta e fontes. LimiteAtingido tira o buscador da rodada; FalhaIA passa o alvo ao próximo."""
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

    def buscar(self, pedido: str) -> RespostaBusca:
        corpo = {
            "contents": [{"role": "user", "parts": [{"text": pedido}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 16384},
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
        return RespostaBusca(texto, candidato.get("groundingMetadata") or {})

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

    def buscar(self, pedido: str) -> RespostaBusca:
        self._ritmo.esperar()
        corpo = {
            "model": self._modelo,
            "temperature": 0,
            "messages": [{"role": "user", "content": pedido}],
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
        # As citações da busca viram o mesmo formato de fontes do Gemini, para a conferência do domínio.
        fontes = [{"web": {"uri": (a.get("url_citation") or {}).get("url", ""), "title": ""}}
                  for a in mensagem.get("annotations") or [] if a.get("type") == "url_citation"]  # fmt: skip
        return RespostaBusca(texto, {"groundingChunks": fontes})


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


@dataclass(frozen=True)
class ResultadoAlvo:
    alvo: AlvoBusca
    sugestoes: tuple[Sugestao, ...] = ()
    erro: str | None = None


def buscar_alvos(
    buscadores: Sequence[Buscador],
    alvos: Iterable[AlvoBusca],
    hoje: date,
    dominios_banca: Mapping[str, Sequence[str]] | None = None,
    limite: int = 15,
) -> list[ResultadoAlvo]:
    """Cada alvo vai ao primeiro buscador disponível; se ele esgotar ou falhar, o mesmo alvo tenta o próximo.
    Alvos que ficaram sem buscador (todos esgotaram a cota) não aparecem no resultado: tentam na próxima execução."""
    ativos = list(buscadores)
    resultados: list[ResultadoAlvo] = []
    for alvo in alvos:
        if not ativos:
            break
        pedido = INSTRUCOES.format(pesquisa=alvo.pesquisa, hoje=hoje.isoformat(), limite=limite)
        erros: list[str] = []
        achou = False
        for buscador in list(ativos):
            try:
                resposta = buscador.buscar(pedido)
                sugestoes = interpretar(alvo, resposta.texto, resposta.metadados, hoje, dominios_banca)
            except LimiteAtingido as erro:
                log.warning("%s; seguindo para o próximo", erro)
                ativos.remove(buscador)
                continue
            except (FalhaIA, httpx.HTTPError) as erro:
                log.warning("busca %s via %s: %s", alvo.codigo, buscador.nome, erro)
                erros.append(str(erro))
                continue
            log.info("busca %s via %s: %d sugestões (%d confirmadas e oficiais)", alvo.codigo, buscador.nome,
                     len(sugestoes), sum(s.confirmado and s.oficial for s in sugestoes))  # fmt: skip
            resultados.append(ResultadoAlvo(alvo, tuple(sugestoes)))
            achou = True
            break
        if not achou and ativos:  # os que sobraram falharam neste alvo (não por cota)
            resultados.append(ResultadoAlvo(alvo, erro="; ".join(erros)[:500] or "sem resposta"))
    return resultados
