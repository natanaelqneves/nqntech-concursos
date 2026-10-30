package br.com.nqntech.site.geracao;

import static br.com.nqntech.site.Fixtures.concurso;
import static org.assertj.core.api.Assertions.assertThat;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import br.com.nqntech.site.dados.Concurso;
import br.com.nqntech.site.dados.TipoIsencao;

/** Renderização real dos templates, sem banco. Dados vindos das fontes são tratados como hostis. */
class PaginasTest {

    private static final LocalDate HOJE = LocalDate.of(2026, 10, 25);
    private final Paginas paginas = new Paginas(GeradorSite.criarTemplates(), "https://exemplo.dev",
            new Formatos(HOJE, Map.of("TI", "Tecnologia da informação", "JURIDICA", "Jurídica")), "29/10/2026 às 06:40");
    private final List<TipoIsencao> tipos = List.of(new TipoIsencao("CADUNICO", "Inscritos no CadÚnico", "cadunico",
            "Descrição.", List.of("NIS"), "Lei nº 13.656/2018.", "https://www.planalto.gov.br/l13656.htm"));

    @Test
    void paginaDoConcursoEscapaTextoEDescartaLinkPerigoso() {
        Concurso base = concurso("tjpb-2026", "TJPB", "ESTADUAL", "PB", false, "INSCRICOES_ABERTAS",
                HOJE.minusDays(5), HOJE.plusDays(20), HOJE.plusDays(80), HOJE.plusDays(2));
        Concurso hostil = new Concurso(base.id(), base.slug(), base.titulo(), "Órgão <script>alert(1)</script>",
                base.banca(), base.situacao(), base.abrangencia(), base.uf(), null, null, false, base.inscricaoInicio(),
                base.inscricaoFim(), base.dataProva(), base.taxaMin(), base.taxaMax(), base.totalVagas(),
                base.salarioMax(), base.escolaridades(), base.areas(), true, base.isencaoInicio(), base.isencaoFim(),
                "Resumo com <img src=x onerror=alert(1)> e \"aspas\".", "javascript:alert(1)",
                "https://portal.conhecimento.fgv.br/inscricao", "data:text/html,oi", base.atualizadoEm(),
                base.cargos(), base.eventos(), base.isencoes());

        String html = paginas.concurso(hostil, tipos).html();

        assertThat(html)
                .doesNotContain("<script>alert(1)</script>", "<img src=x", "javascript:", "data:text/html")
                .contains("&lt;script&gt;alert(1)&lt;/script&gt;")
                .contains("href=\"https://portal.conhecimento.fgv.br/inscricao\"")
                .contains("<link rel=\"canonical\" href=\"https://exemplo.dev/concurso/tjpb-2026/\">")
                .contains("href=\"/isencoes/cadunico/\"")
                .contains("20/10/2026 a 14/11/2026")
                .contains("Banco de Dados");
        // O JSON-LD também não pode fechar o bloco <script>.
        assertThat(html.split("application/ld\\+json")[1].split("</script>")[0]).doesNotContain("<");
    }

    @Test
    void inicioListaOsAbertosEODestaqueDeIsencao() {
        Concurso aberto = concurso("inss-2026", "INSS", "NACIONAL", null, false, "INSCRICOES_ABERTAS",
                HOJE.minusDays(1), HOJE.plusDays(10), null, HOJE.plusDays(3));
        String html = paginas.inicio(List.of(aberto), List.of(aberto), 1).html();
        assertThat(html)
                .contains("<html lang=\"pt-BR\">")
                .contains("Pedido de isenção da taxa aberto")
                .contains("href=\"/concurso/inss-2026/\"")
                .contains("data-prazo=\"2026-10-28\"")
                .contains("Confira sempre o")
                .contains("\"@type\":\"WebSite\"");
    }

    @Test
    void listaVaziaTemMensagem() {
        String html = paginas.lista("/area/ti/", "Concursos na área TI", "Descrição", List.of(), false, List.of())
                .html();
        assertThat(html).contains("Nenhum concurso aberto ou previsto aqui no momento.");
    }
}
