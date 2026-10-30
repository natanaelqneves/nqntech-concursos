import coletor.__main__ as principal
from coletor.pipeline.comum import ResumoEtapa

ENV = {
    "DB_HOST": "localhost",
    "DB_NAME": "concursos",
    "COLETOR_DB_USER": "coletor_app",
    "COLETOR_DB_PASSWORD": "x",
    "COLETOR_CONTATO_EMAIL": "teste@exemplo.com",
    "GITHUB_ACTIONS": "true",
}


class ConexaoQueCaiAoFechar:
    closed = False

    def commit(self):
        raise ConnectionError("server closed the connection unexpectedly")

    def rollback(self):
        pass

    def close(self):
        pass


def test_queda_fora_das_etapas_vira_anotacao_no_github(monkeypatch, capsys):
    for nome, valor in ENV.items():
        monkeypatch.setenv(nome, valor)
    monkeypatch.setattr(principal, "conectar", lambda _config: ConexaoQueCaiAoFechar())
    monkeypatch.setattr(
        principal.Orquestrador,
        "executar",
        lambda *_args, **_kwargs: [ResumoEtapa("DESCOBERTA", "SUCESSO", 3, None, "fgv")],
    )

    assert principal.main(["executar"]) == 1

    saida = capsys.readouterr().out
    assert "::error title=Coletor GERAL::FALHA: ConnectionError: server closed the connection" in saida
