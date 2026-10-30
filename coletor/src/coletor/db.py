"""Acesso ao PostgreSQL: conexão como coletor_app e todas as consultas do coletor (sempre parametrizadas)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from coletor.classificacao.local import Local, Municipio
from coletor.classificacao.orgao import OrgaoInferido
from coletor.config import ConfigBanco
from coletor.extratores.base import CargoExtraido, EditalExtraido
from coletor.fontes.base import DadosEstruturados, SinalDescoberta

log = logging.getLogger(__name__)

Linha = dict[str, Any]

# Concurso sem oportunidade aberta (seção 1 do contexto): encerrado, ou com inscrições encerradas antes de
# %(limite)s (hoje menos a folga para prorrogações), e sem prazo de isenção em curso. Sem data de inscrição
# conhecida o concurso continua acompanhado: é preciso ler o edital para saber.
SEM_OPORTUNIDADE = """(c.situacao = 'ENCERRADO'
                        OR (c.situacao = 'EM_ANDAMENTO' AND c.inscricao_fim < %(limite)s))
                       AND (c.isencao_fim IS NULL OR c.isencao_fim < %(hoje)s)"""


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


class Repositorio:
    def __init__(
        self,
        conn: psycopg.Connection[Linha],
        reconectar: Callable[[], psycopg.Connection[Linha]] | None = None,
    ) -> None:
        self.conn = conn
        self._reconectar = reconectar

    def __enter__(self) -> Repositorio:
        return self

    def __exit__(self, tipo: type[BaseException] | None, *_: object) -> None:
        # Mesmo papel do "with conn" do psycopg, mas sobre a conexão atual (pode ter sido trocada por retomar_conexao).
        if self.conn.closed:
            return
        try:
            if tipo is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()

    def retomar_conexao(self) -> None:
        """Garante uma conexão viva antes de gravar, depois de minutos só na rede (sem nada pendente para gravar).

        O Neon encerra conexões paradas (o processamento "dorme" após ~5 min sem atividade); a descoberta da FGV
        passa mais que isso lendo páginas com o intervalo de cortesia entre acessos.
        """
        if not self.conn.closed:
            try:
                self.conn.execute("SELECT 1")
                self.conn.commit()
                return
            except psycopg.OperationalError as erro:
                log.warning("a conexão com o banco caiu durante a etapa (%s); reconectando", erro)
                with suppress(Exception):
                    self.conn.close()
        if self._reconectar is None:
            raise psycopg.OperationalError("conexão com o banco perdida e sem como reconectar")
        self.conn = self._reconectar()

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

    def urls_sem_oportunidade(self, fonte_id: int, hoje: date, folga_dias: int, releitura_dias: int) -> frozenset[str]:
        """Sinais da fonte cuja página não precisa ser relida hoje: concurso sem oportunidade aberta e página lida
        há menos de `releitura_dias` (gravar_sinal atualiza visto_em a cada leitura)."""
        linhas = self.conn.execute(
            f"""SELECT s.url FROM sinal_descoberta s JOIN concurso c ON c.id = s.concurso_id
                WHERE s.fonte_id = %(fonte)s AND s.visto_em >= now() - make_interval(days => %(releitura)s)
                  AND {SEM_OPORTUNIDADE}""",
            {
                "fonte": fonte_id,
                "releitura": releitura_dias,
                "limite": hoje - timedelta(days=folga_dias),
                "hoje": hoje,
            },
        ).fetchall()
        self.conn.commit()
        return frozenset(linha["url"] for linha in linhas)

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
            """SELECT s.id, s.titulo, s.url, s.data_publicacao, s.payload, s.concurso_id, f.banca_id
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
                      -- A inferência do órgão melhora com o tempo: a mais nova vale (vazia não apaga a antiga).
                      orgao_id = coalesce(EXCLUDED.orgao_id, concurso.orgao_id),
                      link_inscricao = coalesce(EXCLUDED.link_inscricao, concurso.link_inscricao),
                      situacao = CASE WHEN concurso.situacao = 'PREVISTO' AND %(tem_edital)s
                                      THEN 'EM_ANDAMENTO' ELSE concurso.situacao END
                  -- Só toca a linha se algo mudou, para atualizado_em continuar significando "mudou".
                  WHERE (concurso.titulo, concurso.orgao_id, concurso.link_inscricao, concurso.situacao)
                        IS DISTINCT FROM (EXCLUDED.titulo, coalesce(EXCLUDED.orgao_id, concurso.orgao_id),
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

    def marcar_encerrado(self, concurso_id: int, desde: datetime | None) -> bool:
        """A fonte deu o concurso por finalizado. `desde` aproxima quando (última publicação); sem ela, agora."""
        cursor = self.conn.execute(
            """UPDATE concurso SET situacao = 'ENCERRADO', encerrado_em = coalesce(%s, now())
               WHERE id = %s AND situacao <> 'ENCERRADO'""",
            (desde, concurso_id),
        )
        return cursor.rowcount > 0

    def reabrir(self, concurso_id: int) -> bool:
        """Concurso dado por encerrado que voltou a "em andamento" na fonte."""
        cursor = self.conn.execute(
            "UPDATE concurso SET situacao = 'EM_ANDAMENTO' WHERE id = %s AND situacao = 'ENCERRADO'", (concurso_id,)
        )
        return cursor.rowcount > 0

    def descartar_sinal(self, sinal_id: int) -> None:
        self.conn.execute("UPDATE sinal_descoberta SET status = 'DESCARTADO' WHERE id = %s", (sinal_id,))

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
    def ignorar_documentos_sem_interesse(self, hoje: date, folga_dias: int) -> int:
        """Só vale baixar o que pode mudar a página do concurso: editais (cargos, datas, taxas, isenções) e
        retificações. Comunicados e documentos de concursos sem oportunidade aberta não são baixados."""
        with self.transacao():
            cursor = self.conn.execute(
                f"""UPDATE documento d SET status_extracao = 'IGNORADO'
                    FROM concurso c
                    WHERE c.id = d.concurso_id AND d.status_extracao = 'PENDENTE'
                      AND (({SEM_OPORTUNIDADE}) OR d.tipo IN ('COMUNICADO', 'OUTRO'))""",
                {"limite": hoje - timedelta(days=folga_dias), "hoje": hoje},
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

    # --- classificação ---------------------------------------------------------------------------
    def codigos_area(self) -> frozenset[str]:
        linhas = self.conn.execute("SELECT codigo FROM area").fetchall()
        self.conn.commit()
        return frozenset(linha["codigo"] for linha in linhas)

    def municipios(self) -> list[Municipio]:
        linhas = self.conn.execute("SELECT codigo_ibge, nome, uf, slug FROM municipio").fetchall()
        self.conn.commit()
        return [Municipio(**linha) for linha in linhas]

    def concursos_para_classificar(self, dias_encerrado: int) -> list[Linha]:
        """Concursos que ainda podem ir ao site, com o contexto para achar o local: órgão, descrição da página
        da banca e o começo do edital lido (onde costuma estar "Estado de ..."/"Município de ...")."""
        return self.conn.execute(
            """SELECT c.id, c.titulo, c.link_oficial, c.abrangencia, c.uf, c.municipio_ibge, c.unificado,
                      o.id AS orgao_id, o.nome AS orgao_nome, o.esfera AS orgao_esfera, o.uf AS orgao_uf,
                      o.municipio AS orgao_municipio, o.municipio_ibge AS orgao_municipio_ibge,
                      (SELECT s.payload ->> 'descricao' FROM sinal_descoberta s WHERE s.concurso_id = c.id
                       ORDER BY s.visto_em DESC LIMIT 1) AS descricao,
                      (SELECT left(d.texto_extraido, 3000) FROM documento d WHERE d.id = c.edital_documento_id)
                          AS edital_inicio
               FROM concurso c LEFT JOIN orgao o ON o.id = c.orgao_id
               WHERE c.situacao <> 'ENCERRADO' OR c.encerrado_em >= now() - make_interval(days => %s)
               ORDER BY c.id""",
            (dias_encerrado,),
        ).fetchall()

    def cargos_dos_concursos(self, concurso_ids: Sequence[int]) -> list[Linha]:
        return self.conn.execute(
            """SELECT id, concurso_id, nome, especialidade, escolaridade, area FROM cargo
               WHERE concurso_id = ANY(%s) ORDER BY id""",
            (list(concurso_ids),),
        ).fetchall()

    def aplicar_local(self, concurso_id: int, local: Local, unificado: bool) -> bool:
        """Grava abrangência, UF, município e CNU só se mudaram. Devolve True se alterou."""
        cursor = self.conn.execute(
            """UPDATE concurso SET abrangencia = %(abrangencia)s, uf = %(uf)s, municipio_ibge = %(municipio)s,
                                  unificado = %(unificado)s
               WHERE id = %(id)s
                 AND (abrangencia, uf, municipio_ibge, unificado)
                     IS DISTINCT FROM (%(abrangencia)s, %(uf)s::char(2), %(municipio)s::integer, %(unificado)s)""",
            {
                "id": concurso_id,
                "abrangencia": local.abrangencia,
                "uf": local.uf,
                "municipio": local.municipio_ibge,
                "unificado": unificado,
            },
        )
        return cursor.rowcount > 0

    def completar_municipio_do_orgao(self, orgao_id: int, uf: str, municipio_ibge: int) -> None:
        # Só completa órgão que já tem a mesma UF: mudar a UF do órgão mexeria na chave única dele.
        self.conn.execute(
            """UPDATE orgao SET municipio_ibge = %s
               WHERE id = %s AND uf = %s AND municipio_ibge IS DISTINCT FROM %s""",
            (municipio_ibge, orgao_id, uf, municipio_ibge),
        )

    def aplicar_classificacao_cargo(self, cargo_id: int, area: str, escolaridade: str | None) -> bool:
        cursor = self.conn.execute(
            """UPDATE cargo SET area = %(area)s, escolaridade = %(escolaridade)s
               WHERE id = %(id)s AND (area, escolaridade) IS DISTINCT FROM (%(area)s, %(escolaridade)s)""",
            {"id": cargo_id, "area": area, "escolaridade": escolaridade},
        )
        return cursor.rowcount > 0
