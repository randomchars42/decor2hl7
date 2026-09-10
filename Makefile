.PHONY: baseline check mypy-report testrun

check:
	python3 -m unittest discover -s tests

baseline:
	python3 scripts/update_reference_baseline.py

mypy-report:
	@{ \
		echo '=== Python ==='; \
		python --version; \
		echo; \
		echo '=== mypy ==='; \
		python -m mypy --version; \
		echo; \
		echo '=== configuration ==='; \
		grep -A100 '^\[tool\.mypy\]' pyproject.toml 2>/dev/null || true; \
		echo; \
		echo '=== mypy output ==='; \
		python -m mypy --show-error-codes --show-column-numbers src tests; \
		status=$$?; \
		echo; \
		echo "=== mypy exit status: $$status ==="; \
		true; \
	} > mypy-output.txt 2>&1
	@echo "Wrote mypy-output.txt"

testrun:
	python3 -m decor2hl7 --root ../test-workplace check-cda-mapping && \
	python3 -m decor2hl7 --root ../test-workplace setup-test --force \
		--scenario tests/fixtures/scenarios/2026.1.2/notaufnahmeregister--60/valid-reference-cases && \
	python3 -m decor2hl7 --root ../test-workplace test-cda-mapping
