"""Contrato comum a todas as fontes de descoberta (bancas, diários oficiais, notícias)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from coletor.extratores.base import CargoExtraido
from coletor.http_cliente import ClienteHttp


@dataclass(frozen=True)
class DadosEstruturados:
    """Dados que a própria página da banca já traz organizados (cargos, datas, taxas).

    Quando existem, preenchem o concurso sem depender da leitura do PDF. Se depois um extrator de edital
    estruturar o concurso, o edital prevalece.
    """

    orgao: str | None = None
    esfera: str | None = None
    uf: str | None = None
    municipio: str | None = None
    numero_edital: str | None = None
    ano: int | None = None
    situacao: str | None = None
    inscricao_inicio: date | None = None
    inscricao_fim: date | None = None
    data_prova: date | None = None
    taxa_min: Decimal | None = None
    taxa_max: Decimal | None = None
    cargos: tuple[CargoExtraido, ...] = ()
    avisos: tuple[str, ...] = ()

    def para_payload(self) -> dict[str, Any]:
        def texto(valor: Any) -> Any:
            return None if valor is None else str(valor)

        return {
            "orgao": self.orgao,
            "esfera": self.esfera,
            "uf": self.uf,
            "municipio": self.municipio,
            "numero_edital": self.numero_edital,
            "ano": self.ano,
            "situacao": self.situacao,
            "inscricao_inicio": texto(self.inscricao_inicio),
            "inscricao_fim": texto(self.inscricao_fim),
            "data_prova": texto(self.data_prova),
            "taxa_min": texto(self.taxa_min),
            "taxa_max": texto(self.taxa_max),
            "avisos": list(self.avisos),
            "cargos": [
                {
                    "nome": c.nome,
                    "especialidade": c.especialidade,
                    "escolaridade": c.escolaridade,
                    "vagas": c.vagas,
                    "cadastro_reserva": c.cadastro_reserva,
                    "salario": texto(c.salario),
                    "uf_lotacao": c.uf_lotacao,
                }
                for c in self.cargos
            ],
        }

    @classmethod
    def de_payload(cls, dados: Mapping[str, Any]) -> DadosEstruturados:
        def data(valor: Any) -> date | None:
            return date.fromisoformat(valor) if valor else None

        def decimal(valor: Any) -> Decimal | None:
            return Decimal(valor) if valor not in (None, "") else None

        return cls(
            orgao=dados.get("orgao"),
            esfera=dados.get("esfera"),
            uf=dados.get("uf"),
            municipio=dados.get("municipio"),
            numero_edital=dados.get("numero_edital"),
            ano=dados.get("ano"),
            situacao=dados.get("situacao"),
            inscricao_inicio=data(dados.get("inscricao_inicio")),
            inscricao_fim=data(dados.get("inscricao_fim")),
            data_prova=data(dados.get("data_prova")),
            taxa_min=decimal(dados.get("taxa_min")),
            taxa_max=decimal(dados.get("taxa_max")),
            avisos=tuple(dados.get("avisos") or ()),
            cargos=tuple(
                CargoExtraido(
                    nome=c["nome"],
                    especialidade=c.get("especialidade"),
                    escolaridade=c.get("escolaridade"),
                    vagas=c.get("vagas"),
                    cadastro_reserva=bool(c.get("cadastro_reserva")),
                    salario=decimal(c.get("salario")),
                    uf_lotacao=c.get("uf_lotacao"),
                )
                for c in dados.get("cargos") or ()
            ),
        )


@dataclass(frozen=True)
class SinalDescoberta:
    """Evidência de um concurso vista numa fonte. `url` identifica o sinal dentro da fonte.

    `payload` segue o formato comum: titulo, situacao_site, descricao, link_inscricao e arquivos
    [{titulo, url, data (ISO), pdf (bool, opcional)}].
    """

    titulo: str
    url: str
    data_publicacao: date | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    estruturado: DadosEstruturados | None = None

    def payload_completo(self) -> dict[str, Any]:
        completo = dict(self.payload)
        if self.estruturado is not None:
            completo["estruturado"] = self.estruturado.para_payload()
        return completo


@dataclass(frozen=True)
class ResultadoDescoberta:
    sinais: tuple[SinalDescoberta, ...]
    falhas: tuple[str, ...] = ()


class Fonte(Protocol):
    """Adaptador de uma fonte. Implementações não acessam o banco: só devolvem sinais.

    Atributos:
        nome: igual a `concursos.fonte.nome`, liga o adaptador ao cadastro.
        dominios: domínios que o cliente HTTP pode acessar para esta fonte (páginas e arquivos).
    """

    nome: str
    dominios: frozenset[str]

    def descobrir(self, http: ClienteHttp, pular: frozenset[str] = frozenset()) -> ResultadoDescoberta:
        """Lista os concursos visíveis na fonte. Falhas pontuais vão em `falhas`; falha total levanta exceção.

        `pular`: URLs de sinais cuja página não precisa ser relida agora (concursos sem oportunidade aberta);
        a fonte não devolve sinal para elas.
        """
        ...
