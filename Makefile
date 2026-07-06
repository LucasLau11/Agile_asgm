.PHONY: install lint test run format type

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	black --check .

format:
	black .

type:
	mypy src

test:
	pytest --cov=src

run:
	uvicorn agile_ci_demo.app:app --reload
