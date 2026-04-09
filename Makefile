# =============================================================
#  Shopping List with Grocy — Developer Makefile
# =============================================================
#
#  make help           Show this help
#  make install        Install all dev dependencies
#  make format         Auto-format Python sources (ruff)
#  make lint           Check formatting + linting (ruff)
#  make test           Run pytest
#  make check          lint + test  (run before committing)
#
#  make version        Show current version
#  make bump-patch     x.y.Z+1  -- bug fix
#  make bump-minor     x.Y+1.0  -- new feature
#  make bump-major     X+1.0.0  -- breaking change
#
#  make release        check -> bump-patch -> tag -> push
#  make release-minor  check -> bump-minor -> tag -> push
#  make release-major  check -> bump-major -> tag -> push

.DEFAULT_GOAL := help

MANIFEST  := custom_components/shopping_list_with_grocy/manifest.json
COMPONENT := custom_components/shopping_list_with_grocy
TESTS     := tests

# ── Helpers ──────────────────────────────────────────────────

_version = $(shell python3 -c "import json; print(json.load(open('$(MANIFEST)'))['version'])")

define _bump
	@python3 scripts/bump_version.py $(MANIFEST) $(1)
endef

# ── Help ─────────────────────────────────────────────────────

.PHONY: help
help:
	@echo ""
	@echo "  Shopping List with Grocy — Developer Commands"
	@echo ""
	@echo "  make install        Install Python dev dependencies"
	@echo "  make format         Auto-format sources (ruff)"
	@echo "  make lint           Check formatting + linting (ruff)"
	@echo "  make test           Run pytest"
	@echo "  make check          lint + test  (run before committing)"
	@echo ""
	@echo "  make version        Show current version"
	@echo "  make bump-patch     x.y.Z+1  -- bug fix"
	@echo "  make bump-minor     x.Y+1.0  -- new feature"
	@echo "  make bump-major     X+1.0.0  -- breaking change"
	@echo ""
	@echo "  make release        check -> bump-patch -> tag -> push"
	@echo "  make release-minor  check -> bump-minor -> tag -> push"
	@echo "  make release-major  check -> bump-major -> tag -> push"
	@echo ""

# ── Dependencies ─────────────────────────────────────────────

.PHONY: install
install:
	@echo "--- Installing Python dev dependencies"
	pip install ruff pytest homeassistant freezegun
	@echo "Done."

# ── Format ───────────────────────────────────────────────────

.PHONY: format
format:
	@echo "--- ruff format"
	ruff format $(COMPONENT) $(TESTS)
	@echo "--- ruff fix"
	ruff check --fix $(COMPONENT) $(TESTS)

# ── Lint ─────────────────────────────────────────────────────

.PHONY: lint
lint:
	@echo "--- ruff check"
	ruff check $(COMPONENT) $(TESTS)
	@echo "--- ruff format check"
	ruff format --check $(COMPONENT) $(TESTS)
	@echo "Lint passed."

# ── Test ─────────────────────────────────────────────────────

.PHONY: test
test:
	@echo "--- pytest"
	# Exit code 5 = no tests collected — treated as success during early dev.
	pytest $(TESTS) -v; status=$$?; [ $$status -eq 5 ] && exit 0 || exit $$status

# ── Check (pre-commit gate) ───────────────────────────────────

.PHONY: check
check: lint test
	@echo "All checks passed."

# ── Version ──────────────────────────────────────────────────

.PHONY: version
version:
	@echo "Current version: $(_version)"

.PHONY: bump-patch
bump-patch:
	$(call _bump,patch)

.PHONY: bump-minor
bump-minor:
	$(call _bump,minor)

.PHONY: bump-major
bump-major:
	$(call _bump,major)

# ── Release ──────────────────────────────────────────────────

.PHONY: release
release: check bump-patch
	$(eval V := $(_version))
	@echo "--- Releasing v$(V)"
	git add $(MANIFEST)
	git commit -m "chore(release): prepare for v$(V)"
	git tag -a "v$(V)" -m "Release v$(V)"
	git push && git push --tags
	@echo "Released v$(V) ✓"

.PHONY: release-minor
release-minor: check bump-minor
	$(eval V := $(_version))
	@echo "--- Releasing v$(V)"
	git add $(MANIFEST)
	git commit -m "chore(release): prepare for v$(V)"
	git tag -a "v$(V)" -m "Release v$(V)"
	git push && git push --tags
	@echo "Released v$(V) ✓"

.PHONY: release-major
release-major: check bump-major
	$(eval V := $(_version))
	@echo "--- Releasing v$(V)"
	git add $(MANIFEST)
	git commit -m "chore(release): prepare for v$(V)"
	git tag -a "v$(V)" -m "Release v$(V)"
	git push && git push --tags
	@echo "Released v$(V) ✓"