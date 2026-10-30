package br.com.nqntech.site.geracao;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import br.com.nqntech.site.dados.Concurso;

/** busca.json: índice enxuto dos concursos publicados, para filtros e buscas no navegador (sem servidor). */
public final class BuscaJson {

    private BuscaJson() {}

    public static String gerar(List<Concurso> concursos, Formatos fmt) {
        List<Map<String, Object>> itens = concursos.stream().map(c -> {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("url", "/concurso/" + c.slug() + "/");
            item.put("nome", c.nomeExibicao());
            item.put("situacao", c.situacao());
            item.put("abrangencia", c.abrangencia());
            item.put("uf", c.uf());
            item.put("municipio", c.municipio());
            item.put("areas", c.areas());
            item.put("niveis", c.escolaridades());
            item.put("vagas", c.totalVagas());
            item.put("salario", c.salarioMax());
            item.put("inscricaoFim", c.inscricaoFim());
            item.put("prova", c.dataProva());
            item.put("isencaoFim", c.isencaoFim());
            item.put("isencoes", c.isencoes().stream().map(i -> i.codigo()).toList());
            item.put("cnu", c.unificado());
            return item;
        }).toList();
        Map<String, Object> raiz = new LinkedHashMap<>();
        raiz.put("geradoEm", fmt.hoje());
        raiz.put("concursos", itens);
        return Json.escrever(raiz);
    }
}
