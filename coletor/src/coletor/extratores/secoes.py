"""Seções do edital que não dependem da banca: isenção de taxa, calendário, disciplinas e prova discursiva.

Funções puras sobre o texto do PDF. Regra geral: na dúvida, não afirmar. O que não for identificado com
segurança fica vazio (ou None) e vira aviso "confira o edital"; nunca se deduz direito de ninguém.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from coletor.extratores.base import CargoExtraido, EventoCalendario, IsencaoPrevista
from coletor.texto import MESES, normalizar, todas_as_datas

# --- isenção ---------------------------------------------------------------------------------------

_TITULO_ISENCAO = re.compile(r"^\s*(\d{1,2})\s*\.?\s*D[AO]S?\s+ISEN[ÇC](?:[ÃA]O|[ÕO]ES)\b", re.MULTILINE)
_TITULO_SECAO = re.compile(r"^\s*(\d{1,2})\s*\.?\s+D[AO]S?\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{3}", re.MULTILINE)
_MAX_SECAO = 20_000
_MAX_DIAS_PEDIDO = 120

# Ordem importa só para a leitura; cada tipo é procurado na lista de hipóteses do edital (subitem x.1).
# Termos sobre o texto normalizado (minúsculas, sem acento).
_TIPOS_ISENCAO: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CADUNICO", re.compile(r"cadunico|cadastro unico")),
    ("DOADOR_MEDULA", re.compile(r"\bmedula\b")),
    # "doadoras de sangue", "doação de sangue"; "plasma sanguíneo" não conta (é outro tipo).
    ("DOADOR_SANGUE", re.compile(r"\bdoa\w*\s(?:\w+\s){0,3}?sangue\b")),
    ("DOADOR_PLASMA", re.compile(r"\bplasma\b")),
    ("JURADO", re.compile(r"\bjurad[oa]s?\b")),
    ("MESARIO_ELEITORAL", re.compile(r"servico eleitoral|trabalhos? eleitora|mesari|eleitor\w* convocad")),
    ("PESSOA_COM_DEFICIENCIA", re.compile(r"\b(?:pessoas?|candidat[oa]s?) com deficiencia|\(pcd\)")),
    ("VITIMA_VIOLENCIA_DOMESTICA", re.compile(r"violencia domestica")),
    ("ESTUDANTE", re.compile(r"\bestudantes?\b")),
    ("DESEMPREGADO", re.compile(r"\bdesempregad")),
)
_OUTRAS_ISENCOES: tuple[tuple[re.Pattern[str], str], ...] = ((re.compile(r"\bleite\b"), "Doadores de leite humano"),)


@dataclass(frozen=True)
class Isencoes:
    tipos: tuple[IsencaoPrevista, ...] = ()
    inicio: date | None = None
    fim: date | None = None
    avisos: tuple[str, ...] = ()


def secao_isencao(texto: str) -> str | None:
    """Texto do item "DA ISENÇÃO" (até o próximo item numerado de primeiro nível)."""
    titulo = _TITULO_ISENCAO.search(texto)
    if titulo is None:
        return None
    numero = int(titulo.group(1))
    for proximo in _TITULO_SECAO.finditer(texto, titulo.end()):
        if int(proximo.group(1)) > numero:
            return texto[titulo.start() : min(proximo.start(), titulo.start() + _MAX_SECAO)]
    return texto[titulo.start() : titulo.start() + _MAX_SECAO]


def extrair_isencoes(texto: str) -> Isencoes:
    secao = secao_isencao(texto)
    if secao is None:
        if re.search(r"isencao", normalizar(texto)):
            return Isencoes(avisos=("isenção citada, mas a seção não foi identificada: confira o edital",))
        return Isencoes()

    numero = int(_TITULO_ISENCAO.match(secao).group(1))  # type: ignore[union-attr]
    # As hipóteses ficam no x.1 (e nos x.1.y); o resto da seção trata de documentos, recursos e prazos.
    fim_hipoteses = re.search(rf"^\s*{numero}\.2\b", secao, re.MULTILINE)
    hipoteses = normalizar(secao[: fim_hipoteses.start()] if fim_hipoteses else secao)

    tipos = [IsencaoPrevista(codigo) for codigo, padrao in _TIPOS_ISENCAO if padrao.search(hipoteses)]
    outras = [descricao for padrao, descricao in _OUTRAS_ISENCOES if padrao.search(hipoteses)]
    if outras:
        tipos.append(IsencaoPrevista("OUTRA", "; ".join(outras)))
    if not tipos:
        return Isencoes(avisos=("seção de isenção sem tipo reconhecido: confira o edital",))

    inicio, fim = periodo_do_pedido(secao)
    avisos = () if inicio else ("período para pedir isenção não identificado: confira o edital",)
    return Isencoes(tuple(tipos), inicio, fim, avisos)


def periodo_do_pedido(secao: str) -> tuple[date | None, date | None]:
    normal = normalizar(secao)
    for m in re.finditer(r"solicitad|requerid|periodo", normal):
        datas = datas_com_ano_inferido(normal[m.start() : m.start() + 420])
        if len(datas) >= 2 and 0 <= (datas[1] - datas[0]).days <= _MAX_DIAS_PEDIDO:
            return datas[0], datas[1]
    return None, None


_DIA_MES = re.compile(r"\b(\d{1,2})(?:o)?\s+de\s+([a-z]+)(?:\s+de\s+(\d{4}))?")


def datas_com_ano_inferido(trecho: str) -> list[date]:
    """Como todas_as_datas, mas aceita "do dia 20 de outubro e ... 18 de novembro de 2026": a data sem ano
    recebe o ano da próxima data completa (ou o anterior, se o mês for maior: "20 de dezembro a 5 de janeiro")."""
    normal = normalizar(trecho)
    partes: list[tuple[int, int, int | None]] = []
    for m in _DIA_MES.finditer(normal):
        if mes := MESES.get(m.group(2)):
            partes.append((int(m.group(1)), mes, int(m.group(3)) if m.group(3) else None))
    if not partes:
        return todas_as_datas(trecho)
    datas: list[date] = []
    for i, (dia, mes, ano) in enumerate(partes):
        if ano is None:
            seguinte = next(((m, a) for _, m, a in partes[i + 1 :] if a is not None), None)
            if seguinte is None:
                continue
            ano = seguinte[1] - 1 if mes > seguinte[0] else seguinte[1]
        try:
            datas.append(date(ano, mes, dia))
        except ValueError:
            continue
    return datas or todas_as_datas(trecho)


# --- calendário --------------------------------------------------------------------------------------

_CRONOGRAMA = re.compile(r"^.*\bCRONOGRAMA\b.*$", re.MULTILINE)
_DATA_LINHA = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
_FIM_ANEXO = re.compile(r"^\s*ANEXO\s+[IVXL]+\b", re.MULTILINE)

# Eventos-chave do cronograma, com nomes próprios (não se copia o texto do edital). A ordem decide o
# primeiro que casa; a mesma chave só entra uma vez (a primeira ocorrência).
_EVENTOS_CHAVE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Pedido de isenção da taxa", re.compile(r"(?:pedidos?|solicitac\w+|requerimentos?) de isencao")),
    ("Inscrições", re.compile(r"periodo de inscric|^inscricoes\b|recebimento das inscric")),
    ("Prova objetiva e discursiva", re.compile(r"(?:aplicacao|realizacao) das? provas? objetiva.*discursiva")),
    ("Prova objetiva", re.compile(r"(?:aplicacao|realizacao) das? provas? objetiva")),
    ("Prova discursiva", re.compile(r"(?:aplicacao|realizacao) das? provas? discursiva")),
    ("Prova prática", re.compile(r"(?:aplicacao|realizacao) das? provas? pratica")),
    ("Gabarito preliminar", re.compile(r"gabarito preliminar")),
    ("Resultado final", re.compile(r"resultado final|resultado definitivo do concurso|homologacao")),
)
# Linhas sobre o andamento de outro evento ("Publicação do resultado dos pedidos de isenção", "Recursos contra
# o gabarito") não são o evento em si. Gabarito e resultado final são, por natureza, uma publicação.
_EVENTOS_PUBLICACAO = frozenset({"Gabarito preliminar", "Resultado final"})
_ACOMPANHAMENTO = re.compile(r"^(?:publicac|divulgac|interposic|recurs|resultado|convocac|prazo)")
_FAIXA_QUEBRADA = re.compile(r"\d{1,2}/\d{1,2}/\d{4}\s+(?:a|ate)\s*$")


def calendario(
    texto: str,
    isencoes: Isencoes,
    inscricao: tuple[date | None, date | None],
    data_prova: date | None,
) -> tuple[EventoCalendario, ...]:
    """Cronograma do anexo quando existe; senão, os marcos que o próprio edital já trouxe (isenção,
    inscrições, prova)."""
    eventos = list(_eventos_do_cronograma(texto))
    if isencoes.tipos and isencoes.inicio:
        # O período do item "DA ISENÇÃO" vale mais que o cronograma "previsto" (às vezes divergem em um dia).
        eventos = [e for e in eventos if e.evento != "Pedido de isenção da taxa"]
        eventos.append(EventoCalendario("Pedido de isenção da taxa", isencoes.inicio, isencoes.fim))
    nomes = {e.evento for e in eventos}
    if "Inscrições" not in nomes and (inscricao[0] or inscricao[1]):
        eventos.append(EventoCalendario("Inscrições", inscricao[0], inscricao[1]))
    if not nomes & {"Prova objetiva e discursiva", "Prova objetiva"}:
        eventos.append(EventoCalendario("Prova objetiva", data_prova, data_prova))
    return tuple(sorted(eventos, key=lambda e: (e.inicio is None, e.inicio or date.max, e.fim or date.max)))


def _eventos_do_cronograma(texto: str) -> list[EventoCalendario]:
    titulo = None
    for m in _CRONOGRAMA.finditer(texto):
        if _DATA_LINHA.search(texto, m.end(), m.end() + 600):
            titulo = m
            break
    if titulo is None:
        return []
    fim = _FIM_ANEXO.search(texto, titulo.end())
    linhas = _juntar_faixas(texto[titulo.end() : fim.start() if fim else titulo.end() + 15_000].splitlines())

    eventos: dict[str, EventoCalendario] = {}
    pendente: list[str] = []
    for linha in linhas:
        datas = _DATA_LINHA.findall(linha)
        if not datas:
            if linha.strip():
                pendente.append(linha.strip())
            continue
        rotulo = normalizar(" ".join([*pendente[-3:], _DATA_LINHA.sub(" ", linha)]))
        pendente = []
        convertidas = todas_as_datas(" ".join(datas))
        if not convertidas:
            continue
        for nome, padrao in _EVENTOS_CHAVE:
            if nome not in _EVENTOS_PUBLICACAO and _ACOMPANHAMENTO.match(rotulo):
                continue
            if padrao.search(rotulo):
                if nome not in eventos:
                    eventos[nome] = EventoCalendario(nome, convertidas[0], convertidas[-1])
                break
    return list(eventos.values())


def _juntar_faixas(linhas: list[str]) -> list[str]:
    """ "Período de Inscrição 09/07/2026 a" + "07/08/2026" → uma linha só."""
    juntas: list[str] = []
    for linha in linhas:
        if juntas and _FAIXA_QUEBRADA.search(normalizar(juntas[-1])) and _DATA_LINHA.match(linha.strip()):
            juntas[-1] = f"{juntas[-1]} {linha.strip()}"
        else:
            juntas.append(linha)
    return juntas


# --- disciplinas ---------------------------------------------------------------------------------------

_CABECALHO_DISCIPLINAS = re.compile(r"^(?:disciplinas?|componentes? curricular\w*)\b")
_LINHA_DISCIPLINA = re.compile(
    r"^(?:\d{1,2}\s*[.)]\s*)?(?P<nome>[^\d].*?[a-z)])\s+(?P<nums>\d{1,3}(?:[\s,]+\d+(?:,\d+)?)*)$"
)
_SO_NUMEROS = re.compile(r"^\d{1,3}(?:[\s,]+\d+(?:,\d+)?)*$")
_FIM_QUADRO = re.compile(r"^(?:total\b|\d+(?:\.\d+)+\s|\d+\.\d+\.|anexo\b)")
_NAO_DISCIPLINA = re.compile(
    r"^(?:modulo\b|n\.?o de|questoes|peso|pontos|pontuacao|prova\b|conhecimentos (?:gerais|especificos|basicos)$)"
)
_PALAVRAS_GENERICAS = frozenset(
    {"cargo", "cargos", "nivel", "prova", "objetiva", "area", "areas", "todas", "todos", "especialidade",
     "especialidades", "para", "dos", "das", "de", "do", "da", "e", "os", "as", "perfil", "perfis", "quadro"}
)  # fmt: skip


@dataclass(frozen=True)
class QuadroDisciplinas:
    rotulo: str  # texto acima do quadro (cargo, nível ou "todos")
    disciplinas: tuple[str, ...]


def quadros_de_disciplinas(texto: str) -> list[QuadroDisciplinas]:
    linhas = texto.splitlines()
    quadros: list[QuadroDisciplinas] = []
    ultimo_fim = -10
    i = 0
    while i < len(linhas):
        if not _CABECALHO_DISCIPLINAS.match(normalizar(linhas[i])) or "quest" not in normalizar(
            " ".join(linhas[i : i + 3])
        ):
            i += 1
            continue
        anteriores = [
            linhas[j].strip()
            for j in range(max(ultimo_fim + 1, i - 3), i)
            if linhas[j].strip() and not normalizar(linhas[j]).startswith("modulo")
        ]
        disciplinas, i = _ler_quadro(linhas, i + 1)
        continua_anterior = quadros and not anteriores and i - ultimo_fim < 40
        if continua_anterior:
            anterior = quadros.pop()
            quadros.append(QuadroDisciplinas(anterior.rotulo, _sem_repetir([*anterior.disciplinas, *disciplinas])))
        elif disciplinas:
            quadros.append(QuadroDisciplinas(" ".join(anteriores[-2:]), tuple(disciplinas)))
        ultimo_fim = i
    return quadros


def _ler_quadro(linhas: Sequence[str], inicio: int) -> tuple[list[str], int]:
    disciplinas: list[str] = []
    pendente: str | None = None
    i = inicio
    while i < len(linhas) and i < inicio + 60:
        linha = linhas[i].strip()
        normal = normalizar(linha)
        if not linha:
            i += 1
            continue
        if _FIM_QUADRO.match(normal):
            if normal.startswith("total") and _proximo_e_cabecalho(linhas, i + 1):
                i += 1
                continue
            break
        if _NAO_DISCIPLINA.match(normal) or _CABECALHO_DISCIPLINAS.match(normal):
            pendente = None
            i += 1
            continue
        if _SO_NUMEROS.match(normal):
            if pendente:
                # Nome quebrado em volta dos números: "Noções de Informática e Proteção de" / "5" / "Dados".
                cauda = linhas[i + 1].strip() if i + 1 < len(linhas) else ""
                if cauda and not re.search(r"\d", cauda) and not _NAO_DISCIPLINA.match(normalizar(cauda)):
                    pendente = f"{pendente} {cauda}"
                    i += 1
                disciplinas.append(pendente)
                pendente = None
            i += 1
            continue
        if m := _LINHA_DISCIPLINA.match(linha):
            disciplinas.append(m.group("nome").strip(" .-–"))
            pendente = None
        elif re.search(r"\d", linha) or len(linha) > 90:
            break
        else:
            pendente = linha if pendente is None else f"{pendente} {linha}"
        i += 1
    return [d for d in (_limpar(d) for d in disciplinas) if d], i


def _proximo_e_cabecalho(linhas: Sequence[str], inicio: int) -> bool:
    for linha in linhas[inicio : inicio + 3]:
        normal = normalizar(linha)
        if normal:
            return normal.startswith("modulo") or bool(_CABECALHO_DISCIPLINAS.match(normal))
    return False


def _limpar(nome: str) -> str | None:
    nome = re.sub(r"\s+", " ", nome).strip(" .:-–")
    if not 3 <= len(nome) <= 120 or not nome[0].isalpha():
        return None
    return nome


def _sem_repetir(nomes: Sequence[str]) -> tuple[str, ...]:
    vistos: dict[str, str] = {}
    for nome in nomes:
        vistos.setdefault(normalizar(nome), nome)
    return tuple(vistos.values())


def _radicais(texto: str) -> set[str]:
    # Radical de 5 letras: "judiciária" (cargo) casa com "judiciário" (quadro).
    palavras = re.findall(r"[a-z]+", normalizar(texto))
    return {p[:5] if len(p) > 5 else p for p in palavras if p not in _PALAVRAS_GENERICAS and len(p) >= 2}


def atribuir_disciplinas(
    cargos: Sequence[CargoExtraido], quadros: Sequence[QuadroDisciplinas]
) -> tuple[list[CargoExtraido], bool]:
    """Liga cada cargo ao quadro de disciplinas dele. Devolve os cargos e se algum ficou sem quadro."""
    if not quadros or not cargos:
        return list(cargos), bool(quadros)
    if len(quadros) == 1 or len({q.disciplinas for q in quadros}) == 1:
        return [replace(c, disciplinas=quadros[0].disciplinas) for c in cargos], False

    resultado: list[CargoExtraido] = []
    faltou = False
    for cargo in cargos:
        alvo = _radicais(f"{cargo.nome} {cargo.especialidade or ''}")
        nivel = (cargo.escolaridade or "").lower()
        pontos = []
        for quadro in quadros:
            rotulo = _radicais(quadro.rotulo)
            ponto = len(alvo & rotulo)
            if nivel and _radicais(nivel) & rotulo:
                ponto += 1
            pontos.append(ponto)
        melhor = max(pontos)
        escolhidos = {quadros[n].disciplinas for n, p in enumerate(pontos) if p == melhor}
        if melhor > 0 and len(escolhidos) == 1:
            resultado.append(replace(cargo, disciplinas=escolhidos.pop()))
        else:
            resultado.append(cargo)
            faltou = True
    return resultado, faltou


# --- prova discursiva / redação ------------------------------------------------------------------------

_ANEXOS = re.compile(r"^\s*ANEXO\s+[IVXL]+\s*[–-]", re.MULTILINE)
_DISCURSIVA = re.compile(
    r"prova (?:escrita )?discursiva|provas (?:escritas )?discursivas|prova de redacao|prova escrita dissertativa"
)
_RESTRICAO = re.compile(r"(?:exclusiv\w*|somente|apenas) (?:para )?(?:o|os) cargos? de ([^.;:]{3,120})")
# Onde a lista de cargos da restrição termina: "..., de caráter eliminatório", "..., que", "..., conforme".
_FIM_RESTRICAO = re.compile(r",?\s+(?:de carater|que|sendo|conforme|com|nos termos|observad|ambas?|a ser|em)\b")


def redacao_por_cargo(texto: str, cargos: Sequence[CargoExtraido]) -> tuple[list[CargoExtraido], bool]:
    """Marca tem_redacao em cada cargo. Devolve os cargos e se ficou incerto (aviso "confira o edital")."""
    if not cargos:
        return list(cargos), False
    anexo = _ANEXOS.search(texto)
    corpo = normalizar(texto[: anexo.start()] if anexo else texto)  # o conteúdo programático cita "Redação Oficial"
    mencoes = [m.start() for m in _DISCURSIVA.finditer(corpo)]
    if not mencoes:
        return [replace(c, tem_redacao=False) for c in cargos], False

    janelas = [corpo[max(0, p - 60) : p + 260] for p in mencoes[:12]]
    if any(re.search(r"\bexceto\b|com excecao", j) for j in janelas):
        return list(cargos), True
    restritos = {m.group(1) for j in janelas for m in _RESTRICAO.finditer(j)}
    if not restritos:
        return [replace(c, tem_redacao=True) for c in cargos], False

    # O nome do cargo precisa aparecer na restrição: "Delegado de Polícia" não arrasta "Agente de Polícia".
    restricao = " ".join(_FIM_RESTRICAO.split(r, maxsplit=1)[0] for r in restritos)
    marcados = [replace(c, tem_redacao=normalizar(c.nome) in restricao) for c in cargos]
    if not any(c.tem_redacao for c in marcados):
        return list(cargos), True
    return marcados, False
