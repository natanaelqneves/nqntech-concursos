"""Extrator por regras para editais da FGV.

Baseado no edital TJPB 2026 (Edital nº 01/2026) e no padrão FGV: quadro de vagas no item "DOS CARGOS" com
contexto acima da tabela ("NÍVEL SUPERIOR – CARGO: ANALISTA", "REMUNERAÇÃO: R$ ..."), linhas
"<especialidade> <vagas> <AC> <PCD> ... R$ <valor>" e nomes longos quebrados em duas linhas no texto do PDF:

    TI – Desenvolvimento de          ← começo do nome (linha sem números)
    10 6 1 3 0 0 R$ 7.526,14         ← números sem nome: o nome está em volta
    Sistemas                         ← fim do nome

Quando o quadro de vagas não sai legível do PDF (tabelas por localidade, quadros em anexo), os cargos ainda
são reconhecidos, nesta ordem, por:
- linhas "Enfermeiro Obstetra 40h R$ 8.421,31" do anexo de remuneração (SES-TO 2026), que trazem o salário;
- títulos "CARGO: ANALISTA DE TI - PERFIL: DESENVOLVIMENTO" (anexos de atribuições, Dataprev 2026) ou
  "CARGO DE NÍVEL SUPERIOR - COORDENADOR PEDAGÓGICO I - 40h" (Prefeitura do Salvador 2026);
- a abertura do edital: "...concurso público para os cargos de Delegado de Polícia, Agente de Polícia Judiciária
  e Papiloscopista Policial, do Quadro..." (PCPR 2026).
Isso basta para classificar a área; o que faltar (vagas, salário) fica com o aviso "confira o edital".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from coletor.extratores.base import CargoExtraido, EditalExtraido
from coletor.extratores.secoes import (
    atribuir_disciplinas,
    calendario,
    extrair_isencoes,
    quadros_de_disciplinas,
    redacao_por_cargo,
)
from coletor.texto import (
    colapsar_espacos,
    data_por_extenso,
    normalizar,
    titulo_portugues,
    todas_as_datas,
    valores_monetarios,
)

_NUMERO_EDITAL = re.compile(r"EDITAL\s+N\s*[º°o.]*\s*(\d{1,4})\s*/\s*(\d{4})", re.IGNORECASE)
_ORGAO_CABECALHO = (
    re.compile(r"QUADRO DE PESSOAL D[OA]S?\s+(.+)", re.IGNORECASE),
    re.compile(r"CONCURSO P[ÚU]BLICO (?:PARA|D[OA])\s+(?:[OA]\s+)?(.+)", re.IGNORECASE),
)
_VALOR_FIM = r"R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}"
_NUMEROS = r"(?:\d+|CR)(?:\s+(?:\d+|CR|-))*"
_LINHA_COM_SALARIO = re.compile(rf"^(?P<nome>.*?)\s*(?P<nums>{_NUMEROS})\s+(?P<sal>{_VALOR_FIM})\s*\*?$")
_LINHA_SEM_SALARIO = re.compile(rf"^(?P<nome>.*?\D)?\s*(?P<nums>{_NUMEROS})$")
_FIM_DE_TABELA = re.compile(r"^(total\b|\*|\d+(\.\d+)+\s|nota|obs)", re.IGNORECASE)
_NIVEL = re.compile(r"n[ií]vel\s+(superior|m[ée]dio|t[ée]cnico|fundamental)", re.IGNORECASE)
_CARGO_CONTEXTO = re.compile(r"\bcargo\s*:\s*([^\n|]+?)\s*$", re.IGNORECASE | re.MULTILINE)
# Cabeçalho de quadro de vagas: linha curta que começa pelo rótulo da coluna e tem a coluna "Vagas".
_CABECALHO_TABELA = re.compile(r"^(especialidade|cargos?|area|perfil|funcao|emprego)\b.*\bvagas\b")
_ESCOLARIDADE = {"superior": "SUPERIOR", "medio": "MEDIO", "tecnico": "TECNICO", "fundamental": "FUNDAMENTAL"}
_TAXA_MAXIMA_PLAUSIVEL = Decimal("2000")
_ROTULO_CARGO = re.compile(
    r"^CARGOS?(?:\s+DE\s+N[ÍI]VEL\s+(?P<nivel>SUPERIOR|M[ÉE]DIO|T[ÉE]CNICO|FUNDAMENTAL))?\s*[:–-]\s*(?P<resto>.+)$"
)
# Separadores do título do cargo: "- PERFIL: ...", "– ESPECIALIDADE: ...", "- 40h", "- SALVADOR".
_ROTULO_ESPECIALIDADE = re.compile(r"\s+[-–]\s+(?:PERFIL|ESPECIALIDADE|[ÁA]REA|FORMA[ÇC][ÃA]O)\s*:\s*", re.IGNORECASE)
_NUMERACAO = re.compile(r"^\d{1,2}\s*[.)]\s*")
_LINHA_REMUNERACAO = re.compile(
    r"^(?P<nome>[A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\d\n]{2,90}?)\s+\d{1,2}\s?(?:h|horas)\b[^\n]*?\s(?P<sal>R\$\s*\d{1,3}(?:\.\d{3})*,\d{2})$"
)
_ABERTURA_CARGOS = re.compile(r"(?:dos|para os|para o) cargos? de\s+(?P<lista>[^.;]{5,240})", re.IGNORECASE)
# Onde a lista de cargos da abertura termina: ", do Quadro...", ", observado...", ", nos termos...".
_FIM_LISTA = re.compile(
    r",?\s+(?:d[oa]s?|n[oa]s?|conforme|observad[oa]s?|nos termos|que|com|de acordo|sendo|ser[aã]o?|visando|"
    r"a serem|para)\s+(?=[a-záéíóúâêôãõç])",
)
_PALAVRAS_DE_FRASE = frozenset(
    {"que", "deste", "desta", "conforme", "forma", "sera", "serao", "vagas", "edital", "anexo", "nos", "termos",
     "respectivos", "ambito", "posteriormente", "todas", "todos", "diversos", "nivel", "cargos", "cargo"}
)  # fmt: skip


def nome_de_cargo_plausivel(nome: str) -> bool:
    """Filtra o que a leitura de tabelas por texto às vezes devolve como "cargo" (pedaços de frase do edital)."""
    palavras = re.findall(r"[a-z]+", normalizar(nome))
    if not 1 <= len(palavras) <= 9 or not nome[:1].isalpha() or not nome[:1].isupper():
        return False
    if any(c.isdigit() for c in nome):
        return False
    return not set(palavras) & _PALAVRAS_DE_FRASE


@dataclass
class _Tabela:
    escolaridade: str | None
    cargo_base: str | None
    salario_padrao: Decimal | None
    tem_salario_por_linha: bool
    linhas: list[str] = field(default_factory=list)


class ExtratorFGV:
    def extrair(self, texto: str) -> EditalExtraido:
        avisos: list[str] = []
        numero, ano = self._numero_edital(texto)
        if numero is None:
            avisos.append("número do edital não encontrado")

        cargos = self._cargos(texto)
        if not cargos:
            cargos = self._cargos_por_remuneracao(texto)
            if cargos:
                avisos.append("vagas de cada cargo não identificadas: confira o edital")
        if not cargos:
            cargos = self._cargos_por_rotulo(texto) or self._cargos_da_abertura(texto)
            if cargos:
                avisos.append("vagas e salários de cada cargo não identificados: confira o edital")
        if not cargos:
            avisos.append("quadro de cargos/vagas não encontrado: confira o edital")
        elif any(c.escolaridade is None for c in cargos):
            avisos.append("escolaridade não identificada em algum cargo")

        inicio, fim = self._periodo_inscricao(texto)
        if inicio is None or fim is None:
            avisos.append("período de inscrição não encontrado")
        elif fim < inicio:
            avisos.append("período de inscrição incoerente (fim antes do início): confira o edital")
            inicio = fim = None

        isencoes = extrair_isencoes(texto)
        prova = self._data_prova(texto)
        eventos = calendario(texto, isencoes, (inicio, fim), prova)
        if prova is None:
            # Sem data no corpo do edital, o cronograma do anexo pode trazer a "data provável".
            prova = next((e.inicio for e in eventos if e.evento.startswith("Prova objetiva")), None)
        if prova is None:
            avisos.append("data da prova não encontrada")
        elif fim is not None and prova < fim:
            avisos.append("data da prova anterior ao fim das inscrições: confira o edital")

        taxas = self._taxas(texto)
        if not taxas:
            avisos.append("taxa de inscrição não encontrada")
        avisos.extend(isencoes.avisos)

        cargos, faltou_quadro = atribuir_disciplinas(cargos, quadros_de_disciplinas(texto))
        if faltou_quadro:
            avisos.append("disciplinas de algum cargo não identificadas: confira o edital")
        cargos, redacao_incerta = redacao_por_cargo(texto, cargos)
        if redacao_incerta:
            avisos.append("prova discursiva/redação por cargo não identificada: confira o edital")

        return EditalExtraido(
            orgao=self._orgao(texto),
            numero_edital=numero,
            ano=ano,
            cargos=tuple(cargos),
            inscricao_inicio=inicio,
            inscricao_fim=fim,
            data_prova=prova,
            taxa_min=min(taxas) if taxas else None,
            taxa_max=max(taxas) if taxas else None,
            isencoes=isencoes.tipos,
            isencao_inicio=isencoes.inicio,
            isencao_fim=isencoes.fim,
            eventos=eventos,
            avisos=tuple(avisos),
        )

    @staticmethod
    def _numero_edital(texto: str) -> tuple[str | None, int | None]:
        m = _NUMERO_EDITAL.search(texto[:5000])
        if m is None:
            return None, None
        return f"{int(m.group(1)):02d}/{m.group(2)}", int(m.group(2))

    @staticmethod
    def _orgao(texto: str) -> str | None:
        m = _NUMERO_EDITAL.search(texto[:5000])
        cabecalho = colapsar_espacos(texto[: m.start()] if m else texto[:400])
        for padrao in _ORGAO_CABECALHO:
            if achado := padrao.search(cabecalho):
                return titulo_portugues(achado.group(1).strip(" -–,"))
        return None

    def _cargos(self, texto: str) -> list[CargoExtraido]:
        # split("\n") e não splitlines(): splitlines também quebra em \f e apagaria as quebras de página.
        linhas = [linha.strip(" \t\r") for linha in texto.split("\n")]
        cargos: dict[tuple[str, str | None], CargoExtraido] = {}
        for indice, linha in enumerate(linhas):
            cabecalho = normalizar(linha)
            if len(cabecalho.split()) > 15 or not _CABECALHO_TABELA.match(cabecalho):
                continue
            tabela = self._contexto_tabela(linhas[max(0, indice - 8) : indice], cabecalho)
            for cargo in self._linhas_da_tabela(linhas[indice + 1 :], tabela):
                if not nome_de_cargo_plausivel(cargo.especialidade or cargo.nome):
                    continue
                cargos.setdefault((normalizar(cargo.nome), normalizar(cargo.especialidade or "")), cargo)
        return list(cargos.values())

    @staticmethod
    def _cargos_por_remuneracao(texto: str) -> list[CargoExtraido]:
        cargos: dict[tuple[str, str], CargoExtraido] = {}
        for linha in texto.split("\n"):
            achado = _LINHA_REMUNERACAO.match(linha.strip())
            if achado is None:
                continue
            texto_nome = re.sub(r"\s+[-–]\s+", " - ", colapsar_espacos(achado.group("nome")))
            nome, _, especialidade = texto_nome.partition(" - ")
            if not nome_de_cargo_plausivel(nome) or (especialidade and not nome_de_cargo_plausivel(especialidade)):
                continue
            salario = valores_monetarios(achado.group("sal"))
            cargo = CargoExtraido(
                nome=nome, especialidade=especialidade or None, salario=salario[0] if salario else None
            )
            cargos.setdefault((normalizar(nome), normalizar(especialidade)), cargo)
        # Uma ou duas linhas soltas nesse formato não fazem um quadro (podem ser exemplos no meio do texto).
        return list(cargos.values()) if len(cargos) >= 3 else []

    @staticmethod
    def _cargos_por_rotulo(texto: str) -> list[CargoExtraido]:
        cargos: dict[tuple[str, str], CargoExtraido] = {}
        linhas = texto.split("\n")
        for indice, linha in enumerate(linhas):
            rotulo = _ROTULO_CARGO.match(linha.strip())
            if rotulo is None:
                continue
            resto = rotulo.group("resto")
            # Perfil quebrado em duas linhas: "PERFIL: 2. ARQUITETURA, ENGENHARIA E" + "SUSTENTAÇÃO TECNOLÓGICA".
            seguinte = linhas[indice + 1].strip() if indice + 1 < len(linhas) else ""
            if re.search(r"(?:,|\s(?:E|DE|DA|DO|DAS|DOS))$", resto) and seguinte.isupper() and len(seguinte) < 60:
                resto = f"{resto} {seguinte}"
            partes = _ROTULO_ESPECIALIDADE.split(resto, maxsplit=1)
            # Sem rótulo de especialidade, o que vem depois do 1º " - " é carga horária ou local ("- 40h - SALVADOR").
            nome = re.split(r"\s+[-–]\s+", partes[0], maxsplit=1)[0]
            nome = titulo_portugues(_NUMERACAO.sub("", nome).strip(" *.:–-"))
            especialidade = titulo_portugues(_NUMERACAO.sub("", partes[1]).strip(" *.:–-")) if len(partes) > 1 else None
            if not nome_de_cargo_plausivel(nome) or (especialidade and len(especialidade.split()) > 12):
                continue
            nivel = rotulo.group("nivel")
            cargo = CargoExtraido(
                nome=nome,
                especialidade=especialidade or None,
                escolaridade=_ESCOLARIDADE[normalizar(nivel)] if nivel else None,
            )
            cargos.setdefault((normalizar(nome), normalizar(especialidade or "")), cargo)
        return list(cargos.values())

    @staticmethod
    def _cargos_da_abertura(texto: str) -> list[CargoExtraido]:
        achado = _ABERTURA_CARGOS.search(colapsar_espacos(texto[:8000]))
        if achado is None:
            return []
        lista = _FIM_LISTA.split(achado.group("lista"), maxsplit=1)[0]
        nomes = [re.sub(r"\s+e$", "", colapsar_espacos(n).strip(" ,")) for n in re.split(r",\s*|\s+e\s+", lista)]
        return [CargoExtraido(nome=titulo_portugues(n)) for n in nomes if nome_de_cargo_plausivel(n)]

    @staticmethod
    def _contexto_tabela(anteriores: list[str], cabecalho: str) -> _Tabela:
        contexto = "\n".join(anteriores)
        nivel = _NIVEL.search(contexto)
        cargo = _CARGO_CONTEXTO.search(contexto)
        salarios = valores_monetarios(contexto)
        return _Tabela(
            escolaridade=_ESCOLARIDADE[normalizar(nivel.group(1))] if nivel else None,
            cargo_base=titulo_portugues(cargo.group(1).strip(" *")) if cargo else None,
            salario_padrao=salarios[-1] if salarios else None,
            tem_salario_por_linha=bool(re.search(r"remuneracao|salario|vencimento", cabecalho)),
        )

    def _linhas_da_tabela(self, seguintes: list[str], tabela: _Tabela) -> list[CargoExtraido]:
        cargos: list[CargoExtraido] = []
        prefixo: list[str] = []
        pendente: dict | None = None  # linha só com números esperando o fim do nome na linha seguinte
        padrao = _LINHA_COM_SALARIO if tabela.tem_salario_por_linha else _LINHA_SEM_SALARIO

        for linha in seguintes[:80]:
            if "\f" in linha:
                # Tabela continua na página seguinte: o que veio antes da quebra era rodapé, não nome de cargo.
                prefixo = []
                continue
            if not linha:
                continue
            if _FIM_DE_TABELA.match(linha):
                break
            achado = padrao.match(linha)
            if achado is None:
                if pendente is not None:
                    pendente["nome"] = colapsar_espacos(f"{pendente['nome']} {linha}")
                    cargos.append(self._montar_cargo(pendente, tabela))
                    pendente = None
                else:
                    prefixo.append(linha)
                continue
            if pendente is not None:
                cargos.append(self._montar_cargo(pendente, tabela))
                pendente = None
            nome = colapsar_espacos(" ".join([*prefixo, achado.group("nome") or ""]))
            prefixo = []
            linha_cargo = {"nome": nome, "nums": achado.group("nums"), "sal": achado.groupdict().get("sal")}
            if achado.group("nome"):
                cargos.append(self._montar_cargo(linha_cargo, tabela))
            else:
                pendente = linha_cargo
        if pendente is not None and pendente["nome"]:
            cargos.append(self._montar_cargo(pendente, tabela))
        return [c for c in cargos if c.nome]

    @staticmethod
    def _montar_cargo(linha: dict, tabela: _Tabela) -> CargoExtraido:
        numeros = linha["nums"].split()
        primeiro = numeros[0] if numeros else ""
        salarios = valores_monetarios(linha["sal"] or "")
        nome_linha = linha["nome"].strip(" *-–")
        if tabela.cargo_base:
            nome, especialidade = tabela.cargo_base, nome_linha or None
        else:
            nome, especialidade = nome_linha, None
        return CargoExtraido(
            nome=nome,
            especialidade=especialidade,
            escolaridade=tabela.escolaridade,
            vagas=int(primeiro) if primeiro.isdigit() else None,
            cadastro_reserva=primeiro.upper() == "CR" or "CR" in (n.upper() for n in numeros),
            salario=salarios[0] if salarios else tabela.salario_padrao,
        )

    @staticmethod
    def _periodo_inscricao(texto: str) -> tuple[date | None, date | None]:
        normal = normalizar(texto)
        for m in re.finditer(r"inscric(?:ao|oes)", normal):
            janela = normal[m.start() : m.start() + 300]
            if not re.search(r"periodo|a partir|das \d{1,2}h|entre|de \d{1,2}/\d{1,2}", janela):
                continue
            datas = todas_as_datas(janela)
            if len(datas) >= 2:
                return datas[0], datas[1]
        return None, None

    @staticmethod
    def _data_prova(texto: str) -> date | None:
        normal = normalizar(texto)
        padroes = (
            r"provas?\b[^.]{0,900}?\bser(?:a|ao)\s+(?:realizadas?|aplicadas?)\s+"
            r"(?:na data provavel de|no dia|na data de|em)\s+([^.;]{0,60})",
            r"data provavel[^\n.;]{0,60}?prova[^\n.;]{0,80}",
        )
        for padrao in padroes:
            for m in re.finditer(padrao, normal):
                trecho = m.group(1) if m.groups() else m.group(0)
                if (achada := data_por_extenso(trecho)) is not None:
                    return achada
        return None

    @staticmethod
    def _taxas(texto: str) -> list[Decimal]:
        valores: set[Decimal] = set()
        for m in re.finditer(r"(?:valor d[ae] |taxa de )inscri", texto, re.IGNORECASE):
            janela = texto[m.start() : m.start() + 220]
            valores.update(v for v in valores_monetarios(janela) if Decimal(0) < v < _TAXA_MAXIMA_PLAUSIVEL)
        return sorted(valores)
