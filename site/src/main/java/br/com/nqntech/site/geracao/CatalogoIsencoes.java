package br.com.nqntech.site.geracao;

import java.io.IOException;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.yaml.snakeyaml.LoaderOptions;
import org.yaml.snakeyaml.Yaml;
import org.yaml.snakeyaml.constructor.SafeConstructor;

/** Documentos usuais de cada isenção, lidos de config/isencoes.yml (o resto do texto está no banco). */
public final class CatalogoIsencoes {

    private CatalogoIsencoes() {}

    @SuppressWarnings("unchecked")
    public static Map<String, List<String>> documentos(Path arquivo) throws IOException {
        try (Reader leitor = Files.newBufferedReader(arquivo, StandardCharsets.UTF_8)) {
            Map<String, Object> raiz = new Yaml(new SafeConstructor(new LoaderOptions())).load(leitor);
            Map<String, Map<String, Object>> tipos = (Map<String, Map<String, Object>>) raiz.get("tipos");
            Map<String, List<String>> documentos = new LinkedHashMap<>();
            tipos.forEach((codigo, tipo) -> documentos.put(codigo,
                    ((List<Object>) tipo.getOrDefault("documentos", List.of())).stream().map(String::valueOf).toList()));
            return documentos;
        }
    }
}
