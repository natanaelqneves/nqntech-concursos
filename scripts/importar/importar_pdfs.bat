@echo off
REM Importa PDFs de uma pasta para o banco do NqnTech Concursos (Windows).
REM Uso: scripts\importar\importar_pdfs.bat C:\caminho\da\pasta FCC [https://link-oficial]
setlocal
cd /d "%~dp0\..\.."
if "%~2"=="" (
  echo Uso: importar_pdfs.bat PASTA SIGLA_DA_BANCA [LINK_OFICIAL]
  exit /b 2
)
if not exist ".env" (
  echo Falta o arquivo .env na raiz do repositorio. Copie scripts\importar\env.importacao.example para .env e preencha.
  exit /b 2
)
if not exist "coletor\.venv\Scripts\python.exe" (
  echo Preparando o ambiente Python pela primeira vez...
  py -3.13 -m venv coletor\.venv || python -m venv coletor\.venv || exit /b 1
  coletor\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  coletor\.venv\Scripts\python.exe -m pip install --quiet -e coletor || exit /b 1
)
if "%~3"=="" (
  coletor\.venv\Scripts\python.exe -m coletor importar-pdfs "%~1" --banca %2
) else (
  coletor\.venv\Scripts\python.exe -m coletor importar-pdfs "%~1" --banca %2 --link "%~3"
)
