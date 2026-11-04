"""Diagnóstico TLS (roda no GitHub Actions): por que FUMARC e COMPERVE falham na verificação do certificado.

Para cada host: o que o servidor envia (cadeia), emissor e validade do certificado do site, e o endereço "CA Issuers"
(AIA) do intermediário que falta. Baixa esse intermediário (é público, publicado pela própria autoridade
certificadora) e testa a conexão de novo COM verificação, usando o bundle padrão + esse intermediário. Nunca desliga
a verificação: se ainda falhar, o problema não é só cadeia incompleta.
"""

from __future__ import annotations

import json
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import certifi
import requests

HOSTS = ["www.fumarc.com.br", "fumarc.com.br", "www.comperve.ufrn.br", "comperve.ufrn.br"]
UA = "NqnTechConcursos/0.1 (site publico e gratuito de concursos; respeita robots.txt)"
DESTINO = Path("coletor/tests/fixtures/tls")


def cadeia(host: str) -> str:
    saida = subprocess.run(
        ["openssl", "s_client", "-connect", f"{host}:443", "-servername", host, "-showcerts"],
        input=b"",
        capture_output=True,
        timeout=30,
    )
    return saida.stdout.decode(errors="replace")


def certificado_do_site(host: str) -> str:
    """PEM do certificado do site, obtido sem validar (só para ler o AIA; nada é trafegado nesta conexão)."""
    contexto = ssl.create_default_context()
    contexto.check_hostname = False
    contexto.verify_mode = ssl.CERT_NONE
    with (
        socket.create_connection((host, 443), timeout=20) as sock,
        contexto.wrap_socket(sock, server_hostname=host) as tls,
    ):
        return ssl.DER_cert_to_PEM_cert(tls.getpeercert(binary_form=True))


def info(pem: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(pem)
    return subprocess.run(
        [
            "openssl",
            "x509",
            "-noout",
            "-subject",
            "-issuer",
            "-dates",
            "-ext",
            "authorityInfoAccess,subjectAltName",
            "-in",
            f.name,
        ],
        capture_output=True,
        text=True,
    ).stdout


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    relatorio: dict = {}
    for host in HOSTS:
        item: dict = {}
        relatorio[host] = item
        try:
            requests.get(f"https://{host}/robots.txt", timeout=20, headers={"User-Agent": UA})
            item["verificacao_padrao"] = "ok"
            continue
        except requests.exceptions.SSLError as erro:
            item["verificacao_padrao"] = str(erro)[:300]
        except requests.RequestException as erro:
            item["erro_conexao"] = str(erro)[:300]
            continue
        texto = cadeia(host)
        item["certificados_enviados"] = texto.count("BEGIN CERTIFICATE")
        item["cadeia"] = [
            l.strip() for l in texto.splitlines() if l.strip().startswith(("0 s:", "1 s:", "2 s:", "   i:", "  i:"))
        ][:10]
        try:
            pem = certificado_do_site(host)
        except OSError as erro:
            item["erro_leitura"] = str(erro)[:200]
            continue
        detalhes = info(pem)
        item["certificado"] = detalhes
        aia = next(
            (l.split("URI:", 1)[1].strip() for l in detalhes.splitlines() if "CA Issuers" in l and "URI:" in l), None
        )
        item["aia"] = aia
        if not aia:
            continue
        try:
            der = urllib.request.urlopen(aia, timeout=20).read()
        except OSError as erro:
            item["erro_aia"] = str(erro)[:200]
            continue
        try:
            intermediario = ssl.DER_cert_to_PEM_cert(der)
        except ValueError:
            intermediario = der.decode(errors="replace")  # já veio em PEM
        item["intermediario"] = info(intermediario)
        nome = host.replace(".", "_")
        (DESTINO / f"intermediario_{nome}.pem").write_text(intermediario, encoding="utf-8")
        bundle = DESTINO / f"_bundle_{nome}.pem"
        bundle.write_text(Path(certifi.where()).read_text() + "\n" + intermediario, encoding="utf-8")
        try:
            r = requests.get(f"https://{host}/robots.txt", timeout=20, headers={"User-Agent": UA}, verify=str(bundle))
            item["com_intermediario"] = {"status": r.status_code, "robots": r.text[:1500] if r.ok else ""}
            home = requests.get(f"https://{host}/", timeout=25, headers={"User-Agent": UA}, verify=str(bundle))
            item["home"] = {
                "status": home.status_code,
                "tipo": home.headers.get("Content-Type"),
                "bytes": len(home.content),
            }
            if home.ok:
                (DESTINO / f"home_{nome}.html").write_text(home.text, encoding="utf-8")
        except requests.RequestException as erro:
            item["com_intermediario"] = {"erro": str(erro)[:300]}
        bundle.unlink()
    (DESTINO / "_tls.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(relatorio, ensure_ascii=False, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
