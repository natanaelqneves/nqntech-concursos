package br.com.nqntech.site.geracao;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

class FormatosTest {

    private final Formatos fmt = new Formatos(LocalDate.of(2026, 10, 25), Map.of("TI", "Tecnologia da informação"));

    @Test
    void reaisEmPortugues() {
        assertThat(fmt.reais(new BigDecimal("7526.14"))).isEqualTo("R$ 7.526,14");
        assertThat(fmt.reais(new BigDecimal("120"))).isEqualTo("R$ 120,00");
        assertThat(fmt.faixaReais(new BigDecimal("70"), new BigDecimal("90"))).isEqualTo("R$ 70,00 a R$ 90,00");
        assertThat(fmt.faixaReais(new BigDecimal("90.00"), new BigDecimal("90"))).isEqualTo("R$ 90,00");
    }

    @Test
    void datasEPeriodos() {
        LocalDate inicio = LocalDate.of(2026, 10, 20);
        assertThat(fmt.periodo(inicio, LocalDate.of(2026, 10, 27))).isEqualTo("20/10/2026 a 27/10/2026");
        assertThat(fmt.periodo(inicio, inicio)).isEqualTo("20/10/2026");
        assertThat(fmt.periodo(null, null)).isEqualTo("a definir");
        assertThat(fmt.diasAte(LocalDate.of(2026, 10, 27))).isEqualTo(2);
    }

    @Test
    void rotulos() {
        assertThat(fmt.numero(1200)).isEqualTo("1.200");
        assertThat(fmt.niveis(List.of("MEDIO", "SUPERIOR"))).isEqualTo("Médio, Superior");
        assertThat(fmt.area("TI")).isEqualTo("Tecnologia da informação");
        assertThat(fmt.redacao(null)).isEqualTo("Confira o edital");
    }
}
