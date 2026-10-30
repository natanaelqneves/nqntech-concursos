package br.com.nqntech.site.geracao;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

class JsonTest {

    @Test
    void escapaOQueFecharia_oBlocoScript() {
        assertThat(Json.escrever("</script><script>alert(1)</script>"))
                .isEqualTo("\"\\u003c/script\\u003e\\u003cscript\\u003ealert(1)\\u003c/script\\u003e\"")
                .doesNotContain("<", ">");
    }

    @Test
    void escapaAspasBarrasEControles() {
        assertThat(Json.escrever("a\"b\\c\nd\u0001")).isEqualTo("\"a\\\"b\\\\c\\nd\\u0001\"");
    }

    @Test
    void serializaEstruturas() {
        Map<String, Object> mapa = new LinkedHashMap<>();
        mapa.put("n", 1);
        mapa.put("v", new BigDecimal("7526.14"));
        mapa.put("d", LocalDate.of(2026, 11, 18));
        mapa.put("l", List.of("TI", "SAUDE"));
        mapa.put("x", null);
        mapa.put("b", true);
        assertThat(Json.escrever(mapa))
                .isEqualTo("{\"n\":1,\"v\":7526.14,\"d\":\"2026-11-18\",\"l\":[\"TI\",\"SAUDE\"],\"x\":null,\"b\":true}");
    }
}
