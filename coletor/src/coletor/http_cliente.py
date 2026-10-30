"""Cliente HTTP central e "educado": todo acesso externo do coletor passa por aqui.

Regras (seção 10 do contexto): só HTTPS e domínios permitidos (também após redirecionamentos), robots.txt
respeitado, intervalo mínimo por domínio, User-Agent identificado, timeouts, retentativas com espera crescente
e limite de tamanho. Nunca tenta contornar bloqueio, anti-bot ou CAPTCHA: 403 e similares viram erro.
"""

from __future__ import annotations

import codecs
import hashlib
import logging
import re
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

log = logging.getLogger(__name__)

STATUS_RETENTAVEIS = frozenset({429, 500, 502, 503, 504})
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([a-zA-Z0-9_-]+)""", re.IGNORECASE)
MAX_REDIRECIONAMENTOS = 5
ESPERA_MAXIMA_S = 60.0


def decodificar_html(corpo: bytes, charset_cabecalho: str | None) -> str:
    """Charset do cabeçalho HTTP; senão o declarado no <meta> da página; senão UTF-8, com windows-1252 de reserva.

    Sites antigos (IBAM, em ASP) mandam windows-1252 sem charset no cabeçalho: lido como UTF-8, "Balneário" vira
    "Balne�rio" e o município não é encontrado.
    """
    for candidato in (charset_cabecalho, _charset_do_meta(corpo)):
        if candidato:
            try:
                return corpo.decode(codecs.lookup(candidato).name, errors="replace")
            except LookupError:
                continue
    try:
        return corpo.decode("utf-8")
    except UnicodeDecodeError:
        return corpo.decode("cp1252", errors="replace")


def _charset_do_meta(corpo: bytes) -> str | None:
    achado = _META_CHARSET.search(corpo[:4096])
    return achado.group(1).decode("ascii") if achado else None


class ErroHttp(Exception):
    pass


class AcessoNaoPermitido(ErroHttp):
    """Domínio fora da lista, esquema não HTTPS ou caminho proibido pelo robots.txt."""


class RespostaRecusada(ErroHttp):
    """Status de erro, tipo de conteúdo inesperado ou tamanho acima do limite."""


@dataclass(frozen=True)
class Download:
    caminho: Path
    sha256: str
    tamanho: int
    url_final: str


class ClienteHttp:
    def __init__(
        self,
        dominios_permitidos: frozenset[str],
        user_agent: str,
        *,
        intervalo_s: float = 2.5,
        timeout_s: float = 30.0,
        max_tentativas: int = 3,
        max_bytes_html: int = 5 * 1024 * 1024,
        transport: httpx.BaseTransport | None = None,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._dominios = frozenset(d.lower() for d in dominios_permitidos)
        self._user_agent = user_agent
        self._intervalo_s = intervalo_s
        self._max_tentativas = max_tentativas
        self._max_bytes_html = max_bytes_html
        self._relogio = relogio
        self._dormir = dormir
        self._ultimo_acesso: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "pt-BR,pt;q=0.9"},
            timeout=httpx.Timeout(timeout_s, connect=15.0),
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self) -> ClienteHttp:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()

    def fechar(self) -> None:
        self._http.close()

    def obter_texto(self, url: str) -> str:
        with self._abrir(url) as resposta:
            corpo = self._ler_limitado(resposta, self._max_bytes_html, url)
            charset = resposta.charset_encoding
        return decodificar_html(corpo, charset)

    def baixar_pdf(self, url: str, pasta: Path, max_bytes: int) -> Download:
        """Baixa um PDF para `pasta` (temporária, criada por quem chama) conferindo tipo e tamanho."""
        with self._abrir(url) as resposta:
            tipo = resposta.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if tipo not in ("application/pdf", "application/octet-stream", "binary/octet-stream", ""):
                raise RespostaRecusada(f"tipo de conteúdo {tipo!r} não é PDF: {url}")
            declarado = resposta.headers.get("Content-Length")
            if declarado and declarado.isdigit() and int(declarado) > max_bytes:
                raise RespostaRecusada(f"PDF de {int(declarado)} bytes excede o limite de {max_bytes}: {url}")

            destino = pasta / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}.pdf"
            digest = hashlib.sha256()
            tamanho = 0
            with destino.open("wb") as arquivo:
                for bloco in resposta.iter_bytes(64 * 1024):
                    tamanho += len(bloco)
                    if tamanho > max_bytes:
                        raise RespostaRecusada(f"PDF excede o limite de {max_bytes} bytes: {url}")
                    if tamanho == len(bloco) and not bloco.startswith(b"%PDF-"):
                        # Conteúdo é conferido pela assinatura, não só pelo cabeçalho (servidores mentem).
                        raise RespostaRecusada(f"conteúdo não começa com %PDF-: {url}")
                    digest.update(bloco)
                    arquivo.write(bloco)
            if tamanho == 0:
                raise RespostaRecusada(f"PDF vazio: {url}")
            return Download(destino, digest.hexdigest(), tamanho, str(resposta.url))

    def _abrir(self, url: str) -> _RespostaAberta:
        atual = url
        for _ in range(MAX_REDIRECIONAMENTOS + 1):
            self._validar_destino(atual)
            resposta = self._requisitar_com_retentativas(atual)
            if resposta.is_redirect:
                destino = resposta.headers.get("Location")
                resposta.close()
                if not destino:
                    raise RespostaRecusada(f"redirecionamento sem Location: {atual}")
                atual = urljoin(atual, destino)
                continue
            if resposta.status_code >= 400:
                resposta.close()
                raise RespostaRecusada(f"HTTP {resposta.status_code} em {atual}")
            return _RespostaAberta(resposta)
        raise RespostaRecusada(f"redirecionamentos demais a partir de {url}")

    def _validar_destino(self, url: str) -> None:
        partes = urlsplit(url)
        if partes.scheme != "https":
            raise AcessoNaoPermitido(f"só HTTPS é permitido: {url}")
        host = (partes.hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in self._dominios):
            raise AcessoNaoPermitido(f"domínio fora da lista permitida: {host}")
        if not self._robots_permite(partes.scheme, host, url):
            raise AcessoNaoPermitido(f"robots.txt não permite: {url}")

    def _robots_permite(self, esquema: str, host: str, url: str) -> bool:
        if host not in self._robots:
            self._robots[host] = self._carregar_robots(f"{esquema}://{host}/robots.txt")
        return self._robots[host].can_fetch(self._user_agent, url)

    def _carregar_robots(self, url_robots: str) -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser(url_robots)
        try:
            resposta = self._requisitar_com_retentativas(url_robots)
            corpo = resposta.read()
            status = resposta.status_code
            resposta.close()
        except httpx.HTTPError as erro:
            log.warning("robots.txt inacessível (%s); por cautela, nada será acessado em %s", erro, url_robots)
            parser.disallow_all = True
            return parser
        if status in (401, 403) or status >= 500:
            # Mesma regra dos buscadores: robots.txt negado ou com erro de servidor = não coletar.
            parser.disallow_all = True
        elif status >= 400:
            parser.allow_all = True
        else:
            parser.parse(corpo.decode("utf-8", errors="replace").splitlines())
        return parser

    def _requisitar_com_retentativas(self, url: str) -> httpx.Response:
        ultimo_erro: Exception | None = None
        for tentativa in range(1, self._max_tentativas + 1):
            self._respeitar_intervalo(url)
            try:
                resposta = self._http.send(self._http.build_request("GET", url), stream=True)
            except (httpx.TimeoutException, httpx.TransportError) as erro:
                ultimo_erro = erro
                log.warning("falha de rede em %s (tentativa %d/%d): %s", url, tentativa, self._max_tentativas, erro)
            else:
                if resposta.status_code not in STATUS_RETENTAVEIS or tentativa == self._max_tentativas:
                    return resposta
                espera = self._espera_retry_after(resposta) or 2.0 * 2 ** (tentativa - 1)
                resposta.close()
                log.warning("HTTP %d em %s; nova tentativa em %.0fs", resposta.status_code, url, espera)
                self._dormir(espera)
                continue
            if tentativa < self._max_tentativas:
                self._dormir(2.0 * 2 ** (tentativa - 1))
        raise ErroHttp(f"falha de rede persistente em {url}: {ultimo_erro}") from ultimo_erro

    @staticmethod
    def _espera_retry_after(resposta: httpx.Response) -> float | None:
        valor = resposta.headers.get("Retry-After", "")
        return min(float(valor), ESPERA_MAXIMA_S) if valor.isdigit() else None

    def _respeitar_intervalo(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        anterior = self._ultimo_acesso.get(host)
        if anterior is not None:
            restante = self._intervalo_s - (self._relogio() - anterior)
            if restante > 0:
                self._dormir(restante)
        self._ultimo_acesso[host] = self._relogio()

    @staticmethod
    def _ler_limitado(resposta: httpx.Response, maximo: int, url: str) -> bytes:
        partes: list[bytes] = []
        total = 0
        for bloco in resposta.iter_bytes(64 * 1024):
            total += len(bloco)
            if total > maximo:
                raise RespostaRecusada(f"resposta maior que {maximo} bytes: {url}")
            partes.append(bloco)
        return b"".join(partes)


class _RespostaAberta:
    """Garante o fechamento da resposta em streaming mesmo quando a leitura falha."""

    def __init__(self, resposta: httpx.Response) -> None:
        self._resposta = resposta

    def __enter__(self) -> httpx.Response:
        return self._resposta

    def __exit__(self, *_: object) -> None:
        self._resposta.close()
