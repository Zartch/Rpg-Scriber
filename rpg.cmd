@echo off
setlocal
cd /d "%~dp0"

if not exist ".\.venv\Scripts\python.exe" (
  echo [rpg] No se encontro .venv\Scripts\python.exe en este proyecto. 1>&2
  echo [rpg] Crea el entorno virtual e instala dependencias antes de ejecutar. 1>&2
  exit /b 1
)

".\.venv\Scripts\python.exe" -m rpg_scribe.main %*
