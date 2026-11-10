param (
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet("test", "e2e", "visual", "check", "run", "help")]
    [string]$Tarea
)

$ErrorActionPreference = "Stop"
$venvPython = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    $venvPython = "python"
}

switch ($Tarea) {
    "test" {
        Write-Host ">>> Ejecutando suite de pruebas unitarias y de integración..." -ForegroundColor Cyan
        & $venvPython manage.py test
    }
    "e2e" {
        Write-Host ">>> Ejecutando pruebas E2E de presupuesto de clics (Playwright)..." -ForegroundColor Cyan
        & $venvPython -m unittest tests_e2e/test_presupuesto_clics.py
    }
    "visual" {
        Write-Host ">>> Ejecutando matriz visual de dispositivos (Playwright)..." -ForegroundColor Cyan
        & $venvPython scripts/revisar_visual.py
    }
    "check" {
        Write-Host ">>> Comprobando configuración de Django..." -ForegroundColor Cyan
        & $venvPython manage.py check
        Write-Host ">>> Comprobando despliegue seguro (check --deploy)..." -ForegroundColor Cyan
        & $venvPython manage.py check --deploy
    }
    "run" {
        Write-Host ">>> Iniciando servidor de desarrollo en http://127.0.0.1:8000/ ..." -ForegroundColor Cyan
        & $venvPython manage.py runserver
    }
    "help" {
        Write-Host "Uso: .\scripts\tareas.ps1 <test|e2e|visual|check|run>" -ForegroundColor Yellow
    }
}
