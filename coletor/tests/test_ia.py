"""Camada 2 (IA): tudo simulado, sem internet e sem chave real."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from coletor.config import carregar_config
from coletor.extratores.base import CargoExtraido, EditalExtraido
from coletor.ia.esquema import ESQUEMA, VERSAO, para_edital
from coletor.ia.extrator import ExtratorIA, combinar, precisa_de_ia
from coletor.ia.provedores import (
    GEMINI_URL,
    GROQ_URL,
    OPENROUTER_URL,
    ConfigIA,
    FalhaIA,
    Gemini,
    Groq,
    LimiteAtingido,
    OpenRouter,
    Rodizio,
    criar_provedores,
)
from coletor.ia.recorte import recortar
from coletor.ia.triagem import triar

HOJE = date(2026, 10, 25)

RESPOSTA_TJPB = {
    "orgao": "Tribunal de Justiça do Estado da Paraíba",
    "esfera": "ESTADUAL",
    "uf": "PB",
    "municipio": None,
    "numero_edital": "01/2026",
    "ano": 2026,
    "cargos": [
        {"nome": "Analista", "especialidade": "Judiciária", "escolaridade": "SUPERIOR", "vagas": 25,
         "cadastro_reserva": False, "salario": 7526.14, "uf_lotacao": None},
        {"nome": "Analista", "especialidade": "TI – Banco de Dados", "escolaridade": "SUPERIOR", "vagas": 1,
         "cadastro_reserva": False, "salario": 7526.14, "uf_lotacao": None},
    ],
    "inscricao_inicio": "2026-10-20",
    "inscricao_fim": "2026-11-18",
    "data_prova": "2027-01-24",
    "taxa_min": 120,
    "taxa_max": 120,
    "isencoes": ["CADUNICO", "DOADOR_SANGUE", "JURADO"],
    "isencao_inicio": "2026-10-20",
    "isencao_fim": "2026-10-27",
}  # fmt: skip


# --- triagem e recorte (editais reais) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "edital",
    ["edital_tjpb26_1", "edital_dataprev26_0", "edital_pcpr26_0", "edital_pms2026_0", "edital_seducpa26_0",
     "edital_sesto26_0"],
)  # fmt: skip
def test_triagem_aceita_editais_de_abertura(fixture_texto, edital):
    assert triar(fixture_texto(f"fgv/{edital}.txt")).valido


@pytest.mark.parametrize(
    "texto",
    [
        "GABARITO PRELIMINAR DA PROVA OBJETIVA\n" + "texto " * 200,
        "COMUNICADO\nConvocação para a prova prática\n" + "texto " * 200,
        "curto",
    ],
)
def test_triagem_recusa_o_que_nao_e_abertura(texto):
    assert not triar(texto).valido


def test_triagem_recusa_retificacao_parcial(fixture_texto):
    triagem = triar(fixture_texto("fgv/edital_tjpb26_0.txt"))
    assert not triagem.valido and "retificação" in triagem.motivo


def test_recorte_leva_o_que_importa_e_deixa_o_conteudo_programatico(fixture_texto):
    texto = fixture_texto("fgv/edital_tjpb26_1.txt")
    trecho = recortar(texto)
    assert len(trecho) <= 24_000 < len(texto)
    assert "5. DA ISENÇÃO" in trecho
    assert "3. DOS CARGOS" in trecho
    assert "4. DAS INSCRIÇÕES" in trecho
    assert "MÓDULO II - CONHECIMENTOS ESPECÍFICOS" not in trecho  # anexo de conteúdo programático


def test_recorte_com_sumario_citando_o_anexo_no_comeco(fixture_texto):
    trecho = recortar(fixture_texto("fgv/edital_pcpr26_0.txt"))
    assert "DA ISENÇÃO" in trecho.upper() and len(trecho) > 10_000


# --- validação da resposta -----------------------------------------------------------------------------------


def test_resposta_valida_vira_edital():
    edital, uf = para_edital(RESPOSTA_TJPB, HOJE)
    assert uf == "PB"
    assert (edital.inscricao_inicio, edital.inscricao_fim) == (date(2026, 10, 20), date(2026, 11, 18))
    assert edital.taxa_min == edital.taxa_max == Decimal("120.00")
    assert edital.cargos[0].salario == Decimal("7526.14") and edital.cargos[0].vagas == 25
    assert [i.codigo for i in edital.isencoes] == ["CADUNICO", "DOADOR_SANGUE", "JURADO"]
    assert edital.avisos == ()


def test_valores_implausiveis_viram_nulos_com_aviso():
    ruim = {
        **RESPOSTA_TJPB,
        "inscricao_inicio": "2026-12-01",
        "inscricao_fim": "2026-11-01",  # fim antes do início
        "data_prova": "1999-01-01",
        "taxa_max": 99_999,
        "uf": "XX",
        "isencoes": ["CADUNICO", "INVENTADA", "CADUNICO"],
        "cargos": [
            {"nome": "x", "especialidade": None, "escolaridade": "DOUTORADO", "vagas": -3, "cadastro_reserva": False,
             "salario": 10},
            {"nome": "Técnico", "especialidade": None, "escolaridade": "MEDIO", "vagas": True,
             "cadastro_reserva": True, "salario": "abc"},
        ],
    }  # fmt: skip
    edital, uf = para_edital(ruim, HOJE)
    assert uf is None
    assert edital.inscricao_inicio is None and edital.inscricao_fim is None and edital.data_prova is None
    assert edital.taxa_max == Decimal("120.00")
    assert [i.codigo for i in edital.isencoes] == ["CADUNICO"]
    assert len(edital.cargos) == 1
    assert (edital.cargos[0].nome, edital.cargos[0].vagas, edital.cargos[0].salario) == ("Técnico", None, None)
    assert any("incoerente" in a for a in edital.avisos)
    assert any("taxa fora da faixa" in a for a in edital.avisos)


def test_esquema_e_estrito():
    """Modo estrito dos provedores: todo campo obrigatório e objetos fechados."""

    def conferir(no):
        if no.get("type") == "object":
            assert no["additionalProperties"] is False
            assert set(no["required"]) == set(no["properties"])
            for filho in no["properties"].values():
                conferir(filho)
        if no.get("type") == "array":
            conferir(no["items"])
        assert None not in no.get("enum", [])

    conferir(ESQUEMA)


# --- provedores (HTTP simulado) ------------------------------------------------------------------------------


def _cliente(responder) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(responder))


def test_gemini_envia_esquema_e_le_json():
    pedidos = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        texto = json.dumps(RESPOSTA_TJPB)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": texto}]}}]})

    dados = Gemini("chave-teste", "modelo-x", _cliente(responder)).gerar_json("instr", "trecho", ESQUEMA)
    assert dados["orgao"].startswith("Tribunal")
    pedido = pedidos[0]
    assert str(pedido.url) == GEMINI_URL.format(modelo="modelo-x")
    assert pedido.headers["x-goog-api-key"] == "chave-teste"
    corpo = json.loads(pedido.content)
    assert corpo["generationConfig"]["responseJsonSchema"] == ESQUEMA
    assert corpo["generationConfig"]["temperature"] == 0


def test_groq_usa_json_schema_estrito():
    pedidos = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(RESPOSTA_TJPB)}}]})

    Groq("chave-groq", "openai/gpt-oss-120b", _cliente(responder)).gerar_json("instr", "trecho", ESQUEMA)
    corpo = json.loads(pedidos[0].content)
    assert str(pedidos[0].url) == GROQ_URL
    assert pedidos[0].headers["authorization"] == "Bearer chave-groq"
    assert corpo["response_format"]["json_schema"]["strict"] is True


def test_openrouter_so_usa_modelos_com_json_schema():
    pedidos = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(RESPOSTA_TJPB)}}]})

    OpenRouter("chave-or", "openrouter/free", _cliente(responder)).gerar_json("instr", "trecho", ESQUEMA)
    corpo = json.loads(pedidos[0].content)
    assert str(pedidos[0].url) == OPENROUTER_URL
    assert pedidos[0].headers["authorization"] == "Bearer chave-or"
    assert corpo["provider"]["require_parameters"] is True
    assert corpo["response_format"]["json_schema"]["strict"] is True


def test_ordem_dos_provedores():
    config = ConfigIA(gemini_chave="a", groq_chave="b", openrouter_chave="c")
    assert [p.nome for p in criar_provedores(config, _cliente(lambda r: httpx.Response(500)))] == [
        "gemini",
        "groq",
        "openrouter",
    ]
    assert ConfigIA(openrouter_chave="segredo-or").ativa and "segredo-or" not in repr(
        ConfigIA(openrouter_chave="segredo-or")
    )


def test_429_e_resposta_invalida_viram_erros_tipados():
    limite = Gemini("k", "m", _cliente(lambda r: httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})))
    with pytest.raises(LimiteAtingido):
        limite.gerar_json("i", "t", ESQUEMA)
    sem_json = {"choices": [{"message": {"content": "x"}}]}
    invalida = Groq("k", "m", _cliente(lambda r: httpx.Response(200, json=sem_json)))
    with pytest.raises(FalhaIA):
        invalida.gerar_json("i", "t", ESQUEMA)


class ProvedorFalso:
    def __init__(self, nome: str, respostas: list) -> None:
        self.nome, self.modelo, self.respostas, self.chamadas = nome, "falso", list(respostas), 0

    def gerar_json(self, instrucoes, conteudo, esquema):
        self.chamadas += 1
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def _rodizio(*provedores, maximo=10):
    return Rodizio(list(provedores), maximo, intervalo_s=0, dormir=lambda s: None)


def test_fallback_para_o_groq_quando_o_gemini_atinge_o_limite():
    gemini = ProvedorFalso("gemini", [LimiteAtingido("429"), RESPOSTA_TJPB])
    groq = ProvedorFalso("groq", [RESPOSTA_TJPB, RESPOSTA_TJPB])
    rodizio = _rodizio(gemini, groq)
    _, usado = rodizio.gerar("i", "t", ESQUEMA)
    assert usado is groq
    _, usado = rodizio.gerar("i", "t", ESQUEMA)
    assert usado is groq and gemini.chamadas == 1  # gemini fica fora até o fim da execução


def test_teto_de_chamadas_por_execucao():
    gemini = ProvedorFalso("gemini", [RESPOSTA_TJPB] * 5)
    rodizio = _rodizio(gemini, maximo=2)
    rodizio.gerar("i", "t", ESQUEMA)
    rodizio.gerar("i", "t", ESQUEMA)
    assert not rodizio.disponivel
    with pytest.raises(FalhaIA):
        rodizio.gerar("i", "t", ESQUEMA)


def test_intervalo_minimo_entre_chamadas_ao_mesmo_provedor():
    esperas = []
    relogio = iter([0.0, 0.0, 1.0, 5.0])
    rodizio = Rodizio([ProvedorFalso("gemini", [RESPOSTA_TJPB] * 2)], 10, intervalo_s=4, dormir=esperas.append,
                      relogio=lambda: next(relogio))  # fmt: skip
    rodizio.gerar("i", "t", ESQUEMA)
    rodizio.gerar("i", "t", ESQUEMA)
    assert esperas == [3.0]


# --- extrator completo: cache, triagem e combinação ---------------------------------------------------------


class CacheMemoria:
    def __init__(self) -> None:
        self.dados: dict[tuple[str, str], dict] = {}

    def ler(self, sha, versao):
        return self.dados.get((sha, versao))

    def gravar(self, sha, versao, origem, resposta, motivo):
        self.dados[(sha, versao)] = {"resposta": resposta, "motivo": motivo, "origem": origem}


def test_edital_vai_a_ia_uma_vez_so(fixture_texto):
    texto = fixture_texto("fgv/edital_tjpb26_1.txt")
    gemini = ProvedorFalso("gemini", [RESPOSTA_TJPB])
    cache = CacheMemoria()
    extrator = ExtratorIA(_rodizio(gemini), cache.ler, cache.gravar, 24_000)

    primeiro = extrator.extrair(texto, "a" * 64, HOJE)
    segundo = extrator.extrair(texto, "a" * 64, HOJE)

    assert primeiro.origem == "gemini/falso" and segundo.origem == "cache"
    assert gemini.chamadas == 1
    assert cache.dados[("a" * 64, VERSAO)]["origem"] == "gemini/falso"
    # Calendário e disciplinas vêm das regras comuns, sem custo de IA.
    assert {e.evento for e in segundo.edital.eventos} >= {"Inscrições", "Pedido de isenção da taxa"}
    assert segundo.edital.cargos[0].disciplinas


def test_documento_que_nao_e_edital_nao_gasta_chamada_e_fica_no_cache(fixture_texto):
    gemini = ProvedorFalso("gemini", [])
    cache = CacheMemoria()
    extrator = ExtratorIA(_rodizio(gemini), cache.ler, cache.gravar, 24_000)
    resultado = extrator.extrair(fixture_texto("fgv/edital_tjpb26_0.txt"), "b" * 64, HOJE)
    assert resultado.edital is None and resultado.origem == "triagem"
    assert gemini.chamadas == 0
    assert extrator.extrair("qualquer", "b" * 64, HOJE).origem == "cache"


def test_falha_do_provedor_nao_vai_ao_cache(fixture_texto):
    cache = CacheMemoria()
    extrator = ExtratorIA(_rodizio(ProvedorFalso("gemini", [FalhaIA("500")])), cache.ler, cache.gravar, 24_000)
    assert extrator.extrair(fixture_texto("fgv/edital_tjpb26_1.txt"), "c" * 64, HOJE).origem == "falha"
    assert cache.dados == {}


def test_precisa_de_ia_so_com_lacuna():
    completo = EditalExtraido(cargos=(CargoExtraido("Analista", vagas=1),), inscricao_fim=date(2026, 11, 1))
    assert not precisa_de_ia(completo)
    assert precisa_de_ia(None)
    assert precisa_de_ia(EditalExtraido(cargos=(), inscricao_fim=date(2026, 11, 1)))
    lacuna = EditalExtraido(cargos=completo.cargos, inscricao_fim=date(2026, 11, 1),
                            avisos=("taxa de inscrição não encontrada",))  # fmt: skip
    assert precisa_de_ia(lacuna)


def test_regras_vencem_e_ia_preenche_lacunas():
    regras = EditalExtraido(
        orgao="TJPB (regras)",
        cargos=(CargoExtraido("Analista", especialidade="Judiciária"),),  # sem vagas
        inscricao_inicio=date(2026, 10, 20),
        inscricao_fim=date(2026, 11, 18),
        avisos=(
            "vagas e salários de cada cargo não identificados: confira o edital",
            "taxa de inscrição não encontrada",
        ),
    )
    ia, _ = para_edital(RESPOSTA_TJPB, HOJE)
    combinado = combinar(regras, ia)
    assert combinado.orgao == "TJPB (regras)"
    assert combinado.cargos == ia.cargos  # IA trouxe as vagas
    assert combinado.taxa_max == Decimal("120.00")
    assert combinado.avisos == ()


def test_config_ia_desligada_sem_chave_e_sem_vazar_chave():
    base = {"DB_HOST": "h", "DB_NAME": "d", "COLETOR_DB_USER": "u", "COLETOR_DB_PASSWORD": "p",
            "COLETOR_CONTATO_EMAIL": "a@b.c"}  # fmt: skip
    assert not carregar_config(base).ia.ativa
    config = carregar_config({**base, "GEMINI_API_KEY": "segredo-gemini", "COLETOR_IA_MAX_CHAMADAS": "5"})
    assert config.ia.ativa and config.ia.max_chamadas == 5
    assert "segredo-gemini" not in repr(config)
    assert not ConfigIA(gemini_chave="x", max_chamadas=0).ativa


def test_ia_traz_o_local_do_orgao_para_a_persistencia():
    from coletor.pipeline.estruturacao import orgao_do_edital

    resposta = {**RESPOSTA_TJPB, "orgao": "Prefeitura Municipal de Sapé", "esfera": "MUNICIPAL", "uf": "PB",
                "municipio": "Sapé"}  # fmt: skip
    edital, _ = para_edital(resposta, HOJE)
    assert (edital.esfera, edital.uf, edital.municipio) == ("MUNICIPAL", "PB", "Sapé")
    orgao = orgao_do_edital(edital)
    assert (orgao.esfera, orgao.uf, orgao.municipio) == ("MUNICIPAL", "PB", "Sapé")
    federal, _ = para_edital({**RESPOSTA_TJPB, "orgao": "Instituto Nacional do Seguro Social", "esfera": "FEDERAL",
                              "uf": "DF", "municipio": "Brasília"}, HOJE)  # fmt: skip
    assert federal.municipio is None and orgao_do_edital(federal).uf is None  # sede em Brasília não vira DF
    estranho, _ = para_edital({**RESPOSTA_TJPB, "esfera": "PLANETARIA", "uf": "XX"}, HOJE)
    assert estranho.esfera is None and estranho.uf is None


def test_cargo_com_uf_de_lotacao():
    cargos = [{**RESPOSTA_TJPB["cargos"][0], "uf_lotacao": "PB"}, {**RESPOSTA_TJPB["cargos"][1], "uf_lotacao": "ZZ"}]
    edital, _ = para_edital({**RESPOSTA_TJPB, "cargos": cargos}, HOJE)
    assert [c.uf_lotacao for c in edital.cargos] == ["PB", None]
