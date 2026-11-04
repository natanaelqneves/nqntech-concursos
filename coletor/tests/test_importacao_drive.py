"""Importação pelo Drive: lê a subpasta da banca, aplica as mesmas regras e move cada PDF conforme o resultado."""

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from coletor.db import Repositorio
from coletor.importacao_drive import API, Drive, configuracao, importar_do_drive

PDFS = Path(__file__).parent / "fixtures" / "pdf"
LINK = "https://exemplo.gov.br/teste-importacao-drive"


class DriveSimulado:
    """Pasta ENTRADA com a subpasta FCC: um edital bom, um protegido e um com descrição inválida."""

    def __init__(self) -> None:
        self.pastas = {"ENTRADA": [{"id": "fcc", "name": "FCC"}], "fcc": []}
        self.pdfs = {"fcc": [
            {"id": "bom", "name": "Edital_TRT.pdf", "description": LINK},
            {"id": "ruim", "name": "protegido.pdf", "description": None},
            {"id": "semlink", "name": "x.pdf", "description": "javascript:alert(1)"},
        ]}  # fmt: skip
        self.conteudo = {"bom": "edital_mini_tjpb.pdf", "ruim": "protegido.pdf", "semlink": "edital_mini_tjpb.pdf"}
        self.movidos: dict[str, str] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        caminho = request.url.path
        if request.method == "GET" and q.get("alt") == "media":
            return httpx.Response(200, content=(PDFS / self.conteudo[caminho.rsplit("/", 1)[1]]).read_bytes())
        if request.method == "GET":
            pai = q["q"].split("'")[1]
            if "folder" in q["q"]:
                return httpx.Response(200, json={"files": self.pastas.get(pai, [])})
            return httpx.Response(
                200, json={"files": [p for p in self.pdfs.get(pai, []) if p["id"] not in self.movidos]}
            )
        if request.method == "POST":
            nome = json.loads(request.content)["name"]
            self.pastas.setdefault("fcc", []).append({"id": nome, "name": nome})
            return httpx.Response(200, json={"id": nome})
        if request.method == "PATCH":
            self.movidos[caminho.rsplit("/", 1)[1]] = q["addParents"]
            return httpx.Response(200, json={})
        return httpx.Response(400)


def test_configuracao_exige_as_duas_variaveis():
    assert configuracao({"GOOGLE_SA_JSON": "{}"}) is None
    assert configuracao({"GOOGLE_SA_JSON": "{}", "DRIVE_PASTA_ENTRADA": "abc"}) == ("{}", "abc")


def test_listagem_pede_so_pdfs_da_pasta():
    pedidos = []

    def responder(request):
        pedidos.append(parse_qs(request.url.query.decode()))
        return httpx.Response(200, json={"files": [{"id": "1", "name": "a.pdf"}]})

    assert Drive(httpx.Client(transport=httpx.MockTransport(responder))).listar("P", so_pastas=False)[0]["id"] == "1"
    assert pedidos[0]["q"][0] == "'P' in parents and mimeType = 'application/pdf' and trashed = false"
    assert str(httpx.URL(API)).startswith("https://www.googleapis.com/drive/v3/")


@pytest.mark.db
def test_importa_e_move_cada_pdf(parametros_coletor, conn_admin):
    conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url = %s", (LINK,))
    conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial = %s", (LINK,))
    simulado = DriveSimulado()
    conn = psycopg.connect(**parametros_coletor, row_factory=dict_row)
    conn.execute("SET search_path = concursos")
    try:
        resumos = importar_do_drive(Repositorio(conn), Drive(httpx.Client(transport=httpx.MockTransport(simulado))),
                                    "ENTRADA", 5 * 1024 * 1024)  # fmt: skip
        assert [r.status for r in resumos] == ["PARCIAL"]
        assert simulado.movidos == {"bom": "processados", "ruim": "recusados"}  # "semlink" fica para corrigir
        status = conn_admin.execute(
            """SELECT d.status_extracao FROM concursos.documento d JOIN concursos.concurso c ON c.id = d.concurso_id
               WHERE c.link_oficial = %s""",
            (LINK,),
        ).fetchall()
        assert status == [("OK",)]
    finally:
        conn.close()
        conn_admin.execute("DELETE FROM concursos.sinal_descoberta WHERE url = %s", (LINK,))
        conn_admin.execute("DELETE FROM concursos.concurso WHERE link_oficial = %s", (LINK,))
