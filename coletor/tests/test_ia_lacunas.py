"""Segunda leitura dirigida aos dados mínimos (fim das inscrições, prova, salário de até, prazo de isenção)."""

from datetime import date
from decimal import Decimal

from coletor.extratores.base import CargoExtraido, EditalExtraido, IsencaoPrevista
from coletor.ia.lacunas import ESQUEMA, CompletadorIA, aplicar, faltando, trechos_dirigidos
from coletor.ia.provedores import FalhaIA

HOJE = date(2026, 11, 4)
INCOMPLETO = EditalExtraido(
    orgao="Prefeitura Municipal de Sapé",
    cargos=(CargoExtraido("Professor", vagas=10), CargoExtraido("Agente Administrativo", vagas=5)),
    isencoes=(IsencaoPrevista("CADUNICO"),),
    avisos=("período de inscrição não encontrado: confira o edital", "data da prova não encontrada: confira o edital"),
)
TEXTO = (
    "EDITAL 01/2026\n" + "regras gerais do concurso. " * 400
    + "\n10. DO CRONOGRAMA\nPeríodo de inscrições: 10/11/2026 a 10/12/2026. A prova objetiva será realizada em "
    "17/01/2027.\n" + "texto intermediário. " * 300
    + "\nANEXO I – REMUNERAÇÃO: Professor R$ 3.500,00; Agente Administrativo R$ 1.900,00.\n"
    + "O pedido de isenção da taxa poderá ser feito de 10/11/2026 a 14/11/2026.\n"
)  # fmt: skip
RESPOSTA = {
    "inscricao_inicio": "2026-11-10", "inscricao_fim": "2026-12-10", "data_prova": "2027-01-17",
    "salarios": [{"cargo": "Professor", "salario": 3500}, {"cargo": "Agente Administrativo", "salario": 1900}],
    "isencao_inicio": "2026-11-10", "isencao_fim": "2026-11-14",
}  # fmt: skip


def test_identifica_o_que_falta():
    assert faltando(INCOMPLETO) == ["inscricao", "prova", "salario", "isencao"]
    assert faltando(EditalExtraido()) == ["inscricao", "prova"]  # sem cargos e sem isenção: não pede salário/isenção


def test_trechos_dirigidos_pegam_cronograma_remuneracao_e_isencao_longe_do_inicio():
    trechos = trechos_dirigidos(TEXTO, faltando(INCOMPLETO))
    assert "17/01/2027" in trechos and "R$ 3.500,00" in trechos and "14/11/2026" in trechos
    assert len(trechos) < len(TEXTO) / 3


def test_aplicar_preenche_so_o_vazio_e_limpa_avisos_resolvidos():
    completo = aplicar(INCOMPLETO, RESPOSTA, HOJE)
    assert (completo.inscricao_fim, completo.data_prova, completo.isencao_fim) == (
        date(2026, 12, 10), date(2027, 1, 17), date(2026, 11, 14))  # fmt: skip
    assert [c.salario for c in completo.cargos] == [Decimal("3500.00"), Decimal("1900.00")]
    assert faltando(completo) == [] and completo.avisos == ()
    ja_tinha = aplicar(EditalExtraido(data_prova=date(2027, 2, 1)), RESPOSTA, HOJE)
    assert ja_tinha.data_prova == date(2027, 2, 1)  # nunca troca o que a primeira leitura achou


def test_valores_ruins_sao_descartados():
    ruim = {**RESPOSTA, "data_prova": "2026-11-20", "salarios": [{"cargo": "Professor", "salario": 9_999_999}]}
    completo = aplicar(INCOMPLETO, ruim, HOJE)
    assert completo.data_prova is None  # antes do fim das inscrições
    assert all(c.salario is None for c in completo.cargos)
    invertido = aplicar(INCOMPLETO, {**RESPOSTA, "inscricao_inicio": "2026-12-20"}, HOJE)
    assert invertido.inscricao_inicio is None and invertido.inscricao_fim is None  # fim antes do início


def test_salario_unico_vale_para_todos():
    completo = aplicar(INCOMPLETO, {**RESPOSTA, "salarios": [{"cargo": "todos os cargos", "salario": 2100}]}, HOJE)
    assert {c.salario for c in completo.cargos} == {Decimal("2100.00")}


class _Rodizio:
    disponivel = True

    def __init__(self, resposta=None, erro=False):
        self.chamadas, self._resposta, self._erro = [], resposta, erro

    def gerar(self, instrucoes, conteudo, esquema):
        self.chamadas.append((conteudo, esquema))
        if self._erro:
            raise FalhaIA("fora do ar")
        return self._resposta, type("P", (), {"nome": "teste", "modelo": "m"})()


def test_uma_chamada_por_edital_com_cache_e_falha_sem_cache():
    cache: dict = {}
    rodizio = _Rodizio(RESPOSTA)
    completador = CompletadorIA(rodizio, lambda s, v: cache.get((s, v)),
                                lambda s, v, o, r, m: cache.__setitem__((s, v), {"resposta": r}))  # fmt: skip
    assert faltando(completador.completar(INCOMPLETO, TEXTO, "abc", HOJE)) == []
    assert faltando(completador.completar(INCOMPLETO, TEXTO, "abc", HOJE)) == []
    assert len(rodizio.chamadas) == 1 and rodizio.chamadas[0][1] is ESQUEMA
    falho = CompletadorIA(_Rodizio(erro=True), lambda s, v: None, lambda *a: cache.__setitem__("nao", 1))
    assert falho.completar(INCOMPLETO, TEXTO, "x", HOJE) == INCOMPLETO and "nao" not in cache
