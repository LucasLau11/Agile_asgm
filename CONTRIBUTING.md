# Contributing

## Branch strategy
- `main`: always releasable (green CI)
- feature branches: `feat/<short-name>`
- bugfix branches: `fix/<short-name>`

## Workflow
1. Create an Issue (user story or bug) with acceptance criteria (Given/When/Then).
2. Create a branch from `main` and link it to the Issue.
3. Write tests first (TDD encouraged).
4. Commit using conventional style (e.g., `feat: add done endpoint`).
5. Open a PR; CI must be green; request review.
6. Merge via squash; delete branch.

## Local dev
```bash
python -m venv .venv && source .venv/bin/activate
make install
make test
make run
