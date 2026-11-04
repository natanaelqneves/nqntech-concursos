package br.com.nqntech.site.dados;

import static br.com.nqntech.site.Fixtures.concurso;
import static org.assertj.core.api.Assertions.assertThat;

import java.time.LocalDate;

import org.junit.jupiter.api.Test;

class ConcursoTest {

    private static final LocalDate HOJE = LocalDate.of(2026, 10, 25);

    @Test
    void comInscricoesAbertasDestacaOFimDasInscricoes() {
        Concurso c = concurso("a", "A", "ESTADUAL", "PB", false, "INSCRICOES_ABERTAS",
                HOJE.minusDays(2), HOJE.plusDays(9), HOJE.plusDays(60), null);
        assertThat(c.marco(HOJE)).isEqualTo(new Concurso.Marco("Inscrições até", HOJE.plusDays(9)));
    }

    @Test
    void inscricoesQueAindaVaoAbrirDestacamOInicio() {
        Concurso c = concurso("b", "B", "ESTADUAL", "PB", false, "INSCRICOES_ABERTAS",
                HOJE.plusDays(3), HOJE.plusDays(30), HOJE.plusDays(60), null);
        assertThat(c.marco(HOJE)).isEqualTo(new Concurso.Marco("Inscrições a partir de", HOJE.plusDays(3)));
    }

    @Test
    void semInscricaoFuturaDestacaAProvaESemDatasFicaADefinir() {
        Concurso comProva = concurso("c", "C", "ESTADUAL", "PB", false, "PREVISTO", null, null, HOJE.plusDays(40), null);
        assertThat(comProva.marco(HOJE)).isEqualTo(new Concurso.Marco("Prova em", HOJE.plusDays(40)));

        Concurso semDatas = concurso("d", "D", "ESTADUAL", "PB", false, "PREVISTO", null, null, null, null);
        assertThat(semDatas.marco(HOJE).data()).isNull();
    }
}
