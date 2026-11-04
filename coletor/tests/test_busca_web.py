"""Busca assistida: só links https, marcação de oficial e de confirmado pelas fontes da busca."""

import json
from datetime import date

import httpx
import pytest

from coletor.ia.busca_web import (
    BuscaGemini,
    BuscaOpenRouter,
    buscar_bancas,
    criar_buscadores,
    dominios_das_fontes,
    eh_oficial,
    gravar,
    interpretar,
)
from coletor.ia.provedores import FalhaIA

REDIR = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"
METADADOS = {"groundingChunks": [
    {"web": {"uri": REDIR + "a", "title": "concursosfcc.com.br"}},
    {"web": {"uri": REDIR + "b", "title": "trt4.jus.br"}},
]}  # fmt: skip

RESPOSTA = """Aqui está:
```json
[{"orgao": "TRT-4", "cargos": "Analista", "inscricoes_ate": "2026-11-30", "isencao_ate": null,
  "link": "https://www.concursosfcc.com.br/concursos/trt4", "observacao": ""},
 {"orgao": "Inventado", "cargos": "", "inscricoes_ate": "30/11", "link": "https://blog-de-concursos.com/x"},
 {"orgao": "Sem link", "link": "javascript:alert(1)"}]
```"""


def test_interpreta_e_marca_oficial_e_confirmado():
    a, b = interpretar("FCC", RESPOSTA, METADADOS)
    assert (a.oficial, a.confirmado, a.inscricoes_ate) == (True, True, "2026-11-30")
    assert (b.oficial, b.confirmado, b.inscricoes_ate) == (False, False, None)


def test_oficial_inclui_orgaos_publicos():
    assert eh_oficial("https://www.trt4.jus.br/edital.pdf", "FCC")
    assert not eh_oficial("https://fcc.org.br.golpe.com/x", "FCC")
    assert dominios_das_fontes(METADADOS) == {"concursosfcc.com.br", "trt4.jus.br"}


def test_resposta_sem_array_e_erro():
    with pytest.raises(FalhaIA):
        interpretar("FCC", "não achei nada", {})


def _ok(texto=RESPOSTA):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": texto}]},
                                                     "groundingMetadata": METADADOS}]})  # fmt: skip


def test_rodizio_passa_ao_proximo_modelo_quando_um_esgota(tmp_path):
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
    sugestoes, falhas = buscar_bancas(buscadores, ["FCC", "VUNESP"], date(2026, 11, 4))
    assert pedidos == ["lite", "inexistente", "flash", "flash"]  # VUNESP já vai direto ao que sobrou
    assert len(sugestoes) == 2 and len(falhas) == 2 and "requests per day" in falhas[0]
    assert not esperas or all(e <= 13 for e in esperas)  # cota diária não espera 65 s
    csv_, md = gravar(sugestoes, tmp_path, date(2026, 11, 4), falhas)
    texto = md.read_text(encoding="utf-8")
    assert "TRT-4" in texto and "⚠️ não oficial" in texto and "Falhas da busca" in texto
    assert csv_.read_text(encoding="utf-8-sig").startswith("banca;orgao")


def test_limite_por_minuto_espera_e_tenta_de_novo():
    respostas = [httpx.Response(429, json={"error": {"message": "requests per minute"}}), _ok()]
    http = httpx.Client(transport=httpx.MockTransport(lambda r: respostas.pop(0)))
    esperas: list[float] = []
    assert len(BuscaGemini("k", "m", http, dormir=esperas.append).buscar("FCC", date(2026, 11, 4))) == 2
    assert 65.0 in esperas


def test_openrouter_usa_plugin_web_e_citacoes_como_fontes():
    pedidos = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": RESPOSTA, "annotations": [
            {"type": "url_citation", "url_citation": {"url": "https://www.concursosfcc.com.br/x"}}]}}]})  # fmt: skip

    busca = BuscaOpenRouter("k", "openrouter/free", httpx.Client(transport=httpx.MockTransport(responder)))
    primeira = busca.buscar("FCC", date(2026, 11, 4))[0]
    assert pedidos[0]["plugins"][0]["id"] == "web" and primeira.confirmado and primeira.oficial


def test_sem_credito_no_openrouter_e_todos_esgotados():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(402, json={"error": "sem crédito"})))
    sugestoes, falhas = buscar_bancas([BuscaOpenRouter("k", "m", http)], ["FCC", "IBFC"], date(2026, 11, 4))
    assert sugestoes == [] and falhas[-1].startswith("todos os provedores")


def test_criar_buscadores_respeita_as_chaves():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert criar_buscadores({}, http) == []
    nomes = [b.nome for b in criar_buscadores({"GEMINI_API_KEY": "g", "OPENROUTER_API_KEY": "o",
                                                "COLETOR_BUSCA_MODELOS": "a, b"}, http)]  # fmt: skip
    assert nomes == ["gemini:a", "gemini:b", "openrouter:openrouter/free"]


def test_email_monta_relatorio_com_anexo_e_nao_vaza_senha(tmp_path):
    from coletor.ia.email_relatorio import ConfigEmail, EmailNaoConfigurado, montar_mensagem

    with pytest.raises(EmailNaoConfigurado):
        ConfigEmail.do_ambiente({"SMTP_USUARIO": "a@b.c"})
    env = {"SMTP_USUARIO": "a@b.c", "SMTP_SENHA": "segredo-smtp", "BUSCA_EMAIL_DESTINO": "d@e.f"}
    config = ConfigEmail.do_ambiente(env)
    assert config.host == "smtp.gmail.com" and config.porta == 587 and "segredo-smtp" not in repr(config)
    csv_, md = gravar([], tmp_path, date(2026, 11, 4))
    mensagem = montar_mensagem(config, "Assunto", md, csv_)
    assert mensagem["To"] == "d@e.f" and [p.get_filename() for p in mensagem.iter_attachments()] == [csv_.name]
