"""Busca assistida: só links https, marcação de oficial e de confirmado pelas fontes da busca."""

import json
from datetime import date

import httpx
import pytest

from coletor.ia.busca_web import BuscaGemini, buscar_bancas, dominios_das_fontes, eh_oficial, gravar, interpretar
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


def test_busca_usa_google_search_e_para_no_limite(tmp_path):
    pedidos = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(request.content))
        if len(pedidos) == 2:
            return httpx.Response(429)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": RESPOSTA}]},
                                                         "groundingMetadata": METADADOS}]})  # fmt: skip

    busca = BuscaGemini("k", "m", httpx.Client(transport=httpx.MockTransport(responder)))
    sugestoes, falhas = buscar_bancas(busca, ["FCC", "VUNESP", "IBFC"], date(2026, 11, 4))
    assert pedidos[0]["tools"] == [{"google_search": {}}]
    assert len(pedidos) == 2 and len(sugestoes) == 2 and "429" in falhas[0]
    csv_, md = gravar(sugestoes, tmp_path, date(2026, 11, 4))
    assert "TRT-4" in md.read_text(encoding="utf-8") and "⚠️ não oficial" in md.read_text(encoding="utf-8")
    assert csv_.read_text(encoding="utf-8-sig").startswith("banca;orgao")
