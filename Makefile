.PHONY: mypy-report

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
	} > mypy-output.txt 2>&1
	@echo "Wrote mypy-output.txt"
