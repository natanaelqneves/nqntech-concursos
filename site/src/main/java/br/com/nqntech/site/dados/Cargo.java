package br.com.nqntech.site.dados;

import java.math.BigDecimal;
import java.util.List;

public record Cargo(
        String nome,
        String especialidade,
        String escolaridade,
        Integer vagas,
        boolean cadastroReserva,
        BigDecimal salario,
        String area,
        List<String> disciplinas,
        Boolean temRedacao) {}
