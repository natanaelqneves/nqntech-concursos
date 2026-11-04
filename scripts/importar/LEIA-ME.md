# Importar PDFs manualmente

Para bancas cujo site não permite coleta automática (robots.txt ou bloqueio 403). Você baixa o edital no navegador,
põe numa pasta e roda o script. O PDF passa pelas **mesmas regras** dos baixados pelo robô: limite de tamanho
(`COLETOR_PDF_MAX_MB`, 40 MB), assinatura `%PDF-`, PDF protegido/corrompido/escaneado recusado, triagem de edital
de abertura, extração por regras e IA, classificação, resumo e publicação só se for oportunidade (inscrições
abertas, previsto ou isenção em prazo). O PDF não é copiado: só o texto vai para o banco.

## Uma vez

1. Python 3.13 instalado (https://www.python.org/downloads/, marque "Add to PATH").
2. Copie `scripts/importar/env.importacao.example` para `.env` na raiz do repositório e preencha.

## Cada importação

- Uma pasta **por banca**. Nome do arquivo = título do documento (ex.: `Edital_01-2026_TRT-4.pdf`,
  `Retificacao_01_TRT-4.pdf`).
- Link oficial do concurso: crie `<mesmo nome>.url` ao lado do PDF com uma linha `https://...`, ou passe o link
  no comando (vale para os PDFs sem `.url`). PDFs com o mesmo link viram o mesmo concurso.
- Windows: `scripts\importar\importar_pdfs.bat C:\editais\fcc FCC https://www.concursosfcc.com.br/concursos/trt4`
- Linux/macOS: `scripts/importar/importar_pdfs.sh ~/editais/fcc FCC https://...`
- Siglas: FCC, CESGRANRIO, VUNESP, IBFC, CONSULPLAN, QUADRIX, IDECAN, AOCP, FUNDEP, FUMARC, CPCON, ... ou `OUTRA`.

Rodar de novo com os mesmos arquivos não duplica nada. O site é atualizado na próxima execução do `diario`
(ou rode o workflow `site` no GitHub Actions).
