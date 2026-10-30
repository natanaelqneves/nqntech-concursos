package br.com.nqntech.site.geracao;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class UrlSeguraTest {

    @ParameterizedTest
    @ValueSource(strings = {"https://conhecimento.fgv.br/concursos/tjpb26", "http://www.ibam-concursos.org.br/x.pdf"})
    void aceitaHttpAbsoluto(String url) {
        assertThat(UrlSegura.http(url)).isEqualTo(url);
    }

    @ParameterizedTest
    @ValueSource(strings = {"javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,oi", "/relativo",
            "ftp://x.com/a", "https://", "   ", "http://exa mple.com"})
    void recusaOResto(String url) {
        assertThat(UrlSegura.http(url)).isNull();
    }
}
