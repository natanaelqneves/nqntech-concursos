"""Busca na web (pré-cadastro): validação dos campos, oficial/confirmado, rodízio de provedores e alvos."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from coletor.ia.busca_web import (
    AlvoBusca,
    BuscaGemini,
    BuscaOpenRouter,
    buscar_alvos,
    carregar_alvos,
    criar_buscadores,
    dominios_das_fontes,
    eh_oficial,
    interpretar,
)
from coletor.ia.provedores import FalhaIA

HOJE = date(2026, 11, 4)
FCC = AlvoBusca("fcc", "concursos da FCC", "FCC", ("concursosfcc.com.br", "fcc.org.br"))
NORDESTE = AlvoBusca("nordeste", "concursos do Nordeste")
REDIR = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"
METADADOS = {"groundingChunks": [
    {"web": {"uri": REDIR + "a", "title": "concursosfcc.com.br"}},
    {"web": {"uri": REDIR + "b", "title": "trt4.jus.br"}},
]}  # fmt: skip

RESPOSTA = """Aqui está:
```json
[{"orgao": "Tribunal Regional do Trabalho da 4ª Região", "banca": "FCC", "esfera": "FEDERAL", "uf": "RS",
  "situacao": "ABERTO", "ano": 2026, "inscricoes_inicio": "2026-11-01", "inscricoes_fim": "2026-11-30",
  "isencao_fim": "2026-11-10", "data_prova": "2027-02-15", "taxa_max": "R$ 120,5", "vagas": 30,
  "salario_max": 16035.69, "cargos": ["Analista Judiciário", "Técnico Judiciário", ""],
  "escolaridades": ["superior", "MEDIO", "doutorado"],
  "link_pagina": "https://www.concursosfcc.com.br/concursos/trt4", "link_edital": "https://blog.com/edital.pdf"},
 {"orgao": "Inventado", "situacao": "PREVISTO", "inscricoes_fim": "30/11", "data_prova": "2031-01-01",
  "uf": "XX", "taxa_max": 99999, "link_pagina": "https://blog-de-concursos.com/x"},
 {"orgao": "Sem link", "link_pagina": "javascript:alert(1)"},
 {"orgao": null, "link_pagina": "https://trt4.jus.br/x"}]
```"""


def test_interpreta_valida_campos_e_marca_oficial_e_confirmado():
    a, b = interpretar(FCC, RESPOSTA, METADADOS, HOJE)
    assert (a.oficial, a.confirmado, a.banca, a.esfera, a.uf, a.situacao) == (
        True,
        True,
        "FCC",
        "FEDERAL",
        "RS",
        "ABERTO",
    )
    assert (a.inscricoes_fim, a.data_prova, a.vagas, a.salario_max) == (
        date(2026, 11, 30),
        date(2027, 2, 15),
        30,
        Decimal("16035.69"),
    )
    assert a.taxa_max is None  # "R$ 120,5" não é número no formato pedido: melhor nulo que errado
    assert a.cargos == ("Analista Judiciário", "Técnico Judiciário")
    assert a.escolaridades == ("SUPERIOR", "MEDIO")
    assert a.link_edital == "https://blog.com/edital.pdf"
    assert (b.oficial, b.confirmado, b.situacao) == (False, False, "PREVISTO")
    assert (b.inscricoes_fim, b.data_prova, b.uf, b.taxa_max) == (None, None, None, None)
    assert a.para_json()["inscricoes_fim"] == "2026-11-30"


def test_banca_da_sugestao_so_vale_se_conhecida():
    resposta = json.dumps([
        {"orgao": "Prefeitura de Patos", "banca": "IBFC", "link_pagina": "https://ibfc.org.br/x"},
        {"orgao": "Prefeitura de Sousa", "banca": "Desconhecida", "link_pagina": "https://sousa.pb.gov.br/c"},
    ])  # fmt: skip
    a, b = interpretar(NORDESTE, resposta, {}, HOJE, {"IBFC": ("ibfc.org.br",)})
    assert (a.banca, a.oficial) == ("IBFC", True)
    assert (b.banca, b.oficial) == (None, True)  # .gov.br é oficial para qualquer alvo


def test_oficial_inclui_orgaos_publicos():
    assert eh_oficial("https://www.trt4.jus.br/edital.pdf")
    assert not eh_oficial("https://fcc.org.br.golpe.com/x", ("fcc.org.br",))
    assert dominios_das_fontes(METADADOS) == {"concursosfcc.com.br", "trt4.jus.br"}


def test_resposta_sem_array_e_erro():
    with pytest.raises(FalhaIA):
        interpretar(FCC, "não achei nada", {}, HOJE)


def test_alvos_do_arquivo_do_repositorio():
    alvos = carregar_alvos(Path(__file__).parents[2] / "config" / "busca.yml")
    codigos = {a.codigo for a in alvos}
    assert {"fcc", "vunesp", "judiciario", "fisco", "militares", "previstos-seguranca"} <= codigos
    assert "fgv" not in codigos  # banca com coletor próprio não gasta cota da busca
    fcc = next(a for a in alvos if a.codigo == "fcc")
    assert fcc.banca == "FCC" and "concursosfcc.com.br" in fcc.dominios


def _ok(texto=RESPOSTA):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": texto}]},
                                                     "groundingMetadata": METADADOS}]})  # fmt: skip


def test_rodizio_passa_ao_proximo_modelo_quando_um_esgota():
    pedidos = []

    def responder(request: httpx.Request) -> httpx.Response:
        modelo = request.url.path.split("/models/")[1].split(":")[0]
        pedidos.append(modelo)
        if modelo == "lite":
            return httpx.Response(429, json={"error": {"message": "Quota exceeded: requests per day"}})
        if modelo == "inexistente":
            return httpx.Response(404, json={"error": {"message": "model not found"}})
        return _ok()

    http = httpx.Client(transport=httpx.MockTransport(responder))
    esperas: list[float] = []
    buscadores = [BuscaGemini("k", m, http, dormir=esperas.append) for m in ("lite", "inexistente", "flash")]
    resultados = buscar_alvos(buscadores, [FCC, NORDESTE], HOJE)
    assert pedidos == ["lite", "inexistente", "flash", "flash"]  # o 2º alvo já vai direto ao que sobrou
    assert [len(r.sugestoes) for r in resultados] == [2, 2] and all(r.erro is None for r in resultados)
    assert not esperas or all(e <= 13 for e in esperas)  # cota diária não espera 65 s


def test_limite_por_minuto_espera_e_tenta_de_novo():
    respostas = [httpx.Response(429, json={"error": {"message": "requests per minute"}}), _ok()]
    http = httpx.Client(transport=httpx.MockTransport(lambda r: respostas.pop(0)))
    esperas: list[float] = []
    resposta = BuscaGemini("k", "m", http, dormir=esperas.append).buscar("pedido")
    assert len(interpretar(FCC, resposta.texto, resposta.metadados, HOJE)) == 2
    assert 65.0 in esperas


def test_openrouter_usa_plugin_web_e_citacoes_como_fontes():
    pedidos = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": RESPOSTA, "annotations": [
            {"type": "url_citation", "url_citation": {"url": "https://www.concursosfcc.com.br/x"}}]}}]})  # fmt: skip

    busca = BuscaOpenRouter("k", "openrouter/free", httpx.Client(transport=httpx.MockTransport(responder)))
    primeira = buscar_alvos([busca], [FCC], HOJE)[0].sugestoes[0]
    assert pedidos[0]["plugins"][0]["id"] == "web" and primeira.confirmado and primeira.oficial


def test_sem_cota_o_alvo_fica_para_a_proxima_e_erro_comum_e_registrado():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(402, json={"error": "sem crédito"})))
    assert buscar_alvos([BuscaOpenRouter("k", "m", http)], [FCC, NORDESTE], HOJE) == []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"error": "pane"})))
    (resultado,) = buscar_alvos([BuscaOpenRouter("k", "m", http)], [FCC], HOJE)
    assert resultado.sugestoes == () and "pane" in (resultado.erro or "")


def test_criar_buscadores_respeita_as_chaves():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert criar_buscadores({}, http) == []
    nomes = [b.nome for b in criar_buscadores({"GEMINI_API_KEY": "g", "OPENROUTER_API_KEY": "o",
                                                "COLETOR_BUSCA_MODELOS": "a, b"}, http)]  # fmt: skip
    assert nomes == ["gemini:a", "gemini:b", "openrouter:openrouter/free"]


def test_email_monta_mensagem_e_nao_vaza_senha():
    from coletor.ia.email_relatorio import ConfigEmail, EmailNaoConfigurado, montar_mensagem

    with pytest.raises(EmailNaoConfigurado):
        ConfigEmail.do_ambiente({"SMTP_USUARIO": "a@b.c"})
    env = {"SMTP_USUARIO": "a@b.c", "SMTP_SENHA": "segredo-smtp", "BUSCA_EMAIL_DESTINO": "d@e.f"}
    config = ConfigEmail.do_ambiente(env)
    assert config.host == "smtp.gmail.com" and config.porta == 587 and "segredo-smtp" not in repr(config)
    mensagem = montar_mensagem(config, "Assunto", "corpo")
    assert mensagem["To"] == "d@e.f" and mensagem.get_content().strip() == "corpo"
