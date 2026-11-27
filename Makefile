# xiaomi-ai-key-linux
#
# Override the Python interpreter with `make test PY=/usr/bin/python3`.
PY ?= python3
VERSION := $(shell grep -m1 '^__version__' bin/xiaomi-key-daemon.py | cut -d'"' -f2)
DIST_DIR := dist
TARBALL := $(DIST_DIR)/xiaomi-ai-key-linux-$(VERSION).tar.gz

.DEFAULT_GOAL := help
.PHONY: help test lint check install uninstall remap unremap dist clean

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

test:  ## Run the unit test suite (no hardware needed)
	$(PY) -m unittest discover -s tests -t . -v

lint:  ## Shell syntax + shellcheck + Python byte-compile
	@set -e; for script in scripts/*.sh; do \
		echo "bash -n $$script"; bash -n "$$script"; \
		if command -v shellcheck >/dev/null 2>&1; then shellcheck -x "$$script"; fi; \
	done
	$(PY) -m compileall -q bin tests

check:  ## Diagnose the installation on this machine
	$(PY) bin/xiaomi-key-daemon.py --check

install:  ## Install the daemon, udev rule and user service
	./scripts/install.sh

uninstall:  ## Remove everything (keeps action.conf; add PURGE=1 to drop it)
	./scripts/uninstall.sh $(if $(PURGE),--purge,)

remap:  ## Alternative: remap the key to F19 for the desktop shortcut editor
	./scripts/remap-key.sh

unremap:  ## Undo the F19 remap
	./scripts/remap-key.sh --remove

dist:  $(TARBALL)  ## Build a source tarball

$(TARBALL):
	@mkdir -p $(DIST_DIR)
	@if git rev-parse --git-dir >/dev/null 2>&1; then \
		git archive --format=tar.gz --prefix=xiaomi-ai-key-linux-$(VERSION)/ \
			-o $(TARBALL) HEAD; \
	else \
		tar czf $(TARBALL) --exclude='./$(DIST_DIR)' --exclude='./.git' \
			--exclude='__pycache__' --transform 's,^\.,xiaomi-ai-key-linux-$(VERSION),' . ; \
	fi
	@echo "built $(TARBALL)"

clean:  ## Remove build/cache artefacts
	rm -rf $(DIST_DIR)
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
