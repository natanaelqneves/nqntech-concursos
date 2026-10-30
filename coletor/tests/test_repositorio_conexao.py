"""Reconexão do repositório quando o Neon derruba a conexão parada (sem banco: conexões simuladas)."""

import psycopg
import pytest

from coletor.db import Repositorio


class ConexaoFalsa:
    def __init__(self, viva: bool = True) -> None:
        self.closed = False
        self.viva = viva
        self.comandos: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql: str, *_args):
        if not self.viva:
            raise psycopg.OperationalError("the connection is lost")
        self.comandos.append(sql)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_conexao_viva_nao_reconecta():
    conn = ConexaoFalsa()
    repo = Repositorio(conn, reconectar=lambda: pytest.fail("não deveria reconectar"))
    repo.retomar_conexao()
    assert repo.conn is conn
    assert conn.comandos == ["SELECT 1"]


def test_conexao_perdida_e_trocada_por_uma_nova():
    morta, nova = ConexaoFalsa(viva=False), ConexaoFalsa()
    repo = Repositorio(morta, reconectar=lambda: nova)
    repo.retomar_conexao()
    assert repo.conn is nova
    assert morta.closed


def test_conexao_fechada_e_trocada_sem_testar():
    fechada, nova = ConexaoFalsa(), ConexaoFalsa()
    fechada.closed = True
    repo = Repositorio(fechada, reconectar=lambda: nova)
    repo.retomar_conexao()
    assert repo.conn is nova
    assert fechada.comandos == []


def test_sem_como_reconectar_a_falha_aparece():
    with pytest.raises(psycopg.OperationalError):
        Repositorio(ConexaoFalsa(viva=False)).retomar_conexao()


def test_saida_do_bloco_fecha_a_conexao_atual():
    original, nova = ConexaoFalsa(viva=False), ConexaoFalsa()
    with Repositorio(original, reconectar=lambda: nova) as repo:
        repo.retomar_conexao()
    assert nova.closed and nova.commits >= 1


def test_erro_no_bloco_desfaz_e_fecha():
    conn = ConexaoFalsa()
    with pytest.raises(RuntimeError), Repositorio(conn):
        raise RuntimeError("falha")
    assert conn.rollbacks == 1 and conn.closed
