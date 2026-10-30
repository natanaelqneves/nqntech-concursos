"""Área de cada cargo por regras de palavras-chave (config/areas.yml; regras explicadas no próprio arquivo)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from coletor.classificacao.regras import RegrasInvalidas, Termos, carregar_yaml, preparar

AREA_PADRAO = "OUTRAS"


@dataclass(frozen=True)
class RegraArea:
    codigo: str
    principal: Termos
    termos: Termos
    orgao: Termos
    genericos: Termos
    excluir: Termos

    @property
    def principal_e_termos(self) -> tuple[Termos, Termos]:
        return (self.principal, self.termos)


@dataclass(frozen=True)
class AreaClassificada:
    codigo: str
    # Por que a área foi escolhida, para log e testes: "principal:professor", "especialidade:ti", "orgao:banco".
    motivo: str | None

    @property
    def identificada(self) -> bool:
        return self.motivo is not None


class ClassificadorArea:
    def __init__(self, regras: tuple[RegraArea, ...], abreviacoes: Mapping[str, str] | None = None) -> None:
        self._regras = regras
        self._abreviacoes = dict(abreviacoes or {})

    @classmethod
    def padrao(cls) -> ClassificadorArea:
        return cls.de_dados(carregar_yaml("areas.yml"))

    @classmethod
    def de_dados(cls, dados: Mapping[str, Any], areas_validas: frozenset[str] | None = None) -> ClassificadorArea:
        areas = dados.get("areas")
        if not isinstance(areas, Mapping) or not areas:
            raise RegrasInvalidas("areas.yml: chave 'areas' ausente ou vazia")
        regras = []
        for codigo, regra in areas.items():
            if areas_validas is not None and codigo not in areas_validas:
                raise RegrasInvalidas(f"areas.yml: área '{codigo}' não existe no catálogo concursos.area")
            if codigo == AREA_PADRAO:
                raise RegrasInvalidas(f"areas.yml: '{AREA_PADRAO}' é o padrão e não leva regras")
            regra = regra or {}
            regras.append(
                RegraArea(
                    codigo=str(codigo),
                    principal=Termos.de(regra.get("principal") or ()),
                    termos=Termos.de(regra.get("termos") or ()),
                    orgao=Termos.de(regra.get("orgao") or ()),
                    genericos=Termos.de(regra.get("genericos") or ()),
                    excluir=Termos.de(regra.get("excluir") or ()),
                )
            )
        abreviacoes = dados.get("abreviacoes") or {}
        if not isinstance(abreviacoes, Mapping):
            raise RegrasInvalidas("areas.yml: 'abreviacoes' deve ser um mapeamento abreviação → palavra")
        return cls(tuple(regras), {preparar(str(k)): preparar(str(v)) for k, v in abreviacoes.items()})

    @property
    def codigos(self) -> frozenset[str]:
        return frozenset(r.codigo for r in self._regras) | {AREA_PADRAO}

    def classificar(self, nome: str, especialidade: str | None = None, orgao: str | None = None) -> AreaClassificada:
        texto_nome = preparar(nome, self._abreviacoes)
        texto_especialidade = preparar(especialidade, self._abreviacoes)
        texto_cargo = f"{texto_nome} {texto_especialidade}".strip()

        passos = (
            ("principal", texto_nome, lambda r: r.principal),
            ("especialidade", texto_especialidade, lambda r: r.principal_e_termos),
            ("cargo", texto_nome, lambda r: r.principal_e_termos),
            ("orgao", preparar(orgao), lambda r: r.orgao),
            ("generico", texto_cargo, lambda r: r.genericos),
        )
        for motivo, texto, termos_de in passos:
            if not texto:
                continue
            melhor: tuple[int, str, str] | None = None  # (tamanho do termo, área, termo)
            for regra in self._regras:
                if regra.excluir.presente(texto_cargo):
                    continue
                termo = _maior_termo(termos_de(regra), texto)
                if termo is not None and (melhor is None or len(termo) > melhor[0]):
                    melhor = (len(termo), regra.codigo, termo)
            if melhor is not None:
                return AreaClassificada(melhor[1], f"{motivo}:{melhor[2]}")
        return AreaClassificada(AREA_PADRAO, None)


def _maior_termo(termos: tuple[Termos, ...] | Termos, texto: str) -> str | None:
    if isinstance(termos, Termos):
        return termos.maior(texto)
    achados = [t for t in (grupo.maior(texto) for grupo in termos) if t is not None]
    return max(achados, key=len) if achados else None
