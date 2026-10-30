package br.com.nqntech.site.geracao;

import java.time.LocalDate;
import java.util.List;

public final class Sitemap {

    private Sitemap() {}

    public static String gerar(String urlBase, List<String> urls, LocalDate hoje) {
        StringBuilder xml = new StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
                .append("<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n");
        for (String url : urls) {
            xml.append("  <url><loc>").append(escapar(urlBase + url)).append("</loc><lastmod>").append(hoje)
                    .append("</lastmod></url>\n");
        }
        return xml.append("</urlset>\n").toString();
    }

    private static String escapar(String texto) {
        return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }
}
