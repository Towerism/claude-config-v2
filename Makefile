# Short commands for development and for tools/cfg.py. The raw commands still work.
#   make setup | test | lint
#   make plan|deploy|status|rollback [HOST=personal|work] [TARGET=dir]
#   make deploy applies only with YES=1; FORCE=1 overwrites conflicts (backed up).
PY ?= python3
VENV := .venv
CFG := $(PY) -I tools/cfg.py

# Only values typed on the make command line count, never exported environment variables
# (HOST is set by some shells), and YES/FORCE must be exactly 1.
cmdline = $(if $(filter command line,$(origin $(1))),$($(1)))
HOST_ARG = $(call cmdline,HOST)
TARGET_ARG = $(call cmdline,TARGET)
$(if $(findstring ',$(HOST_ARG)$(TARGET_ARG)),$(error HOST and TARGET must not contain a single quote))
CFG_ARGS = $(if $(HOST_ARG),--host '$(HOST_ARG)') $(if $(TARGET_ARG),--target '$(TARGET_ARG)')

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
	@$(CFG) deploy $(CFG_ARGS) $(if $(filter 1,$(call cmdline,YES)),--yes) $(if $(filter 1,$(call cmdline,FORCE)),--force)
