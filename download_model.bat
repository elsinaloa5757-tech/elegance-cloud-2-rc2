@echo off
cd /d "%~dp0"
echo Descargando modelo CLIP...
python scripts\download_model.py
pause
