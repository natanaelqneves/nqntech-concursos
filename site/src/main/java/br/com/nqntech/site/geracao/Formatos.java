package br.com.nqntech.site.geracao;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.text.DecimalFormat;
import java.text.DecimalFormatSymbols;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Formatação em português usada pelos templates (datas, reais, rótulos de catálogo). */
public final class Formatos {

    public static final ZoneId FUSO = ZoneId.of("America/Sao_Paulo");
    private static final Locale PT_BR = Locale.of("pt", "BR");
    private static final DateTimeFormatter DATA = DateTimeFormatter.ofPattern("dd/MM/yyyy");
    private static final DateTimeFormatter DATA_HORA = DateTimeFormatter.ofPattern("dd/MM/yyyy 'às' HH:mm");

    private static final Map<String, String> SITUACOES = Map.of(
            "PREVISTO", "Previsto",
            "INSCRICOES_ABERTAS", "Inscrições abertas",
            "EM_ANDAMENTO", "Em andamento",
            "ENCERRADO", "Encerrado");
    private static final Map<String, String> NIVEIS = Map.of(
            "FUNDAMENTAL", "Fundamental", "MEDIO", "Médio", "TECNICO", "Técnico", "SUPERIOR", "Superior");
    private static final Map<String, String> ABRANGENCIAS =
            Map.of("NACIONAL", "Nacional", "ESTADUAL", "Estadual", "MUNICIPAL", "Municipal");

    private final LocalDate hoje;
    private final Map<String, String> areas;

    public Formatos(LocalDate hoje, Map<String, String> areas) {
        this.hoje = hoje;
        this.areas = Map.copyOf(areas);
    }

    public LocalDate hoje() {
        return hoje;
    }

    public String data(LocalDate data) {
        return data == null ? "a definir" : DATA.format(data);
    }

    public String dataIso(LocalDate data) {
        return data == null ? "" : data.toString();
    }

    public String dataHora(OffsetDateTime momento) {
        return momento == null ? "" : DATA_HORA.format(momento.atZoneSameInstant(FUSO));
    }

    /** "20/10/2026 a 27/10/2026", "24/01/2027" (um dia só) ou "a definir". */
    public String periodo(LocalDate inicio, LocalDate fim) {
        if (inicio == null && fim == null) {
            return "a definir";
        }
        if (inicio == null || fim == null || inicio.equals(fim)) {
            return data(inicio != null ? inicio : fim);
        }
        return data(inicio) + " a " + data(fim);
    }

    public String reais(BigDecimal valor) {
        if (valor == null) {
            return "";
        }
        DecimalFormat formato = new DecimalFormat("#,##0.00", DecimalFormatSymbols.getInstance(PT_BR));
        return "R$ " + formato.format(valor.setScale(2, RoundingMode.HALF_UP));
    }

    public String faixaReais(BigDecimal minimo, BigDecimal maximo) {
        if (maximo == null) {
            return "";
        }
        if (minimo == null || minimo.compareTo(maximo) == 0) {
            return reais(maximo);
        }
        return reais(minimo) + " a " + reais(maximo);
    }

    public String numero(Integer valor) {
        return valor == null ? "" : String.format(PT_BR, "%,d", valor);
    }

    /** Dias até a data (0 = hoje). Só para o texto estático de fallback; o navegador recalcula. */
    public long diasAte(LocalDate data) {
        return data == null ? -1 : ChronoUnit.DAYS.between(hoje, data);
    }

    public String situacao(String codigo) {
        return SITUACOES.getOrDefault(codigo, codigo);
    }

    public String nivel(String codigo) {
        return NIVEIS.getOrDefault(codigo, codigo);
    }

    public String niveis(List<String> codigos) {
        return String.join(", ", codigos.stream().map(this::nivel).toList());
    }

    public String area(String codigo) {
        return codigo == null ? "" : areas.getOrDefault(codigo, codigo);
    }

    public String abrangencia(String codigo) {
        return ABRANGENCIAS.getOrDefault(codigo, "");
    }

    public String redacao(Boolean temRedacao) {
        if (temRedacao == null) {
            return "Confira o edital";
        }
        return temRedacao ? "Sim" : "Não";
    }
}
