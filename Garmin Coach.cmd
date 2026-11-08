@echo off
rem Doppio clic: apre Garmin Coach nel browser.
rem
rem Non installa niente e non contatta nessuno. Avvia un server che ascolta solo
rem su 127.0.0.1, cioe su questo computer, e apre la pagina. Per chiuderlo si
rem chiude questa finestra.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo L'ambiente Python non c'e ancora in .venv
  echo Si ricrea con:  python -m venv .venv  e poi  .venv\Scripts\pip install -e .[dev]
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -m garmin_coach app --port 8766
if errorlevel 1 pause
