"""Contrato da resposta da IA (JSON Schema estrito) e a validação que a transforma em EditalExtraido.

O esquema segue o subconjunto aceito pelos dois provedores em modo estrito: todo campo é obrigatório, objetos são
fechados (additionalProperties: false) e "pode faltar" é representado por null. A validação desconfia de tudo:
valor fora de faixa vira null com aviso, nunca chega ao site.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from coletor.extratores.base import CargoExtraido, EditalExtraido, IsencaoPrevista

VERSAO = "1"  # muda quando o esquema ou o prompt mudam: invalida o cache

ESCOLARIDADES = ("FUNDAMENTAL", "MEDIO", "TECNICO", "SUPERIOR")
ISENCOES = (
    "CADUNICO",
    "DOADOR_MEDULA",
    "DOADOR_SANGUE",
    "DOADOR_PLASMA",
    "JURADO",
    "MESARIO_ELEITORAL",
    "PESSOA_COM_DEFICIENCIA",
    "VITIMA_VIOLENCIA_DOMESTICA",
    "ESTUDANTE",
    "DESEMPREGADO",
    "OUTRA",
)
UFS = (
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
    "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
)  # fmt: skip

MAX_CARGOS = 300
SALARIO = (Decimal(300), Decimal(150_000))
TAXA = (Decimal(0), Decimal(2_000))
MAX_VAGAS = 100_000


CAMPOS = [
    "orgao", "uf", "numero_edital", "ano", "cargos", "inscricao_inicio", "inscricao_fim", "data_prova",
    "taxa_min", "taxa_max", "isencoes", "isencao_inicio", "isencao_fim",
]  # fmt: skip


def _texto(descricao: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "description": descricao}


def _data(descricao: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "description": f"{descricao} (AAAA-MM-DD)"}


def _numero(descricao: str) -> dict[str, Any]:
    return {"type": ["number", "null"], "description": descricao}


ESQUEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": CAMPOS,
    "properties": {
        "orgao": _texto("órgão que abre o concurso, por extenso"),
        # Enum só em campos não nulos: os provedores divergem sobre null dentro de enum. O resto valida depois.
        "uf": _texto("sigla da UF do órgão (ex.: PB); null se o concurso é nacional"),
        "numero_edital": _texto("número do edital, ex.: 01/2026"),
        "ano": {"type": ["integer", "null"]},
        "cargos": {
            "type": "array",
            "description": "um item por cargo/especialidade com vagas próprias",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["nome", "especialidade", "escolaridade", "vagas", "cadastro_reserva", "salario"],
                "properties": {
                    "nome": {"type": "string"},
                    "especialidade": _texto("especialidade/área/perfil, se houver"),
                    "escolaridade": _texto("FUNDAMENTAL, MEDIO, TECNICO ou SUPERIOR"),
                    "vagas": {"type": ["integer", "null"], "description": "vagas imediatas (total do cargo)"},
                    "cadastro_reserva": {"type": "boolean"},
                    "salario": _numero("remuneração inicial em reais"),
                },
            },
        },
        "inscricao_inicio": _data("início das inscrições"),
        "inscricao_fim": _data("fim das inscrições"),
        "data_prova": _data("data da prova objetiva"),
        "taxa_min": _numero("menor taxa de inscrição em reais"),
        "taxa_max": _numero("maior taxa de inscrição em reais"),
        "isencoes": {
            "type": "array",
            "description": "tipos de isenção da taxa previstos no edital",
            "items": {"type": "string", "enum": list(ISENCOES)},
        },
        "isencao_inicio": _data("início do prazo para pedir isenção"),
        "isencao_fim": _data("fim do prazo para pedir isenção"),
    },
}

INSTRUCOES = (
    "Você extrai dados de editais de concursos públicos brasileiros. Responda só com o JSON do esquema. "
    "Use apenas o que está escrito no trecho; se um dado não aparece, use null (nunca estime). "
    "Datas em AAAA-MM-DD. Valores em reais como número (7526.14). Em 'cargos', um item por cargo ou "
    "especialidade com vagas próprias; vagas = total de vagas imediatas do cargo. Em 'isencoes', só os tipos "
    "previstos no item de isenção da taxa (OUTRA para casos fora da lista, como doadoras de leite). Ignore "
    "conteúdo programático."
)


def para_edital(dados: Mapping[str, Any], hoje: date) -> tuple[EditalExtraido, str | None]:
    """Valida a resposta e converte. Devolve o edital e a UF informada (usada só como pista de local)."""
    avisos: list[str] = []

    def data_valida(campo: str) -> date | None:
        valor = dados.get(campo)
        if not valor:
            return None
        try:
            dia = date.fromisoformat(str(valor)[:10])
        except ValueError:
            avisos.append(f"{campo} inválida na leitura automática: confira o edital")
            return None
        if not hoje.year - 2 <= dia.year <= hoje.year + 3:
            avisos.append(f"{campo} fora do período plausível: confira o edital")
            return None
        return dia

    def valor(bruto: Any, faixa: tuple[Decimal, Decimal], rotulo: str) -> Decimal | None:
        if bruto is None or isinstance(bruto, bool):
            return None
        try:
            numero = Decimal(str(bruto)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None
        if not faixa[0] < numero < faixa[1]:
            avisos.append(f"{rotulo} fora da faixa plausível: confira o edital")
            return None
        return numero

    inicio, fim = data_valida("inscricao_inicio"), data_valida("inscricao_fim")
    if inicio and fim and fim < inicio:
        avisos.append("período de inscrição incoerente (fim antes do início): confira o edital")
        inicio = fim = None
    isencao_inicio, isencao_fim = data_valida("isencao_inicio"), data_valida("isencao_fim")
    if isencao_inicio and isencao_fim and isencao_fim < isencao_inicio:
        isencao_inicio = isencao_fim = None
    prova = data_valida("data_prova")
    if prova and fim and prova < fim:
        avisos.append("data da prova anterior ao fim das inscrições: confira o edital")

    cargos: list[CargoExtraido] = []
    for bruto in list(dados.get("cargos") or [])[:MAX_CARGOS]:
        if not isinstance(bruto, Mapping):
            continue
        nome = " ".join(str(bruto.get("nome") or "").split())[:200]
        if len(nome) < 2:
            continue
        vagas = bruto.get("vagas")
        vagas = vagas if isinstance(vagas, int) and not isinstance(vagas, bool) and 0 <= vagas <= MAX_VAGAS else None
        escolaridade = bruto.get("escolaridade") if bruto.get("escolaridade") in ESCOLARIDADES else None
        especialidade = " ".join(str(bruto.get("especialidade") or "").split())[:200] or None
        cargos.append(
            CargoExtraido(
                nome=nome,
                especialidade=especialidade,
                escolaridade=escolaridade,
                vagas=vagas,
                cadastro_reserva=bool(bruto.get("cadastro_reserva")),
                salario=valor(bruto.get("salario"), SALARIO, "salário"),
            )
        )
    if not cargos:
        avisos.append("quadro de cargos/vagas não encontrado: confira o edital")

    taxas = [t for t in (valor(dados.get(c), TAXA, "taxa") for c in ("taxa_min", "taxa_max")) if t is not None]
    isencoes = tuple(IsencaoPrevista(c) for c in dict.fromkeys(dados.get("isencoes") or []) if c in ISENCOES)
    if isencoes and isencao_fim is None:
        avisos.append("período para pedir isenção não identificado: confira o edital")
    ano = dados.get("ano")
    uf = dados.get("uf") if dados.get("uf") in UFS else None
    edital = EditalExtraido(
        orgao=(" ".join(str(dados.get("orgao") or "").split())[:300] or None),
        numero_edital=(str(dados.get("numero_edital") or "").strip()[:40] or None),
        ano=ano if isinstance(ano, int) and hoje.year - 2 <= ano <= hoje.year + 2 else None,
        cargos=tuple(cargos),
        inscricao_inicio=inicio,
        inscricao_fim=fim,
        data_prova=prova,
        taxa_min=min(taxas) if taxas else None,
        taxa_max=max(taxas) if taxas else None,
        isencoes=isencoes,
        isencao_inicio=isencao_inicio if isencoes else None,
        isencao_fim=isencao_fim if isencoes else None,
        avisos=tuple(dict.fromkeys(avisos)),
    )
    return edital, uf
