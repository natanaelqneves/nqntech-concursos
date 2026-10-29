# Sobe o ambiente de dev (Postgres + Flyway + Mailpit), mostra o status e roda a verificacao.
# Uso (PowerShell, na raiz do repositorio):  .\scripts\subir.ps1 [-Email voce@exemplo.com]
# Se o Windows bloquear scripts: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
param([string]$Email)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$python = $null
foreach ($candidato in @('python', 'py', 'python3')) {
    if (Get-Command $candidato -ErrorAction SilentlyContinue) { $python = $candidato; break }
}
if (-not $python) { Write-Error 'Python 3 nao encontrado. Instale o Python 3.12+ e rode de novo.'; exit 1 }

docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Error 'Docker nao esta rodando. Abra o Docker Desktop e rode de novo.'; exit 1 }

if ($Email) { & $python scripts/criar_env.py --email $Email } else { & $python scripts/criar_env.py }
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host 'Subindo conteineres...'
docker compose up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python scripts/verificar_ambiente.py --aguardar 180
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host 'Logs do flyway (ultimas 30 linhas):'
    docker compose logs --tail 30 flyway
    exit 1
}

Write-Host ''
docker compose ps --all
