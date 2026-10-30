"""Resumo próprio de cada concurso, gerado por regras a partir dos campos estruturados (seção 4.5 do contexto).

Princípios: frases curtas em português simples; só fatos que o coletor extraiu (campo ausente = frase omitida,
nunca inventada); linguagem informativa ("o edital prevê"); nada copiado do edital ou de notícias. As datas
são absolutas: contagens como "faltam 3 dias" são feitas no navegador, para o HTML não envelhecer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from coletor.texto import slugificar

SITUACOES_OPORTUNIDADE = frozenset({"PREVISTO", "INSCRICOES_ABERTAS"})

NIVEIS = {"FUNDAMENTAL": "fundamental", "MEDIO": "médio", "TECNICO": "técnico", "SUPERIOR": "superior"}
ORDEM_NIVEIS = ("FUNDAMENTAL", "MEDIO", "TECNICO", "SUPERIOR")

AREAS = {
    "ADMINISTRATIVA": "administrativa",
    "BANCARIA": "bancária",
    "CONTROLE_FISCAL": "controle e fiscal",
    "EDUCACAO": "educação",
    "ENGENHARIA_ARQUITETURA": "engenharia e arquitetura",
    "JURIDICA": "jurídica",
    "LEGISLATIVA": "legislativa",
    "MEIO_AMBIENTE_AGRARIA": "meio ambiente e agrária",
    "POLICIAL_SEGURANCA": "policial e segurança",
    "SAUDE": "saúde",
    "TI": "TI",
    "ASSISTENCIA_SOCIAL": "assistência social",
    "COMUNICACAO_ARTES": "comunicação e artes",
    "OPERACIONAL": "operacional",
}
MAX_AREAS_NO_TEXTO = 4

ISENCOES = {
    "CADUNICO": "inscritos no CadÚnico",
    "DOADOR_MEDULA": "doadores de medula óssea",
    "DOADOR_SANGUE": "doadores de sangue",
    "DOADOR_PLASMA": "doadores de plasma",
    "JURADO": "jurados",
    "MESARIO_ELEITORAL": "mesários e trabalhadores das eleições",
    "PESSOA_COM_DEFICIENCIA": "pessoas com deficiência",
    "VITIMA_VIOLENCIA_DOMESTICA": "mulheres vítimas de violência doméstica",
    "ESTUDANTE": "estudantes",
    "DESEMPREGADO": "desempregados",
}
ORDEM_ISENCOES = tuple(ISENCOES)
MAX_ISENCOES_NO_TEXTO = 3

MAX_SLUG = 80


@dataclass(frozen=True)
class DadosConcurso:
    titulo: str
    situacao: str
    banca: str | None = None
    orgao: str | None = None
    abrangencia: str | None = None
    uf: str | None = None
    municipio: str | None = None
    ano: int | None = None
    total_vagas: int | None = None
    cadastro_reserva: bool = False
    salario_min: Decimal | None = None
    salario_max: Decimal | None = None
    escolaridades: Sequence[str] = ()
    areas: Sequence[str] = ()
    inscricao_inicio: date | None = None
    inscricao_fim: date | None = None
    data_prova: date | None = None
    taxa_min: Decimal | None = None
    taxa_max: Decimal | None = None
    isencoes: Sequence[str] = ()
    isencao_fim: date | None = None
    tem_avisos: bool = False
    unificado: bool = False
    cargos: Sequence[str] = field(default_factory=tuple)


def e_oportunidade(situacao: str, isencao_fim: date | None, hoje: date) -> bool:
    """O que vai ao site (seção 4.3): previsto, inscrições abertas ou por abrir, ou prazo de isenção em curso."""
    if situacao == "ENCERRADO":
        return False
    return situacao in SITUACOES_OPORTUNIDADE or (isencao_fim is not None and isencao_fim >= hoje)


def gerar_resumo(dados: DadosConcurso, hoje: date) -> str:
    frases = [_abertura(dados, hoje)]
    if dados.situacao == "PREVISTO" and dados.inscricao_inicio is None:
        frases.append("Ainda não há edital publicado.")
    frases.extend(f for f in (_inscricoes(dados, hoje), _prova(dados), _isencao(dados, hoje)) if f)
    if dados.banca:
        frases.append(f"Banca: {dados.banca}.")
    if dados.tem_avisos:
        frases.append("Alguns dados não foram identificados automaticamente: confira o edital.")
    return " ".join(frases)


def gerar_slug(dados: DadosConcurso, ocupados: set[str], ano_padrao: int) -> str:
    """URL amigável e estável (gravada uma vez, nunca recalculada): "<órgão>-<ano>", com sufixo se já existir."""
    base = slugificar(dados.orgao or dados.titulo) or "concurso"
    if dados.unificado and "unificado" not in base:
        base = "concurso-nacional-unificado"
    ano = str(dados.ano or ano_padrao)
    if len(base) > MAX_SLUG - len(ano) - 4:
        base = base[: MAX_SLUG - len(ano) - 4].rsplit("-", 1)[0]
    candidato = f"{base}-{ano}"
    sufixo = 2
    while candidato in ocupados:
        candidato = f"{base}-{ano}-{sufixo}"
        sufixo += 1
    return candidato


# --- frases ----------------------------------------------------------------------------------------------------


def _abertura(d: DadosConcurso, hoje: date) -> str:
    sujeito = d.orgao or d.titulo
    if d.abrangencia == "MUNICIPAL" and d.municipio and d.uf and d.municipio.lower() not in sujeito.lower():
        sujeito = f"{sujeito} ({d.municipio}/{d.uf})"
    elif d.abrangencia in ("ESTADUAL", "MUNICIPAL") and d.uf and f"({d.uf})" not in sujeito:
        sujeito = f"{sujeito} ({d.uf})"

    if d.situacao == "PREVISTO" and d.inscricao_inicio is None:
        verbo = "tem concurso previsto"
    elif d.inscricao_inicio is not None and d.inscricao_inicio > hoje:
        verbo = "publicou edital de concurso"
    elif d.situacao == "INSCRICOES_ABERTAS":
        verbo = "abriu concurso"
    else:
        verbo = "tem concurso"

    partes = [f"{sujeito} {verbo}"]
    if d.total_vagas:
        partes.append(f"com {_milhar(d.total_vagas)} {'vaga' if d.total_vagas == 1 else 'vagas'}")
    elif d.cadastro_reserva:
        partes.append("para cadastro de reserva")
    if niveis := [NIVEIS[n] for n in ORDEM_NIVEIS if n in d.escolaridades]:
        partes.append(f"para {'nível' if len(niveis) == 1 else 'níveis'} {_lista(niveis)}")
    texto = " ".join(partes)

    complementos = []
    if salario := _salario(d):
        complementos.append(salario)
    if areas := _areas(d.areas):
        complementos.append(areas)
    if complementos:
        texto = f"{texto}, {', '.join(complementos)}"
    return f"{texto}."


def _salario(d: DadosConcurso) -> str | None:
    if not d.salario_max:
        return None
    if d.salario_min and d.salario_min != d.salario_max:
        return f"salários de {_reais(d.salario_min)} a {_reais(d.salario_max)}"
    return f"salário de {_reais(d.salario_max)}"


def _areas(codigos: Sequence[str]) -> str | None:
    nomes = [AREAS[c] for c in AREAS if c in codigos]
    if not nomes:
        return None
    if len(nomes) > MAX_AREAS_NO_TEXTO:
        return f"em {len(nomes)} áreas, como {_lista(nomes[:3])}"
    return f"{'na área' if len(nomes) == 1 else 'nas áreas'} {_lista(nomes)}"


def _inscricoes(d: DadosConcurso, hoje: date) -> str | None:
    if d.inscricao_inicio and d.inscricao_inicio > hoje and d.inscricao_fim:
        frase = f"Inscrições de {_data(d.inscricao_inicio)} a {_data(d.inscricao_fim)}"
    elif d.inscricao_fim and d.inscricao_fim >= hoje:
        frase = f"Inscrições até {_data(d.inscricao_fim)}"
    elif d.inscricao_fim:
        frase = f"Inscrições encerradas em {_data(d.inscricao_fim)}"
    else:
        frase = None
    taxa = _taxa(d)
    if frase and taxa:
        return f"{frase}, {taxa}."
    if frase:
        return f"{frase}."
    return f"{taxa[0].upper()}{taxa[1:]}." if taxa else None


def _taxa(d: DadosConcurso) -> str | None:
    if not d.taxa_max:
        return None
    if d.taxa_min and d.taxa_min != d.taxa_max:
        return f"taxas de {_reais(d.taxa_min)} a {_reais(d.taxa_max)}"
    return f"taxa de {_reais(d.taxa_max)}"


def _prova(d: DadosConcurso) -> str | None:
    return f"Prova em {_data(d.data_prova)}." if d.data_prova else None


def _isencao(d: DadosConcurso, hoje: date) -> str | None:
    if not d.isencoes:
        return None
    conhecidas = [ISENCOES[c] for c in ORDEM_ISENCOES if c in d.isencoes]
    if len(conhecidas) > MAX_ISENCOES_NO_TEXTO or (conhecidas and "OUTRA" in d.isencoes):
        quem = f"{', '.join(conhecidas[:MAX_ISENCOES_NO_TEXTO])} e outros casos"
    elif conhecidas:
        quem = _lista(conhecidas)
    else:
        quem = "alguns casos"
    frase = f"O edital prevê isenção da taxa para {quem}."
    if d.isencao_fim and d.isencao_fim >= hoje:
        frase = f"{frase} Pedidos de isenção até {_data(d.isencao_fim)}."
    return frase


# --- formatação ------------------------------------------------------------------------------------------------


def _lista(itens: Sequence[str]) -> str:
    if len(itens) <= 1:
        return "".join(itens)
    return f"{', '.join(itens[:-1])} e {itens[-1]}"


def _data(dia: date) -> str:
    return dia.strftime("%d/%m/%Y")


def _milhar(numero: int) -> str:
    return f"{numero:,}".replace(",", ".")


def _reais(valor: Decimal) -> str:
    inteiro, centavos = f"{valor:.2f}".split(".")
    return f"R$ {_milhar(int(inteiro))},{centavos}"
