"""Acesso ao PostgreSQL: conexão como coletor_app e todas as consultas do coletor (sempre parametrizadas)."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from coletor.config import ConfigBanco
from coletor.extratores.base import CargoExtraido, EditalExtraido
from coletor.fontes.base import DadosEstruturados, SinalDescoberta

log = logging.getLogger(__name__)

Linha = dict[str, Any]


def conectar(config: ConfigBanco, tentativas: int = 3) -> psycopg.Connection[Linha]:
    ultimo: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            conn = psycopg.connect(**config.parametros(), row_factory=dict_row, autocommit=False)
            # Garante o schema mesmo se o papel não tiver search_path padrão (ex.: banco de testes).
            conn.execute("SET search_path = concursos")
            conn.commit()
            return conn
        except psycopg.OperationalError as erro:
            ultimo = erro
            log.warning("conexão ao banco falhou (tentativa %d/%d): %s", tentativa, tentativas, erro)
            if tentativa < tentativas:
                time.sleep(3 * tentativa)  # dá tempo de o Neon "acordar" o processamento
    raise ultimo  # type: ignore[misc]


@dataclass(frozen=True)
class _Registro:
    nome: str
    especialidade: str | None
    escolaridade: str | None
    vagas: int | None
    cadastro_reserva: bool
    salario: Decimal | None
    uf_lotacao: str | None


@dataclass(frozen=True)
class FonteCadastrada:
    id: int
    nome: str
    banca_id: int | None


@dataclass(frozen=True)
class OrgaoInferido:
    nome: str
    esfera: str | None
    uf: str | None
    municipio: str | None


class Repositorio:
    def __init__(self, conn: psycopg.Connection[Linha]) -> None:
        self.conn = conn

    @contextmanager
    def transacao(self) -> Iterator[None]:
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    # --- execuções -------------------------------------------------------------------------------
    def registrar_execucao(
        self,
        etapa: str,
        inicio: datetime,
        status: str,
        itens_novos: int,
        mensagem_erro: str | None = None,
        fonte_id: int | None = None,
    ) -> None:
        with self.transacao():
            self.conn.execute(
                """INSERT INTO execucao_coleta (fonte_id, etapa, inicio, fim, status, itens_novos, mensagem_erro)
                   VALUES (%s, %s, %s, now(), %s, %s, %s)""",
                (fonte_id, etapa, inicio, status, itens_novos, (mensagem_erro or None) and mensagem_erro[:4000]),
            )

    # --- descoberta ------------------------------------------------------------------------------
    def fontes_ativas(self) -> list[FonteCadastrada]:
        linhas = self.conn.execute("SELECT id, nome, banca_id FROM fonte WHERE ativa ORDER BY id").fetchall()
        self.conn.commit()
        return [FonteCadastrada(**linha) for linha in linhas]

    def gravar_sinal(self, fonte_id: int, sinal: SinalDescoberta) -> bool:
        """Insere ou atualiza (payload novo = arquivos novos). Devolve True se o sinal é inédito."""
        linha = self.conn.execute(
            """INSERT INTO sinal_descoberta (fonte_id, titulo, url, data_publicacao, payload)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (fonte_id, url) DO UPDATE
                  SET titulo = EXCLUDED.titulo, data_publicacao = EXCLUDED.data_publicacao,
                      payload = EXCLUDED.payload, visto_em = now()
               RETURNING (xmax = 0) AS inserido""",
            (fonte_id, sinal.titulo[:1000], sinal.url, sinal.data_publicacao, Jsonb(sinal.payload_completo())),
        ).fetchone()
        return bool(linha and linha["inserido"])

    # --- vinculação ------------------------------------------------------------------------------
    def sinais_para_vincular(self, desde: datetime) -> list[Linha]:
        return self.conn.execute(
            """SELECT s.id, s.titulo, s.url, s.payload, s.concurso_id, f.banca_id
               FROM sinal_descoberta s JOIN fonte f ON f.id = s.fonte_id
               WHERE s.status = 'NOVO' OR (s.status = 'VINCULADO' AND s.visto_em >= %s)
               ORDER BY s.id""",
            (desde,),
        ).fetchall()

    def garantir_orgao(self, orgao: OrgaoInferido) -> int:
        linha = self.conn.execute(
            """INSERT INTO orgao (nome, esfera, uf, municipio) VALUES (%s, %s, %s, %s)
               ON CONFLICT ON CONSTRAINT orgao_uk DO UPDATE SET nome = EXCLUDED.nome
               RETURNING id""",
            (orgao.nome[:300], orgao.esfera, orgao.uf, orgao.municipio),
        ).fetchone()
        assert linha is not None
        return int(linha["id"])

    def garantir_concurso(
        self,
        *,
        titulo: str,
        link_oficial: str,
        banca_id: int | None,
        orgao_id: int | None,
        link_inscricao: str | None,
        tem_edital: bool,
    ) -> int:
        linha = self.conn.execute(
            """INSERT INTO concurso (titulo, link_oficial, banca_id, orgao_id, link_inscricao, situacao)
               VALUES (%(titulo)s, %(link)s, %(banca)s, %(orgao)s, %(inscricao)s,
                       CASE WHEN %(tem_edital)s THEN 'EM_ANDAMENTO' ELSE 'PREVISTO' END)
               ON CONFLICT (link_oficial) DO UPDATE
                  SET titulo = EXCLUDED.titulo,
                      orgao_id = coalesce(concurso.orgao_id, EXCLUDED.orgao_id),
                      link_inscricao = coalesce(EXCLUDED.link_inscricao, concurso.link_inscricao),
                      situacao = CASE WHEN concurso.situacao = 'PREVISTO' AND %(tem_edital)s
                                      THEN 'EM_ANDAMENTO' ELSE concurso.situacao END
                  -- Só toca a linha se algo mudou, para atualizado_em continuar significando "mudou".
                  WHERE (concurso.titulo, concurso.orgao_id, concurso.link_inscricao, concurso.situacao)
                        IS DISTINCT FROM (EXCLUDED.titulo, coalesce(concurso.orgao_id, EXCLUDED.orgao_id),
                                          coalesce(EXCLUDED.link_inscricao, concurso.link_inscricao),
                                          CASE WHEN concurso.situacao = 'PREVISTO' AND %(tem_edital)s
                                               THEN 'EM_ANDAMENTO' ELSE concurso.situacao END)
               RETURNING id""",
            {
                "titulo": titulo[:1000],
                "link": link_oficial,
                "banca": banca_id,
                "orgao": orgao_id,
                "inscricao": link_inscricao,
                "tem_edital": tem_edital,
            },
        ).fetchone()
        if linha is None:
            linha = self.conn.execute("SELECT id FROM concurso WHERE link_oficial = %s", (link_oficial,)).fetchone()
        assert linha is not None
        return int(linha["id"])

    def garantir_documento(
        self, concurso_id: int, tipo: str, titulo: str, url: str, data_publicacao: date | None
    ) -> bool:
        linha = self.conn.execute(
            """INSERT INTO documento (concurso_id, tipo, titulo, url_origem, data_publicacao)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (url_origem) DO NOTHING
               RETURNING id""",
            (concurso_id, tipo, titulo[:500], url, data_publicacao),
        ).fetchone()
        return linha is not None

    def marcar_sinal_vinculado(self, sinal_id: int, concurso_id: int) -> None:
        self.conn.execute(
            "UPDATE sinal_descoberta SET status = 'VINCULADO', concurso_id = %s WHERE id = %s",
            (concurso_id, sinal_id),
        )

    def aplicar_dados_fonte(self, concurso_id: int, dados: DadosEstruturados, situacao: str) -> bool:
        """Campos e cargos vindos da página da banca. Não sobrescreve concurso já estruturado pelo edital e só
        grava o que mudou (para atualizado_em continuar significando "mudou"). Devolve True se alterou algo."""
        atual = self.conn.execute(
            """SELECT edital_documento_id, numero_edital, ano, inscricao_inicio, inscricao_fim, data_prova, taxa_min,
                      taxa_max, avisos_extracao, situacao, origem_estrutura
               FROM concurso WHERE id = %s""",
            (concurso_id,),
        ).fetchone()
        if atual is None or atual["edital_documento_id"] is not None:
            return False
        novo = {
            "numero_edital": dados.numero_edital or atual["numero_edital"],
            "ano": dados.ano or atual["ano"],
            "inscricao_inicio": dados.inscricao_inicio,
            "inscricao_fim": dados.inscricao_fim,
            "data_prova": dados.data_prova,
            "taxa_min": dados.taxa_min,
            "taxa_max": dados.taxa_max,
            "avisos_extracao": list(dados.avisos),
            "situacao": situacao,
            "origem_estrutura": "FONTE",
        }
        alterou = any(atual[campo] != valor for campo, valor in novo.items())
        if alterou:
            self.conn.execute(
                """UPDATE concurso SET numero_edital = %(numero_edital)s, ano = %(ano)s,
                          inscricao_inicio = %(inscricao_inicio)s, inscricao_fim = %(inscricao_fim)s,
                          data_prova = %(data_prova)s, taxa_min = %(taxa_min)s, taxa_max = %(taxa_max)s,
                          avisos_extracao = %(avisos)s, situacao = %(situacao)s, origem_estrutura = 'FONTE'
                   WHERE id = %(id)s""",
                {**novo, "avisos": Jsonb(novo["avisos_extracao"]), "id": concurso_id},
            )
        return self._substituir_cargos_se_mudaram(concurso_id, dados.cargos) or alterou

    def _substituir_cargos_se_mudaram(self, concurso_id: int, cargos: Sequence[CargoExtraido]) -> bool:
        def chave(c: Any) -> tuple:
            return (
                c.nome,
                c.especialidade,
                c.escolaridade,
                c.vagas,
                c.cadastro_reserva,
                None if c.salario is None else Decimal(str(c.salario)),
                c.uf_lotacao,
            )

        atuais = self.conn.execute(
            """SELECT nome, especialidade, escolaridade, vagas, cadastro_reserva, salario, uf_lotacao
               FROM cargo WHERE concurso_id = %s""",
            (concurso_id,),
        ).fetchall()
        if {chave(_Registro(**c)) for c in atuais} == {chave(c) for c in cargos}:
            return False
        self.conn.execute("DELETE FROM cargo WHERE concurso_id = %s", (concurso_id,))
        self._inserir_cargos(concurso_id, cargos)
        return True

    def _inserir_cargos(self, concurso_id: int, cargos: Sequence[CargoExtraido]) -> None:
        for cargo in cargos:
            self.conn.execute(
                """INSERT INTO cargo (concurso_id, nome, especialidade, escolaridade, vagas, cadastro_reserva,
                                      salario, uf_lotacao)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT ON CONSTRAINT cargo_uk DO NOTHING""",
                (
                    concurso_id,
                    cargo.nome[:300],
                    cargo.especialidade and cargo.especialidade[:300],
                    cargo.escolaridade,
                    cargo.vagas,
                    cargo.cadastro_reserva,
                    cargo.salario,
                    cargo.uf_lotacao,
                ),
            )

    # --- documentos ------------------------------------------------------------------------------
    def ignorar_documentos_sem_interesse(self) -> int:
        """Só vale baixar o que pode mudar a página do concurso: editais (cargos, datas, taxas, isenções) e
        retificações. Comunicados e documentos de concursos encerrados não são baixados."""
        with self.transacao():
            cursor = self.conn.execute(
                """UPDATE documento d SET status_extracao = 'IGNORADO'
                   FROM concurso c
                   WHERE c.id = d.concurso_id AND d.status_extracao = 'PENDENTE'
                     AND (c.situacao = 'ENCERRADO' OR d.tipo IN ('COMUNICADO', 'OUTRO'))"""
            )
            return cursor.rowcount

    def documentos_pendentes(self, limite: int) -> list[Linha]:
        # Ordem: editais antes de retificações; concursos ainda sem edital lido (recém-descobertos) primeiro,
        # depois os com inscrições abertas; por fim os mais recentes. O limite por execução drena o acúmulo
        # em poucos dias.
        return self.conn.execute(
            """SELECT d.id, d.url_origem, d.tipo, d.concurso_id
               FROM documento d
                        JOIN concurso c ON c.id = d.concurso_id
               WHERE d.status_extracao = 'PENDENTE'
               ORDER BY (d.tipo = 'EDITAL') DESC,
                        (c.edital_documento_id IS NULL) DESC,
                        (c.situacao = 'INSCRICOES_ABERTAS') DESC,
                        d.data_publicacao DESC NULLS LAST, d.id DESC
               LIMIT %s""",
            (limite,),
        ).fetchall()

    def texto_por_hash(self, sha256: str) -> Linha | None:
        return self.conn.execute(
            """SELECT texto_extraido, status_extracao FROM documento
               WHERE hash_sha256 = %s AND status_extracao IN ('OK', 'SEM_TEXTO') LIMIT 1""",
            (sha256,),
        ).fetchone()

    def salvar_extracao(self, documento_id: int, sha256: str | None, texto: str | None, status: str) -> None:
        with self.transacao():
            self.conn.execute(
                """UPDATE documento SET hash_sha256 = coalesce(%s, hash_sha256), texto_extraido = %s,
                                        status_extracao = %s
                   WHERE id = %s""",
                (sha256, texto, status, documento_id),
            )

    # --- estruturação ----------------------------------------------------------------------------
    def concursos_para_estruturar(self) -> list[Linha]:
        return self.conn.execute(
            """SELECT c.id, b.sigla AS banca, e.id AS documento_id, e.texto_extraido
               FROM concurso c
                        JOIN banca b ON b.id = c.banca_id
                        JOIN LATERAL (SELECT d.id, d.texto_extraido FROM documento d
                                      WHERE d.concurso_id = c.id AND d.tipo = 'EDITAL' AND d.status_extracao = 'OK'
                                      ORDER BY d.data_publicacao DESC NULLS LAST, d.id DESC LIMIT 1) e ON true
               WHERE c.edital_documento_id IS DISTINCT FROM e.id"""
        ).fetchall()

    def aplicar_edital(self, concurso_id: int, documento_id: int, edital: EditalExtraido, situacao: str) -> None:
        with self.transacao():
            self.conn.execute(
                """UPDATE concurso SET numero_edital = coalesce(%s, numero_edital), ano = coalesce(%s, ano),
                          inscricao_inicio = %s, inscricao_fim = %s, data_prova = %s, taxa_min = %s, taxa_max = %s,
                          avisos_extracao = %s, situacao = %s, edital_documento_id = %s,
                          origem_estrutura = 'EDITAL'
                   WHERE id = %s""",
                (
                    edital.numero_edital,
                    edital.ano,
                    edital.inscricao_inicio,
                    edital.inscricao_fim,
                    edital.data_prova,
                    edital.taxa_min,
                    edital.taxa_max,
                    Jsonb(list(edital.avisos)),
                    situacao,
                    documento_id,
                    concurso_id,
                ),
            )
            self.conn.execute("DELETE FROM cargo WHERE concurso_id = %s", (concurso_id,))
            self._inserir_cargos(concurso_id, edital.cargos)

    def atualizar_situacoes_por_data(self, hoje: date, dias_sem_ver: int) -> int:
        with self.transacao():
            fechadas = self.conn.execute(
                """UPDATE concurso SET situacao = 'EM_ANDAMENTO'
                   WHERE situacao = 'INSCRICOES_ABERTAS' AND inscricao_fim < %s""",
                (hoje,),
            ).rowcount
            # Saiu da lista "em andamento" da banca há dias: tratamos como encerrado.
            encerradas = self.conn.execute(
                """UPDATE concurso c SET situacao = 'ENCERRADO'
                   WHERE c.situacao <> 'ENCERRADO'
                     AND EXISTS (SELECT 1 FROM sinal_descoberta s WHERE s.concurso_id = c.id)
                     AND NOT EXISTS (SELECT 1 FROM sinal_descoberta s
                                     WHERE s.concurso_id = c.id AND s.visto_em >= now() - make_interval(days => %s))""",
                (dias_sem_ver,),
            ).rowcount
        return fechadas + encerradas
