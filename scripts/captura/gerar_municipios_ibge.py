"""Gera a migration com os municípios do IBGE (db/migrations/V6__municipios_ibge.sql).

Uso (no GitHub Actions, workflow captura-ibge):
    python scripts/captura/gerar_municipios_ibge.py --saida db/migrations/V6__municipios_ibge.sql
    python scripts/captura/gerar_municipios_ibge.py --entrada municipios.json --saida ...   # sem internet

A UF sai dos dois primeiros dígitos do código IBGE (regra fixa do IBGE), sem depender da hierarquia de
micro/mesorregião da API, que vem nula para municípios criados recentemente.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

URL_IBGE = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
# Espelho público derivado do IBGE, usado só se a API oficial não responder ao GitHub Actions. A origem usada fica
# registrada no cabeçalho da migration gerada.
URL_ESPELHO = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"
UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos)"

UF_POR_CODIGO: dict[int, str] = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
    21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA",
    31: "MG", 32: "ES", 33: "RJ", 35: "SP",
    41: "PR", 42: "SC", 43: "RS",
    50: "MS", 51: "MT", 52: "GO", 53: "DF",
}  # fmt: skip

# Faixa de segurança: o Brasil tem 5.571 municípios (2026); fora disso a resposta da API está errada.
MINIMO_MUNICIPIOS = 5560
MAXIMO_MUNICIPIOS = 5600


class DadosInvalidos(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Municipio:
    codigo: int
    nome: str
    uf: str
    slug: str


def slugificar(texto: str) -> str:
    sem_acento = (
        unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")


def converter(registros: Iterable[dict]) -> list[Municipio]:
    municipios: list[Municipio] = []
    for registro in registros:
        codigo = int(registro["id"])
        nome = str(registro["nome"]).strip()
        if not 1_000_000 <= codigo <= 9_999_999 or not nome:
            raise DadosInvalidos(f"registro inválido: {registro!r}")
        uf = UF_POR_CODIGO.get(codigo // 100_000)
        if uf is None:
            raise DadosInvalidos(f"código {codigo} não corresponde a nenhuma UF")
        municipios.append(Municipio(codigo, nome, uf, slugificar(nome)))
    municipios.sort(key=lambda m: m.codigo)
    return municipios


def validar(municipios: list[Municipio], *, completo: bool = True) -> None:
    codigos = [m.codigo for m in municipios]
    if len(set(codigos)) != len(codigos):
        raise DadosInvalidos("códigos IBGE repetidos")
    chaves = [(m.uf, m.slug) for m in municipios]
    if len(set(chaves)) != len(chaves):
        repetidas = sorted({c for c in chaves if chaves.count(c) > 1})
        raise DadosInvalidos(f"slugs repetidos na mesma UF (URL ambígua): {repetidas}")
    if not completo:
        return
    if not MINIMO_MUNICIPIOS <= len(municipios) <= MAXIMO_MUNICIPIOS:
        raise DadosInvalidos(f"{len(municipios)} municípios fora da faixa esperada")
    sem_municipio = set(UF_POR_CODIGO.values()) - {m.uf for m in municipios}
    if sem_municipio:
        raise DadosInvalidos(f"UFs sem municípios: {sorted(sem_municipio)}")


def _literal(texto: str) -> str:
    return "'" + texto.replace("'", "''") + "'"


def gerar_sql(municipios: list[Municipio], origem: str) -> str:
    linhas = ",\n".join(
        f"       ({m.codigo}, {_literal(m.nome)}, '{m.uf}', '{m.slug}')"
        for m in municipios
    )
    return (
        "-- GERADO por scripts/captura/gerar_municipios_ibge.py (workflow captura-ibge). Não editar à mão.\n"
        f"-- Origem: {origem}. {len(municipios)} municípios.\n"
        "-- Município novo ou renomeado pelo IBGE entra por uma migration nova (nunca editar esta).\n\n"
        "INSERT INTO concursos.municipio (codigo_ibge, nome, uf, slug)\n"
        f"VALUES {linhas.lstrip()}\n"
        "ON CONFLICT (codigo_ibge) DO NOTHING;\n"
    )


def _obter(url: str, tentativas: int = 3) -> bytes:
    pedido = urllib.request.Request(url, headers={"User-Agent": UA})
    for tentativa in range(1, tentativas + 1):
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                return resposta.read()
        except (urllib.error.URLError, TimeoutError) as erro:
            print(
                f"::warning title=Municípios IBGE::{url} falhou ({erro}), tentativa {tentativa}",
                file=sys.stderr,
            )
            if tentativa == tentativas:
                raise
            time.sleep(5 * tentativa)
    raise AssertionError("inalcançável")


def ler_csv_espelho(conteudo: str) -> list[dict]:
    return [
        {"id": linha["codigo_ibge"], "nome": linha["nome"]}
        for linha in csv.DictReader(io.StringIO(conteudo))
    ]


def baixar() -> tuple[list[dict], str]:
    try:
        return json.loads(_obter(URL_IBGE)), URL_IBGE
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return ler_csv_espelho(_obter(URL_ESPELHO).decode("utf-8")), URL_ESPELHO


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--entrada", type=Path, help="JSON já baixado da API do IBGE (sem internet)"
    )
    parser.add_argument("--saida", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.entrada:
            registros, origem = (
                json.loads(args.entrada.read_text(encoding="utf-8")),
                str(args.entrada.name),
            )
        else:
            registros, origem = baixar()
        municipios = converter(registros)
        validar(municipios)
    except (DadosInvalidos, KeyError, TypeError, ValueError, OSError) as erro:
        # Formato de anotação do GitHub Actions: o motivo aparece no resumo da execução, sem abrir o log.
        print(f"::error title=Municípios IBGE::{erro}", file=sys.stderr)
        return 1
    args.saida.write_text(gerar_sql(municipios, origem), encoding="utf-8")
    print(
        f"::notice title=Municípios IBGE::{len(municipios)} municípios de {origem} gravados em {args.saida}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
