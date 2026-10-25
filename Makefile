# Short commands for development and for tools/cfg.py. The raw commands still work.
#   make setup | test | lint
#   make plan|deploy|status|rollback [HOST=personal|work] [TARGET=dir]
#   make deploy applies only with YES=1; FORCE=1 overwrites conflicts (backed up).
PY ?= python3
VENV := .venv
CFG := $(PY) -I tools/cfg.py
CFG_ARGS = $(if $(HOST),--host '$(HOST)') $(if $(TARGET),--target '$(TARGET)')

.PHONY: setup test lint plan deploy status rollback

define SETUP
$(PY) -m venv $(VENV)
$(VENV)/bin/pip install -r requirements-dev.txt
endef

setup: ; $(SETUP)

$(VENV)/bin/python: ; $(SETUP)

test: $(VENV)/bin/python
	$(VENV)/bin/python -I -m pytest

lint: $(VENV)/bin/python
	$(VENV)/bin/ruff check

plan status rollback:
	@$(CFG) $@ $(CFG_ARGS)

deploy:
	@$(CFG) deploy $(CFG_ARGS) $(if $(YES),--yes) $(if $(FORCE),--force)
