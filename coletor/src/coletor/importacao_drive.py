"""Importação de PDFs a partir de uma pasta do Google Drive (roda no GitHub Actions, antes da coleta diária).

Estrutura esperada (a pasta é compartilhada como Editor com a conta de serviço):

    <pasta de entrada>/
        FCC/            ← uma subpasta por banca, com a sigla como nome (ou OUTRA)
            edital-trt4.pdf   (link oficial na "descrição" do arquivo no Drive; opcional)
            processados/      ← criada pelo coletor: PDFs importados vão para cá
            recusados/        ← PDFs que falharam nas regras (protegido, corrompido, grande demais...)

O PDF só passa pela pasta temporária do runner enquanto o texto é extraído (seção 5.3): no banco fica o texto.
Mesmas regras e etapas de `importacao_manual`. Escopo da credencial: só o Drive (`drive`), e a conta de serviço
só enxerga o que foi compartilhado com ela.
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from coletor.db import Repositorio
from coletor.importacao_manual import ImportacaoInvalida, importar_arquivos, validar_link
from coletor.pipeline.comum import ResumoEtapa

log = logging.getLogger(__name__)

API = "https://www.googleapis.com/drive/v3/files"
ESCOPO = "https://www.googleapis.com/auth/drive"
PASTA = "application/vnd.google-apps.folder"
PROCESSADOS, RECUSADOS = "processados", "recusados"


class ErroDrive(Exception):
    pass


def token_da_conta_de_servico(json_credencial: str) -> str:
    """Token OAuth de curta duração a partir do JSON da conta de serviço (secret GOOGLE_SA_JSON)."""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    try:
        info = json.loads(json_credencial)
    except json.JSONDecodeError as erro:
        raise ErroDrive("GOOGLE_SA_JSON não é um JSON válido") from erro
    credencial = service_account.Credentials.from_service_account_info(info, scopes=[ESCOPO])
    credencial.refresh(Request())
    return str(credencial.token)


@dataclass(frozen=True)
class ArquivoDrive:
    id: str
    nome: str
    descricao: str | None


class Drive:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def _get(self, url: str, **params: Any) -> httpx.Response:
        resposta = self._http.get(url, params=params)
        if resposta.status_code >= 400:
            raise ErroDrive(f"Drive: HTTP {resposta.status_code}: {resposta.text[:300]}")
        return resposta

    def listar(self, pasta_id: str, so_pastas: bool) -> list[dict[str, Any]]:
        tipo = f"mimeType = '{PASTA}'" if so_pastas else "mimeType = 'application/pdf'"
        itens: list[dict[str, Any]] = []
        pagina: str | None = None
        while True:
            dados = self._get(API, q=f"'{pasta_id}' in parents and {tipo} and trashed = false",
                              fields="nextPageToken, files(id, name, description)", pageSize=200,
                              supportsAllDrives="true", includeItemsFromAllDrives="true",
                              **({"pageToken": pagina} if pagina else {})).json()  # fmt: skip
            itens += dados.get("files", [])
            pagina = dados.get("nextPageToken")
            if not pagina:
                return itens

    def subpasta(self, pai_id: str, nome: str) -> str:
        for item in self.listar(pai_id, so_pastas=True):
            if item["name"] == nome:
                return str(item["id"])
        resposta = self._http.post(API, params={"supportsAllDrives": "true"},
                                   json={"name": nome, "mimeType": PASTA, "parents": [pai_id]})  # fmt: skip
        if resposta.status_code >= 400:
            raise ErroDrive(f"Drive: não criou a pasta {nome}: HTTP {resposta.status_code}")
        return str(resposta.json()["id"])

    def baixar(self, arquivo_id: str, destino: Path, max_bytes: int) -> None:
        with self._http.stream("GET", f"{API}/{arquivo_id}", params={"alt": "media", "supportsAllDrives": "true"}) as r:
            if r.status_code >= 400:
                raise ErroDrive(f"Drive: download HTTP {r.status_code}")
            tamanho = 0
            with destino.open("wb") as saida:
                for bloco in r.iter_bytes(64 * 1024):
                    tamanho += len(bloco)
                    if tamanho > max_bytes:  # o resto do arquivo nem é lido; ler_pdf recusa pelo tamanho
                        saida.write(bloco)
                        return
                    saida.write(bloco)

    def mover(self, arquivo_id: str, de: str, para: str) -> None:
        resposta = self._http.patch(f"{API}/{arquivo_id}", params={"addParents": para, "removeParents": de,
                                                                     "supportsAllDrives": "true"})  # fmt: skip
        if resposta.status_code >= 400:
            raise ErroDrive(f"Drive: não moveu o arquivo: HTTP {resposta.status_code}")


def importar_do_drive(repo: Repositorio, drive: Drive, pasta_entrada: str, max_bytes: int) -> list[ResumoEtapa]:
    resumos: list[ResumoEtapa] = []
    for pasta_banca in drive.listar(pasta_entrada, so_pastas=True):
        banca = str(pasta_banca["name"]).strip().upper()
        pdfs = [ArquivoDrive(i["id"], i["name"], i.get("description")) for i in drive.listar(pasta_banca["id"], False)]
        if not pdfs:
            continue
        if repo.fonte_manual(banca) is None:
            log.warning("Drive: pasta %r não é sigla de banca cadastrada (use FCC, VUNESP... ou OUTRA)", banca)
            resumos.append(ResumoEtapa("IMPORTACAO_DRIVE", "FALHA", 0, f"pasta {banca}: banca desconhecida"))
            continue
        with tempfile.TemporaryDirectory(prefix="nqntech-drive-") as tmp:
            arquivos, por_caminho, invalidos = [], {}, []
            for numero, pdf in enumerate(pdfs):
                caminho = Path(tmp) / f"{numero:03d}-{Path(pdf.nome).name}"
                try:
                    link = validar_link(pdf.descricao, pdf.nome)
                except ImportacaoInvalida as erro:
                    log.warning("%s", erro)
                    invalidos.append(pdf)
                    continue
                drive.baixar(pdf.id, caminho, max_bytes)
                arquivos.append((caminho, link))
                por_caminho[caminho] = pdf
            resumo, lidos = importar_arquivos(repo, arquivos, banca, max_bytes) if arquivos else (None, [])
            processados, recusados = drive.subpasta(pasta_banca["id"], PROCESSADOS), None
            for lido in lidos:
                destino = processados if lido.status != "FALHA" else None
                if destino is None:
                    recusados = recusados or drive.subpasta(pasta_banca["id"], RECUSADOS)
                    destino = recusados
                drive.mover(por_caminho[lido.arquivo].id, pasta_banca["id"], destino)
            for pdf in invalidos:  # link inválido na descrição: fica onde está para ser corrigido
                log.warning("Drive: %s ficou na pasta (descrição não é um link https)", pdf.nome)
        if resumo is not None:
            log.info("Drive %s: %d importados, %s", banca, resumo.itens_novos, resumo.mensagem or "sem falhas")
            resumos.append(resumo)
    return resumos


def configuracao(env: Mapping[str, str]) -> tuple[str, str] | None:
    credencial, pasta = env.get("GOOGLE_SA_JSON"), env.get("DRIVE_PASTA_ENTRADA")
    return (credencial, pasta) if credencial and pasta else None
