@echo off
title Meeting Assistant
cd /d "%~dp0"

rem Путь к activate.bat вашего conda-окружения (нужен для CUDA DLL: cublas64_12.dll и т.д.).
rem Замените на свой путь; при отсутствии файла будет использован pythonw из PATH.
set "CONDA_ACTIVATE=C:\Users\Wiz\miniconda3\Scripts\activate.bat"
if exist "%CONDA_ACTIVATE%" (
    call "%CONDA_ACTIVATE%" base
)

start "" pythonw src\main.py