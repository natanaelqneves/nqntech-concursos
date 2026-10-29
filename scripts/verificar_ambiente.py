"""Verifica o ambiente de desenvolvimento do NqnTech Concursos.

Só usa a biblioteca padrão do Python, para rodar antes de qualquer ambiente virtual existir.
Uso (na raiz do repositório):  python scripts/verificar_ambiente.py [--aguardar SEGUNDOS]
--aguardar espera o postgres ficar saudável e o flyway terminar antes de verificar (útil logo após o "up").
Código de saída 0 = tudo certo; 1 = alguma verificação falhou.
"""

from __future__ import annotations

import argparse
import json
import smtplib
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVICOS_ESPERADOS = ("postgres", "flyway", "mailpit")
VARIAVEIS_OBRIGATORIAS = (
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "COLETOR_DB_PASSWORD",
    "SITE_DB_PASSWORD",
    "COLETOR_CONTATO_EMAIL",
)
PREFIXO_VALOR_EXEMPLO = "troque-"
HOSTS_LOCAIS = {"127.0.0.1", "::1", "localhost"}


@dataclass(frozen=True)
class Resultado:
    nome: str
    ok: bool
    detalhe: str = ""
    apenas_aviso: bool = False


@dataclass(frozen=True)
class Servico:
    nome: str
    estado: str
    saude: str
    codigo_saida: int
    hosts_publicados: tuple[str, ...]


def ler_env(caminho: Path) -> dict[str, str]:
    return ler_env_texto(caminho.read_text(encoding="utf-8"))


def ler_env_texto(conteudo: str) -> dict[str, str]:
    """Parser mínimo de .env: KEY=VALOR, ignora comentários e linhas vazias, remove aspas externas."""
    valores: dict[str, str] = {}
    for linha in conteudo.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[chave.strip()] = valor
    return valores


def parse_compose_ps(saida: str) -> dict[str, Servico]:
    """Aceita os dois formatos do `docker compose ps --format json`: array JSON ou um objeto por linha."""
    saida = saida.strip()
    if not saida:
        return {}
    if saida.startswith("["):
        itens = json.loads(saida)
    else:
        itens = [json.loads(linha) for linha in saida.splitlines() if linha.strip()]

    servicos: dict[str, Servico] = {}
    for item in itens:
        publicados = tuple(
            str(p.get("URL", ""))
            for p in (item.get("Publishers") or [])
            if p.get("PublishedPort")
        )
        servicos[item["Service"]] = Servico(
            nome=item["Service"],
            estado=str(item.get("State", "")).lower(),
            saude=str(item.get("Health", "")).lower(),
            codigo_saida=int(item.get("ExitCode") or 0),
            hosts_publicados=publicados,
        )
    return servicos


def hosts_expostos(servicos: dict[str, Servico]) -> list[str]:
    """Lista 'servico -> host' publicados fora de loopback (0.0.0.0 expõe a porta para a rede inteira)."""
    return [
        f"{s.nome} -> {host}"
        for s in servicos.values()
        for host in s.hosts_publicados
        if host not in HOSTS_LOCAIS
    ]


def executar(comando: list[str], entrada: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        comando, cwd=RAIZ, input=entrada, capture_output=True, text=True, timeout=120, check=False
    )


def verificar_env() -> tuple[list[Resultado], dict[str, str]]:
    caminho = RAIZ / ".env"
    if not caminho.exists():
        return [Resultado(".env existe", False, "copie .env.example para .env")], {}
    env = ler_env(caminho)
    resultados = [Resultado(".env existe", True)]
    faltando = [v for v in VARIAVEIS_OBRIGATORIAS if not env.get(v)]
    resultados.append(
        Resultado("variáveis obrigatórias preenchidas", not faltando, ", ".join(faltando))
    )
    com_exemplo = [k for k, v in env.items() if v.startswith(PREFIXO_VALOR_EXEMPLO)]
    resultados.append(
        Resultado(
            "senhas trocadas (não são as do exemplo)",
            not com_exemplo,
            ", ".join(com_exemplo),
            apenas_aviso=True,
        )
    )
    return resultados, env


def verificar_conteineres() -> tuple[list[Resultado], dict[str, Servico]]:
    proc = executar(["docker", "compose", "ps", "--all", "--format", "json"])
    if proc.returncode != 0:
        return [Resultado("docker compose ps", False, proc.stderr.strip()[:300])], {}
    servicos = parse_compose_ps(proc.stdout)

    resultados: list[Resultado] = []
    for nome in SERVICOS_ESPERADOS:
        if nome not in servicos:
            resultados.append(Resultado(f"serviço {nome} criado", False, "rode docker compose up -d"))

    if (pg := servicos.get("postgres")) is not None:
        resultados.append(
            Resultado(
                "postgres rodando e saudável",
                pg.estado == "running" and pg.saude == "healthy",
                f"estado={pg.estado} saude={pg.saude or '-'}",
            )
        )
    if (fw := servicos.get("flyway")) is not None:
        resultados.append(
            Resultado(
                "flyway terminou com sucesso",
                fw.estado == "exited" and fw.codigo_saida == 0,
                f"estado={fw.estado} exit={fw.codigo_saida} (veja: docker compose logs flyway)",
            )
        )
    if (mp := servicos.get("mailpit")) is not None:
        resultados.append(Resultado("mailpit rodando", mp.estado == "running", f"estado={mp.estado}"))

    expostos = hosts_expostos(servicos)
    resultados.append(
        Resultado("portas presas em 127.0.0.1", not expostos, "; ".join(expostos))
    )
    return resultados, servicos


def aguardar_inicializacao(limite_segundos: int) -> None:
    """Espera o estado estável: postgres saudável e flyway encerrado (com sucesso ou não)."""
    prazo = time.monotonic() + limite_segundos
    while time.monotonic() < prazo:
        proc = executar(["docker", "compose", "ps", "--all", "--format", "json"])
        servicos = parse_compose_ps(proc.stdout) if proc.returncode == 0 else {}
        pg, fw = servicos.get("postgres"), servicos.get("flyway")
        if pg and fw and pg.saude == "healthy" and fw.estado == "exited":
            return
        time.sleep(2)
    print(f"Aviso: o ambiente não estabilizou em {limite_segundos}s; verificando mesmo assim.")


def consultar_banco(env: dict[str, str], sql: str) -> str:
    proc = executar(
        [
            "docker", "compose", "exec", "-T", "postgres",
            "psql", "-v", "ON_ERROR_STOP=1", "-qtAX",
            "-U", env.get("POSTGRES_USER", "concursos_admin"),
            "-d", env.get("POSTGRES_DB", "concursos"),
            "-c", sql,
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300])
    return proc.stdout.strip()


def verificar_banco(env: dict[str, str]) -> list[Resultado]:
    verificacoes = [
        ("schema concursos existe", "SELECT count(*) FROM pg_namespace WHERE nspname = 'concursos'", "1"),
        (
            "extensões unaccent e pg_trgm instaladas",
            "SELECT count(*) FROM pg_extension WHERE extname IN ('unaccent', 'pg_trgm')",
            "2",
        ),
        (
            "unaccent funciona",
            "SELECT extensions.unaccent('Informática e Ciência de Dados')",
            "Informatica e Ciencia de Dados",
        ),
        (
            "migrations aplicadas sem falha",
            "SELECT CASE WHEN count(*) > 0 AND bool_and(success) THEN 'ok' ELSE 'falha' END "
            "FROM concursos.flyway_schema_history WHERE version IS NOT NULL",
            "ok",
        ),
    ]
    resultados: list[Resultado] = []
    for nome, sql, esperado in verificacoes:
        try:
            obtido = consultar_banco(env, sql)
            resultados.append(Resultado(nome, obtido == esperado, f"esperado={esperado} obtido={obtido}"))
        except (RuntimeError, subprocess.TimeoutExpired) as erro:
            resultados.append(Resultado(nome, False, str(erro)))
    return resultados


def verificar_mailpit(env: dict[str, str]) -> list[Resultado]:
    porta_ui = int(env.get("MAILPIT_UI_PORT") or 8025)
    porta_smtp = int(env.get("MAILPIT_SMTP_PORT") or 1025)
    base = f"http://127.0.0.1:{porta_ui}"
    resultados: list[Resultado] = []

    try:
        with urllib.request.urlopen(f"{base}/api/v1/info", timeout=5) as resposta:
            versao = json.load(resposta).get("Version", "?")
        resultados.append(Resultado("interface do Mailpit responde", True, f"{base} (v{versao})"))
    except (urllib.error.URLError, OSError, ValueError) as erro:
        return [Resultado("interface do Mailpit responde", False, f"{base}: {erro}")]

    assunto = f"[NqnTech Concursos] teste do ambiente {uuid.uuid4().hex[:8]}"
    mensagem = EmailMessage()
    mensagem["From"] = "nqntech-concursos@exemplo.com"
    mensagem["To"] = env.get("COLETOR_CONTATO_EMAIL") or "voce@exemplo.com"
    mensagem["Subject"] = assunto
    mensagem.set_content("Se você está lendo isto no Mailpit, o SMTP local funciona.")
    try:
        with smtplib.SMTP("127.0.0.1", porta_smtp, timeout=10) as smtp:
            smtp.send_message(mensagem)
    except (OSError, smtplib.SMTPException) as erro:
        resultados.append(Resultado("envio SMTP para o Mailpit", False, str(erro)))
        return resultados

    recebido = False
    for _ in range(10):
        try:
            with urllib.request.urlopen(f"{base}/api/v1/messages?limit=50", timeout=5) as resposta:
                assuntos = {m.get("Subject") for m in json.load(resposta).get("messages", [])}
            if assunto in assuntos:
                recebido = True
                break
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.5)
    resultados.append(Resultado("e-mail de teste chegou no Mailpit", recebido, assunto))
    return resultados


def imprimir(titulo: str, resultados: list[Resultado]) -> None:
    print(f"\n== {titulo}")
    for r in resultados:
        marca = "OK   " if r.ok else ("AVISO" if r.apenas_aviso else "FALHA")
        detalhe = f"  ({r.detalhe})" if r.detalhe and not r.ok else ""
        print(f"  [{marca}] {r.nome}{detalhe}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verifica o ambiente de dev do NqnTech Concursos.")
    parser.add_argument("--aguardar", type=int, default=0, metavar="SEGUNDOS")
    args = parser.parse_args(argv)
    if args.aguardar > 0:
        aguardar_inicializacao(args.aguardar)

    todos: list[Resultado] = []

    resultados_env, env = verificar_env()
    imprimir("Configuração (.env)", resultados_env)
    todos += resultados_env
    if not env:
        return 1

    resultados_docker, servicos = verificar_conteineres()
    imprimir("Contêineres", resultados_docker)
    todos += resultados_docker

    if "postgres" in servicos:
        resultados_banco = verificar_banco(env)
        imprimir("Banco", resultados_banco)
        todos += resultados_banco

    if "mailpit" in servicos:
        resultados_mail = verificar_mailpit(env)
        imprimir("Mailpit", resultados_mail)
        todos += resultados_mail

    falhas = [r for r in todos if not r.ok and not r.apenas_aviso]
    avisos = [r for r in todos if not r.ok and r.apenas_aviso]
    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s). Corrija e rode de novo.")
        return 1
    sufixo = f" ({len(avisos)} aviso(s))" if avisos else ""
    print(f"RESULTADO: ambiente OK{sufixo}. Mailpit: http://127.0.0.1:{env.get('MAILPIT_UI_PORT') or 8025}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
