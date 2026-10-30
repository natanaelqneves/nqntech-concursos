package br.com.nqntech.site.dados;

import java.math.BigDecimal;
import java.sql.Array;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Leituras do gerador, como {@code site_app} (só leitura; a RLS já esconde o que não está publicado).
 *
 * <p>O filtro de oportunidade (seção 4.3 do contexto) é repetido aqui de propósito: mesmo que um concurso fique
 * marcado como publicado por engano, o site não mostra encerrados nem concursos em fase de prova sem isenção em
 * curso.
 */
@Repository
public class RepositorioSite {

    private static final String OPORTUNIDADE =
            "(c.situacao IN ('PREVISTO', 'INSCRICOES_ABERTAS') OR c.isencao_fim >= :hoje) AND c.situacao <> 'ENCERRADO'";

    private final JdbcClient jdbc;

    public RepositorioSite(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public List<Concurso> concursosPublicados(LocalDate hoje) {
        List<Concurso> base = jdbc.sql("""
                        SELECT c.id, c.slug, c.titulo, o.nome AS orgao, b.sigla AS banca, c.situacao, c.abrangencia,
                               c.uf, c.municipio_ibge, m.nome AS municipio, c.unificado, c.inscricao_inicio,
                               c.inscricao_fim, c.data_prova, c.taxa_min, c.taxa_max, c.total_vagas, c.salario_max,
                               c.escolaridades, c.areas, c.tem_isencao, c.isencao_inicio, c.isencao_fim, c.resumo,
                               c.link_oficial, c.link_inscricao, c.atualizado_em,
                               (SELECT d.url_origem FROM documento d
                                WHERE d.concurso_id = c.id AND d.tipo = 'EDITAL'
                                ORDER BY d.data_publicacao DESC NULLS LAST, d.id DESC LIMIT 1) AS link_edital
                        FROM concurso c
                                 LEFT JOIN orgao o ON o.id = c.orgao_id
                                 LEFT JOIN banca b ON b.id = c.banca_id
                                 LEFT JOIN municipio m ON m.codigo_ibge = c.municipio_ibge
                        WHERE c.publicado AND c.slug IS NOT NULL AND c.resumo IS NOT NULL AND
                        """ + OPORTUNIDADE + " ORDER BY c.id")
                .param("hoje", hoje)
                .query(RepositorioSite::concurso)
                .list();
        if (base.isEmpty()) {
            return List.of();
        }
        Long[] ids = base.stream().map(Concurso::id).toArray(Long[]::new);
        Map<Long, List<Cargo>> cargos = agrupar(jdbc.sql("""
                        SELECT concurso_id, nome, especialidade, escolaridade, vagas, cadastro_reserva, salario, area,
                               disciplinas, tem_redacao
                        FROM cargo WHERE concurso_id = ANY(:ids)
                        ORDER BY concurso_id, salario DESC NULLS LAST, nome, especialidade NULLS FIRST""")
                .param("ids", ids)
                .query((rs, n) -> Map.entry(rs.getLong("concurso_id"), new Cargo(
                        rs.getString("nome"),
                        rs.getString("especialidade"),
                        rs.getString("escolaridade"),
                        (Integer) rs.getObject("vagas"),
                        rs.getBoolean("cadastro_reserva"),
                        rs.getBigDecimal("salario"),
                        rs.getString("area"),
                        textos(rs.getArray("disciplinas")),
                        (Boolean) rs.getObject("tem_redacao"))))
                .list());
        Map<Long, List<Evento>> eventos = agrupar(jdbc.sql("""
                        SELECT concurso_id, evento, inicio, fim FROM concurso_evento
                        WHERE concurso_id = ANY(:ids) ORDER BY concurso_id, ordem""")
                .param("ids", ids)
                .query((rs, n) -> Map.entry(rs.getLong("concurso_id"), new Evento(
                        rs.getString("evento"), rs.getObject("inicio", LocalDate.class),
                        rs.getObject("fim", LocalDate.class))))
                .list());
        Map<Long, List<IsencaoPrevista>> isencoes = agrupar(jdbc.sql("""
                        SELECT ci.concurso_id, ci.tipo_codigo, ci.observacao FROM concurso_isencao ci
                        JOIN isencao_tipo t ON t.codigo = ci.tipo_codigo
                        WHERE ci.concurso_id = ANY(:ids) ORDER BY ci.concurso_id, t.ordem""")
                .param("ids", ids)
                .query((rs, n) -> Map.entry(rs.getLong("concurso_id"),
                        new IsencaoPrevista(rs.getString("tipo_codigo"), rs.getString("observacao"))))
                .list());
        return base.stream()
                .map(c -> c.comDetalhes(
                        cargos.getOrDefault(c.id(), List.of()),
                        eventos.getOrDefault(c.id(), List.of()),
                        isencoes.getOrDefault(c.id(), List.of())))
                .toList();
    }

    public List<Item> areas() {
        return jdbc.sql("SELECT codigo, nome, slug FROM area ORDER BY ordem").query(Item.class).list();
    }

    public List<Item> escolaridades() {
        return jdbc.sql("SELECT codigo, nome, slug FROM escolaridade ORDER BY ordem").query(Item.class).list();
    }

    public List<Item> regioes() {
        return jdbc.sql("SELECT sigla AS codigo, nome, slug FROM regiao ORDER BY ordem").query(Item.class).list();
    }

    public List<Uf> ufs() {
        return jdbc.sql("SELECT sigla, nome, regiao, slug FROM uf ORDER BY nome").query(Uf.class).list();
    }

    public List<Municipio> municipios(List<Integer> codigos) {
        if (codigos.isEmpty()) {
            return List.of();
        }
        return jdbc.sql("SELECT codigo_ibge, nome, uf, slug FROM municipio WHERE codigo_ibge = ANY(:codigos) ORDER BY nome")
                .param("codigos", codigos.toArray(Integer[]::new))
                .query(Municipio.class)
                .list();
    }

    /** Nome, descrição, base legal e link vêm do banco (migration V11); os documentos usuais, do YAML. */
    public List<TipoIsencao> tiposIsencao(Map<String, List<String>> documentosPorTipo) {
        return jdbc.sql("SELECT codigo, nome, slug, descricao, base_legal, link_oficial FROM isencao_tipo ORDER BY ordem")
                .query((rs, n) -> new TipoIsencao(
                        rs.getString("codigo"),
                        rs.getString("nome"),
                        rs.getString("slug"),
                        rs.getString("descricao"),
                        documentosPorTipo.getOrDefault(rs.getString("codigo"), List.of()),
                        rs.getString("base_legal"),
                        rs.getString("link_oficial")))
                .list();
    }

    public Optional<OffsetDateTime> ultimaColeta() {
        return jdbc.sql("SELECT max(fim) FROM execucao_coleta WHERE status <> 'FALHA'")
                .query((rs, n) -> rs.getObject(1, OffsetDateTime.class))
                .optional();
    }

    private static Concurso concurso(ResultSet rs, int linha) throws SQLException {
        return new Concurso(
                rs.getLong("id"),
                rs.getString("slug"),
                rs.getString("titulo"),
                rs.getString("orgao"),
                rs.getString("banca"),
                rs.getString("situacao"),
                rs.getString("abrangencia"),
                rs.getString("uf"),
                (Integer) rs.getObject("municipio_ibge"),
                rs.getString("municipio"),
                rs.getBoolean("unificado"),
                rs.getObject("inscricao_inicio", LocalDate.class),
                rs.getObject("inscricao_fim", LocalDate.class),
                rs.getObject("data_prova", LocalDate.class),
                rs.getBigDecimal("taxa_min"),
                rs.getBigDecimal("taxa_max"),
                (Integer) rs.getObject("total_vagas"),
                (BigDecimal) rs.getObject("salario_max"),
                textos(rs.getArray("escolaridades")),
                textos(rs.getArray("areas")),
                rs.getBoolean("tem_isencao"),
                rs.getObject("isencao_inicio", LocalDate.class),
                rs.getObject("isencao_fim", LocalDate.class),
                rs.getString("resumo"),
                rs.getString("link_oficial"),
                rs.getString("link_inscricao"),
                rs.getString("link_edital"),
                rs.getObject("atualizado_em", OffsetDateTime.class),
                List.of(),
                List.of(),
                List.of());
    }

    private static List<String> textos(Array array) throws SQLException {
        if (array == null) {
            return List.of();
        }
        return Arrays.stream((Object[]) array.getArray()).map(String::valueOf).toList();
    }

    private static <T> Map<Long, List<T>> agrupar(List<Map.Entry<Long, T>> linhas) {
        Map<Long, List<T>> agrupado = new LinkedHashMap<>();
        for (Map.Entry<Long, T> linha : linhas) {
            agrupado.computeIfAbsent(linha.getKey(), k -> new ArrayList<>()).add(linha.getValue());
        }
        return agrupado;
    }
}
