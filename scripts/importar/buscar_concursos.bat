@echo off
REM Sugere concursos abertos das bancas sem coleta automatica (Gemini + Busca Google). Nao grava nada no banco.
REM Uso: scripts\importar\buscar_concursos.bat            (todas as bancas)
REM      scripts\importar\buscar_concursos.bat FCC VUNESP (so estas)
setlocal
cd /d "%~dp0\..\.."
if not exist ".env" (
  echo Falta o .env na raiz do repositorio ^(basta a linha GEMINI_API_KEY=...^).
  exit /b 2
)
if not exist "coletor\.venv\Scripts\python.exe" (
  echo Preparando o ambiente Python pela primeira vez...
  py -3.13 -m venv coletor\.venv || python -m venv coletor\.venv || exit /b 1
  coletor\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  coletor\.venv\Scripts\python.exe -m pip install --quiet -e coletor || exit /b 1
)
if "%~1"=="" (
  coletor\.venv\Scripts\python.exe -m coletor buscar-concursos
) else (
  coletor\.venv\Scripts\python.exe -m coletor buscar-concursos --bancas %*
)
