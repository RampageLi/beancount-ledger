PYTHON := .venv/bin/python
FAVA := .venv/bin/fava
PORT ?= 5001

.PHONY: install build check serve test
install:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt
build:
	$(PYTHON) -m ledger.build_fava
check: build
	.venv/bin/bean-check ledger/main.beancount
serve: check
	$(FAVA) --host 127.0.0.1 --port $(PORT) ledger/main.beancount
test:
	$(PYTHON) -m pytest -q
