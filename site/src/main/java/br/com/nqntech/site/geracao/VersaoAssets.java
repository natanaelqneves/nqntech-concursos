package br.com.nqntech.site.geracao;

import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * URL de um arquivo de /assets/ com "?v=" + hash do conteúdo. O _headers manda o navegador guardar os assets por
 * um dia; sem a versão na URL, quem já visitou o site recebe o HTML novo com o CSS/JS antigo.
 */
final class VersaoAssets {

    private static final Map<String, String> URLS = new ConcurrentHashMap<>();

    private VersaoAssets() {}

    static String url(String nome) {
        return URLS.computeIfAbsent(nome, VersaoAssets::calcular);
    }

    private static String calcular(String nome) {
        try (InputStream entrada = VersaoAssets.class.getResourceAsStream("/static/assets/" + nome)) {
            if (entrada == null) {
                throw new IllegalArgumentException("asset inexistente: " + nome);
            }
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(entrada.readAllBytes());
            return "/assets/" + nome + "?v=" + HexFormat.of().formatHex(hash, 0, 5);
        } catch (IOException | NoSuchAlgorithmException e) {
            throw new IllegalStateException("não foi possível ler o asset " + nome, e);
        }
    }
}
