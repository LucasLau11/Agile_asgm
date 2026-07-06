# Agile Demo: API + Testing + CI

This repository is a **teaching project** that shows how Agile development,
automated testing, and CI fit together.

We use a tiny FastAPI app that manages todo items:

- **Product side:** user stories, acceptance criteria, BDD-style Gherkin scenarios.
- **Technical side:** unit tests, acceptance tests, BDD tests, property-based tests.
- **Process side:** CI pipeline running lint, type checks and tests.

---

## 1. Project structure

```text
.
├── src/
│   └── agile_ci_demo/
│       ├── __init__.py
│       └── app.py          # FastAPI app (business logic)
├── tests/
│   ├── test_acceptance_items.py  # Acceptance + BDD tests (this is the main demo)
│   └── features/
│       └── items.feature         # Gherkin BDD feature(s)
├── .github/
│   └── workflows/
│       └── ci.yml          # CI pipeline: lint, type check, tests, coverage
├── pyproject.toml          # Dependencies & tool config
├── Makefile                # Shortcuts: install, lint, test, etc.
└── README.md               # You're here
