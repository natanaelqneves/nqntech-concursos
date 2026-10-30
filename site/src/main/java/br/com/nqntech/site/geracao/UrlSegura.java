package br.com.nqntech.site.geracao;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/**
 * Links que vêm das fontes (edital, inscrição) são dados não confiáveis: só http(s) absoluto vira link. Isso evita
 * {@code javascript:} e {@code data:} no href, que o escape de HTML do Thymeleaf não impede.
 */
public final class UrlSegura {

    private UrlSegura() {}

    public static String http(String url) {
        if (url == null || url.isBlank() || url.length() > 2000) {
            return null;
        }
        try {
            URI uri = new URI(url.strip());
            String esquema = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
            if (!(esquema.equals("https") || esquema.equals("http")) || uri.getHost() == null) {
                return null;
            }
            return uri.toString();
        } catch (URISyntaxException e) {
            return null;
        }
    }
}
