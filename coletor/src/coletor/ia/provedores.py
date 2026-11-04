"""Provedores de IA com saída estruturada e a política de uso deles.

Política (seção 10 do contexto): uma chave por provedor, dentro do limite de cada um. Ao receber 429 o provedor
sai da rodada e a próxima tentativa vai para o seguinte da lista (fallback); nunca se multiplicam chaves do mesmo
provedor para fugir do limite, o que violaria os termos de uso. Há um teto de chamadas por execução e um
intervalo mínimo entre chamadas ao mesmo provedor.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class FalhaIA(Exception):
    """Resposta inválida ou erro do provedor nesta chamada (o próximo provedor pode tentar)."""


class LimiteAtingido(FalhaIA):
    """429/cota: o provedor fica fora até o fim da execução."""


class ProvedorIA(Protocol):
    nome: str
    modelo: str

    def gerar_json(self, instrucoes: str, conteudo: str, esquema: Mapping[str, Any]) -> dict[str, Any]:
        """Devolve o objeto JSON da resposta (já conferido como JSON válido) ou levanta FalhaIA/LimiteAtingido."""
        ...


@dataclass(frozen=True)
class ConfigIA:
    gemini_chave: str | None = None
    gemini_modelo: str = "gemini-3.8-flash"
    groq_chave: str | None = None
    groq_modelo: str = "openai/gpt-oss-120b"
    openrouter_chave: str | None = None
    # Roteador gratuito do OpenRouter; com require_parameters só vão modelos que aceitam json_schema.
    openrouter_modelo: str = "openrouter/free"
    max_chamadas: int = 30
    intervalo_s: float = 4.0  # entre chamadas ao mesmo provedor (cabe no RPM da faixa gratuita)
    timeout_s: float = 120.0
    max_caracteres: int = 24_000

    @property
    def ativa(self) -> bool:
        return bool(self.gemini_chave or self.groq_chave or self.openrouter_chave) and self.max_chamadas > 0

    def __repr__(self) -> str:  # chaves nunca em logs
        return (
            f"ConfigIA(gemini={'sim' if self.gemini_chave else 'não'}, groq={'sim' if self.groq_chave else 'não'}, "
            f"openrouter={'sim' if self.openrouter_chave else 'não'}, max_chamadas={self.max_chamadas})"
        )


def _json_da_resposta(texto: str | None, provedor: str) -> dict[str, Any]:
    if not texto:
        raise FalhaIA(f"{provedor}: resposta vazia")
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise FalhaIA(f"{provedor}: JSON inválido ({erro})") from erro
    if not isinstance(dados, dict):
        raise FalhaIA(f"{provedor}: a resposta não é um objeto JSON")
    return dados


def _checar_status(resposta: httpx.Response, provedor: str) -> None:
    if resposta.status_code == 429:
        raise LimiteAtingido(f"{provedor}: limite atingido (429)")
    if resposta.status_code >= 400:
        # O corpo de erro dos provedores não contém a chave; corta para não poluir o log.
        raise FalhaIA(f"{provedor}: HTTP {resposta.status_code}: {resposta.text[:300]}")


@dataclass
class Gemini:
    chave: str
    modelo: str
    http: httpx.Client
    nome: str = "gemini"

    def gerar_json(self, instrucoes: str, conteudo: str, esquema: Mapping[str, Any]) -> dict[str, Any]:
        corpo = {
            "systemInstruction": {"parts": [{"text": instrucoes}]},
            "contents": [{"role": "user", "parts": [{"text": conteudo}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": esquema,
                "maxOutputTokens": 8192,
            },
        }
        resposta = self.http.post(GEMINI_URL.format(modelo=self.modelo), json=corpo,
                                  headers={"x-goog-api-key": self.chave})  # fmt: skip
        _checar_status(resposta, self.nome)
        try:
            partes = resposta.json()["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError, ValueError) as erro:
            raise FalhaIA(f"gemini: resposta sem conteúdo ({erro})") from erro
        return _json_da_resposta("".join(p.get("text", "") for p in partes), self.nome)


@dataclass
class Groq:
    chave: str
    modelo: str
    http: httpx.Client
    nome: str = "groq"

    def gerar_json(self, instrucoes: str, conteudo: str, esquema: Mapping[str, Any]) -> dict[str, Any]:
        corpo = {
            "model": self.modelo,
            "temperature": 0,
            "max_completion_tokens": 8192,
            "messages": [{"role": "system", "content": instrucoes}, {"role": "user", "content": conteudo}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "edital", "strict": True, "schema": esquema},
            },
        }
        resposta = self.http.post(GROQ_URL, json=corpo, headers={"Authorization": f"Bearer {self.chave}"})
        _checar_status(resposta, self.nome)
        try:
            texto = resposta.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as erro:
            raise FalhaIA(f"groq: resposta sem conteúdo ({erro})") from erro
        return _json_da_resposta(texto, self.nome)


@dataclass
class OpenRouter:
    """API compatível com a da OpenAI; a última reserva da lista."""

    chave: str
    modelo: str
    http: httpx.Client
    nome: str = "openrouter"

    def gerar_json(self, instrucoes: str, conteudo: str, esquema: Mapping[str, Any]) -> dict[str, Any]:
        corpo = {
            "model": self.modelo,
            "temperature": 0,
            "max_tokens": 8192,
            "messages": [{"role": "system", "content": instrucoes}, {"role": "user", "content": conteudo}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "edital", "strict": True, "schema": esquema},
            },
            "provider": {"require_parameters": True},
        }
        cabecalhos = {
            "Authorization": f"Bearer {self.chave}",
            "HTTP-Referer": "https://github.com/natanaelqneves/nqntech-concursos",
            "X-Title": "NqnTech Concursos",
        }
        resposta = self.http.post(OPENROUTER_URL, json=corpo, headers=cabecalhos)
        _checar_status(resposta, self.nome)
        try:
            texto = resposta.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as erro:
            raise FalhaIA(f"openrouter: resposta sem conteúdo ({erro})") from erro
        return _json_da_resposta(texto, self.nome)


def criar_provedores(config: ConfigIA, http: httpx.Client) -> list[ProvedorIA]:
    """Ordem = prioridade: Gemini, depois Groq, depois OpenRouter."""
    provedores: list[ProvedorIA] = []
    if config.gemini_chave:
        provedores.append(Gemini(config.gemini_chave, config.gemini_modelo, http))
    if config.groq_chave:
        provedores.append(Groq(config.groq_chave, config.groq_modelo, http))
    if config.openrouter_chave:
        provedores.append(OpenRouter(config.openrouter_chave, config.openrouter_modelo, http))
    return provedores


@dataclass
class Rodizio:
    """Escolhe o provedor de cada chamada: o primeiro disponível, respeitando intervalo, limite e teto."""

    provedores: Sequence[ProvedorIA]
    max_chamadas: int
    intervalo_s: float
    dormir: Callable[[float], None] = time.sleep
    relogio: Callable[[], float] = time.monotonic
    chamadas: int = 0
    esgotados: set[str] = field(default_factory=set)
    _ultima: dict[str, float] = field(default_factory=dict)

    @property
    def disponivel(self) -> bool:
        return self.chamadas < self.max_chamadas and any(p.nome not in self.esgotados for p in self.provedores)

    def gerar(self, instrucoes: str, conteudo: str, esquema: Mapping[str, Any]) -> tuple[dict[str, Any], ProvedorIA]:
        erros: list[str] = []
        for provedor in self.provedores:
            if provedor.nome in self.esgotados:
                continue
            if self.chamadas >= self.max_chamadas:
                break
            espera = self._ultima.get(provedor.nome, -1e9) + self.intervalo_s - self.relogio()
            if espera > 0:
                self.dormir(espera)
            self.chamadas += 1
            self._ultima[provedor.nome] = self.relogio()
            try:
                return provedor.gerar_json(instrucoes, conteudo, esquema), provedor
            except LimiteAtingido as erro:
                log.warning("%s; seguindo para o próximo provedor", erro)
                self.esgotados.add(provedor.nome)
                erros.append(str(erro))
            except (FalhaIA, httpx.HTTPError) as erro:
                log.warning("falha no provedor %s: %s", provedor.nome, erro)
                erros.append(f"{provedor.nome}: {erro}")
        raise FalhaIA("; ".join(erros) or "nenhum provedor disponível (teto de chamadas ou limites atingidos)")
