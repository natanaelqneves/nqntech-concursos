# Instruções para o Claude — NqnTech Concursos

Este arquivo substitui as Instruções do Projeto no Claude. O repositório é a **única** fonte de contexto:
não há cópias em outro lugar.

## Antes de qualquer resposta ou trabalho
Leia `docs/CONTEXTO_PROJETO.md` (fonte da verdade) e, se for trabalhar numa fase, o prompt dela em
`docs/GUIA_PROMPTS.md` e as pendências em `docs/PENDENCIAS.md`. Siga arquitetura, modelo de dados, estrutura
de pastas, convenções e regras de segurança/privacidade do contexto. Se algo pedido contrariar o contexto,
avise antes de fazer.

## Quem pede
Desenvolvedor Java/Spring Boot e PostgreSQL, com conhecimento de Python. Domina integração, conexão com banco,
variáveis de ambiente e configuração: não explique o básico.

## Projeto
Site público e gratuito de concursos públicos do Brasil (todas as áreas, níveis e estados; previstos, abertos e
encerrados), com resumo próprio de cada concurso, informações sobre isenções de taxa e alertas por e-mail com
cadastro só de nome, e-mail e filtro. Coleta em Python e geração do site estático em Java/Thymeleaf no GitHub
Actions; PostgreSQL no Neon; site na Cloudflare (Workers, assets estáticos, deploy só pelo GitHub Actions).
Repositório público: https://github.com/natanaelqneves/nqntech-concursos

O repositório `natanaelqneves/radar-ti` é outro projeto: só pode ser lido como referência, nunca alterado.

## Padrão de código
- Nível profissional, como em produção: arquitetura limpa, SOLID onde fizer sentido, tratamento de erros
  explícito, logs úteis, type hints no Python, records/dataclasses imutáveis quando possível.
- Comente apenas o que não for trivial (regras de negócio, decisões não óbvias, regex/heurísticas, pontos de
  segurança). Sem comentários que repetem o código; prefira bons nomes.
- Javadoc/docstring só em interfaces e contratos públicos entre módulos.
- Testes automatizados para toda lógica relevante, sem acessar a internet nos testes.
- Nunca coloque segredo real no código (o repositório é público); use GitHub Secrets e mantenha o
  `.env.example` atualizado.
- Use versões estáveis atuais das bibliotecas e confira na web o que pode ter mudado.

## Como trabalhar
- Faça o trabalho completo da fase pedida: crie os arquivos no repositório, rode os testes no GitHub Actions,
  corrija até ficar verde e só deixe ao usuário o que depende das contas dele, com instruções em
  `docs/PENDENCIAS.md`.
- Explicações curtas e diretas: só decisões de projeto relevantes e trade-offs.
- Respostas em português.

## Ao final de cada fase
1. O que foi entregue e como verificar (workflow/página e resultado esperado).
2. Pontos de segurança e privacidade da fase (só os relevantes).
3. A seção "Estado atual" do `docs/CONTEXTO_PROJETO.md` atualizada **no repositório** (não há cópia a sincronizar).
