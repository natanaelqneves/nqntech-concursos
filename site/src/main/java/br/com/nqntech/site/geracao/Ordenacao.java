package br.com.nqntech.site.geracao;

import java.time.LocalDate;
import java.util.Comparator;
import java.util.List;

import br.com.nqntech.site.dados.Concurso;

/** Ordens das listas (seção 4.6 do contexto). */
public final class Ordenacao {

    private Ordenacao() {}

    private static final Comparator<LocalDate> DATA_NULA_POR_ULTIMO = Comparator.nullsLast(Comparator.naturalOrder());

    /** Prova mais próxima primeiro; sem data de prova vai ao fim; desempate pelo fim das inscrições. */
    public static final Comparator<Concurso> POR_PROVA = Comparator
            .comparing(Concurso::dataProva, DATA_NULA_POR_ULTIMO)
            .thenComparing(Concurso::inscricaoFim, DATA_NULA_POR_ULTIMO)
            .thenComparing(Concurso::nomeExibicao, String.CASE_INSENSITIVE_ORDER);

    /** Tela inicial: só inscrições abertas; CNU, depois nacionais, depois estaduais e municipais. */
    public static List<Concurso> telaInicial(List<Concurso> concursos, LocalDate hoje) {
        return concursos.stream()
                .filter(c -> c.inscricoesAbertas(hoje))
                .sorted(Comparator.comparingInt(Ordenacao::grupo).thenComparing(POR_PROVA))
                .toList();
    }

    /** Listas gerais: inscrições abertas, depois só com isenção em prazo ou por abrir, depois previstos. */
    public static List<Concurso> lista(List<Concurso> concursos, LocalDate hoje) {
        return concursos.stream()
                .sorted(Comparator.comparingInt((Concurso c) -> estagio(c, hoje))
                        .thenComparingInt(Ordenacao::grupo)
                        .thenComparing(POR_PROVA))
                .toList();
    }

    /** Pedidos de isenção abertos, prazo mais curto primeiro. */
    public static List<Concurso> isencaoEmPrazo(List<Concurso> concursos, LocalDate hoje) {
        return concursos.stream()
                .filter(c -> c.isencaoEmPrazo(hoje))
                .sorted(Comparator.comparing(Concurso::isencaoFim).thenComparing(POR_PROVA))
                .toList();
    }

    private static int grupo(Concurso c) {
        if (c.unificado()) {
            return 0;
        }
        return c.nacional() ? 1 : 2;
    }

    private static int estagio(Concurso c, LocalDate hoje) {
        if (c.inscricoesAbertas(hoje)) {
            return 0;
        }
        return "PREVISTO".equals(c.situacao()) ? 2 : 1;
    }
}
