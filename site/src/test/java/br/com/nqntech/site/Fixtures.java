package br.com.nqntech.site;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;

import br.com.nqntech.site.dados.Cargo;
import br.com.nqntech.site.dados.Concurso;
import br.com.nqntech.site.dados.Evento;
import br.com.nqntech.site.dados.IsencaoPrevista;

/** Concursos de teste montados em memória. */
public final class Fixtures {

    private Fixtures() {}

    public static Concurso concurso(String slug, String orgao, String abrangencia, String uf, boolean cnu,
            String situacao, LocalDate inicio, LocalDate fim, LocalDate prova, LocalDate isencaoFim) {
        return new Concurso(1, slug, "Concurso " + orgao, orgao, "FGV", situacao, abrangencia, uf, null, null, cnu,
                inicio, fim, prova, new BigDecimal("120.00"), new BigDecimal("120.00"), 50,
                new BigDecimal("7526.14"), List.of("SUPERIOR"), List.of("JURIDICA", "TI"), isencaoFim != null,
                isencaoFim == null ? null : isencaoFim.minusDays(7), isencaoFim, "Resumo de " + orgao + ".",
                "https://conhecimento.fgv.br/concursos/" + slug, "https://portal.conhecimento.fgv.br/inscricao",
                "https://conhecimento.fgv.br/edital.pdf", OffsetDateTime.of(2026, 10, 29, 12, 0, 0, 0, ZoneOffset.UTC),
                List.of(new Cargo("Analista", "TI – Desenvolvimento", "SUPERIOR", 10, false,
                        new BigDecimal("7526.14"), "TI", List.of("Língua Portuguesa", "Banco de Dados"), true)),
                List.of(new Evento("Inscrições", inicio, fim), new Evento("Resultado final", null, null)),
                isencaoFim == null ? List.of() : List.of(new IsencaoPrevista("CADUNICO", null)));
    }
}
