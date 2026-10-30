package br.com.nqntech.site.geracao;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Collection;
import java.util.Map;

/**
 * Serialização JSON mínima para busca.json e JSON-LD. Escapa também {@code <}, {@code >} e {@code &}: o JSON-LD vai
 * dentro de {@code <script>} e um título com {@code </script>} não pode fechar o bloco.
 */
public final class Json {

    private Json() {}

    public static String escrever(Object valor) {
        StringBuilder saida = new StringBuilder();
        escrever(valor, saida);
        return saida.toString();
    }

    private static void escrever(Object valor, StringBuilder saida) {
        switch (valor) {
            case null -> saida.append("null");
            case String texto -> texto(texto, saida);
            case Boolean b -> saida.append(b);
            case Integer i -> saida.append(i);
            case Long l -> saida.append(l);
            case BigDecimal d -> saida.append(d.toPlainString());
            case LocalDate data -> texto(data.toString(), saida);
            case Map<?, ?> mapa -> {
                saida.append('{');
                boolean primeiro = true;
                for (Map.Entry<?, ?> item : mapa.entrySet()) {
                    if (!primeiro) {
                        saida.append(',');
                    }
                    primeiro = false;
                    texto(String.valueOf(item.getKey()), saida);
                    saida.append(':');
                    escrever(item.getValue(), saida);
                }
                saida.append('}');
            }
            case Collection<?> lista -> {
                saida.append('[');
                boolean primeiro = true;
                for (Object item : lista) {
                    if (!primeiro) {
                        saida.append(',');
                    }
                    primeiro = false;
                    escrever(item, saida);
                }
                saida.append(']');
            }
            default -> throw new IllegalArgumentException("tipo sem serialização JSON: " + valor.getClass());
        }
    }

    private static void texto(String texto, StringBuilder saida) {
        saida.append('"');
        for (int i = 0; i < texto.length(); i++) {
            char c = texto.charAt(i);
            switch (c) {
                case '"' -> saida.append("\\\"");
                case '\\' -> saida.append("\\\\");
                case '\n' -> saida.append("\\n");
                case '\r' -> saida.append("\\r");
                case '\t' -> saida.append("\\t");
                case '<' -> saida.append("\\u003c");
                case '>' -> saida.append("\\u003e");
                case '&' -> saida.append("\\u0026");
                case ' ' -> saida.append("\\u2028");
                case ' ' -> saida.append("\\u2029");
                default -> {
                    if (c < 0x20) {
                        saida.append(String.format("\\u%04x", (int) c));
                    } else {
                        saida.append(c);
                    }
                }
            }
        }
        saida.append('"');
    }
}
