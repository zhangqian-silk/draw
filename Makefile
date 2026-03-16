SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command

PYTHON ?= python
VENV := .venv
VENV_PYTHON := $(VENV)/Scripts/python.exe
DEPS_STAMP := $(VENV)/.deps-installed

.DEFAULT_GOAL := run

.PHONY: run gui setup install sync test clean help venv

run: $(DEPS_STAMP)
	$$env:PYTHONPATH='src'; & '$(VENV_PYTHON)' -m drawbot gui

gui: run

setup: $(DEPS_STAMP)

install: setup

sync:
	if (Test-Path '$(DEPS_STAMP)') { Remove-Item '$(DEPS_STAMP)' -Force }
	$(MAKE) setup

venv: $(VENV_PYTHON)

$(VENV_PYTHON):
	if (-not (Test-Path '$(VENV_PYTHON)')) { $(PYTHON) -m venv $(VENV) }

$(DEPS_STAMP): pyproject.toml $(VENV_PYTHON)
	& '$(VENV_PYTHON)' -m pip install -e .
	Set-Content -Path '$(DEPS_STAMP)' -Value 'ok'

test: $(DEPS_STAMP)
	$$env:PYTHONPATH='src'; & '$(VENV_PYTHON)' -m unittest discover -s tests -v

clean:
	if (Test-Path '$(VENV)') { Remove-Item '$(VENV)' -Recurse -Force }

help:
	Write-Host "make         -> launch the GUI from source; install dependencies only when needed"
	Write-Host "make run     -> launch the GUI from source; install dependencies only when needed"
	Write-Host "make gui     -> same as make run"
	Write-Host "make setup   -> create .venv and install dependencies if needed"
	Write-Host "make venv    -> create the local virtual environment"
	Write-Host "make install -> same as make setup"
	Write-Host "make sync    -> force reinstall dependencies into .venv"
	Write-Host "make test    -> run unit tests inside .venv"
	Write-Host "make clean   -> remove .venv"
