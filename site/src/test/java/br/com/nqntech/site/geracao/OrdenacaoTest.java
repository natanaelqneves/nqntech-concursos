package br.com.nqntech.site.geracao;

import static br.com.nqntech.site.Fixtures.concurso;
import static org.assertj.core.api.Assertions.assertThat;

import java.time.LocalDate;
import java.util.List;

import org.junit.jupiter.api.Test;

import br.com.nqntech.site.dados.Concurso;

class OrdenacaoTest {

    private static final LocalDate HOJE = LocalDate.of(2026, 10, 25);
    private static final LocalDate ABRIU = HOJE.minusDays(5);
    private static final LocalDate FECHA = HOJE.plusDays(20);

    @Test
    void telaInicialCnuDepoisNacionaisDepoisProvaMaisProxima() {
        Concurso estadualCedo = concurso("pb", "TJPB", "ESTADUAL", "PB", false, "INSCRICOES_ABERTAS", ABRIU, FECHA,
                HOJE.plusDays(40), null);
        Concurso estadualSemProva = concurso("pr", "PCPR", "ESTADUAL", "PR", false, "INSCRICOES_ABERTAS", ABRIU, FECHA,
                null, null);
        Concurso nacional = concurso("inss", "INSS", "NACIONAL", null, false, "INSCRICOES_ABERTAS", ABRIU, FECHA,
                HOJE.plusDays(90), null);
        Concurso cnu = concurso("cnu", "MGI", "NACIONAL", null, true, "INSCRICOES_ABERTAS", ABRIU, FECHA,
                HOJE.plusDays(120), null);
        Concurso previsto = concurso("prev", "Câmara", "MUNICIPAL", "SP", false, "PREVISTO", null, null, null, null);
        Concurso porAbrir = concurso("depois", "SEFAZ", "ESTADUAL", "AL", false, "INSCRICOES_ABERTAS",
                HOJE.plusDays(3), FECHA, HOJE.plusDays(30), null);

        List<Concurso> tela = Ordenacao.telaInicial(
                List.of(estadualSemProva, previsto, estadualCedo, nacional, porAbrir, cnu), HOJE);

        assertThat(tela).extracting(Concurso::slug).containsExactly("cnu", "inss", "pb", "pr");
    }

    @Test
    void listaAbertosDepoisSoIsencaoEPorAbrirDepoisPrevistos() {
        Concurso aberto = concurso("a", "A", "ESTADUAL", "PB", false, "INSCRICOES_ABERTAS", ABRIU, FECHA, null, null);
        Concurso soIsencao = concurso("b", "B", "ESTADUAL", "PB", false, "EM_ANDAMENTO", ABRIU, HOJE.minusDays(1),
                null, HOJE.plusDays(2));
        Concurso previsto = concurso("c", "C", "ESTADUAL", "PB", false, "PREVISTO", null, null, null, null);

        assertThat(Ordenacao.lista(List.of(previsto, soIsencao, aberto), HOJE))
                .extracting(Concurso::slug).containsExactly("a", "b", "c");
        assertThat(Ordenacao.isencaoEmPrazo(List.of(previsto, soIsencao, aberto), HOJE))
                .extracting(Concurso::slug).containsExactly("b");
    }
}
