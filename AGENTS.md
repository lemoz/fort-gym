# Repository Guidelines

## Project Structure & Module Organization
fort-gym centers on the `fort_gym/` package: `bench/agent`, `bench/env`, and `bench/run` implement agents, environment adapters, and orchestration, while `bench/api` hosts the FastAPI service and `bench/cli.py` powers the `fort-gym` entrypoint. Run artifacts persist under `fort_gym/artifacts/<run_id>/`; web assets sit in `web/`, infrastructure in `infra/`, supporting docs in `docs/`, and runnable samples in `examples/`. Tests live in `tests/` and mirror the bench subpackages.

## Build, Test, and Development Commands
Install dependencies with `pip install -e .[dev]` (aliased as `make install`). Use `make api` or `fort-gym api` to serve the backend on port 8000, and `make mock-run` to smoke-test the deterministic backend before touching DFHack. `make test` wraps `pytest -q`; pass filters such as `pytest -k jobs` for focused runs, regenerate protocol bindings with `make proto`, and launch the helper DFHack sandbox via `make df-headless`.

## Coding Style & Naming Conventions
Target Python 3.11, four-space indentation, and type hints on public surfaces. Format with `black` (line length 100) and `isort --profile black`; run `ruff check fort_gym tests` plus `mypy fort_gym` before opening a PR. Modules stay `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`, while CLI commands and Make targets are lowercase with hyphens.

## Testing Guidelines
Add coverage under `tests/` using the `test_<feature>.py` / `test_<behavior>` pattern. Reuse the API client helpers from `tests/test_api_routes.py` and mock-environment utilities in `tests/test_mock_run.py` instead of re-creating fixtures. Tests that write artifacts should rely on pytest temporary paths and assert a success path plus a failure edge when modifying job orchestration or SSE streaming.

## Commit & Pull Request Guidelines
Keep commits imperative and scoped, following the existing prefixes (`dfhack:`, `api:`, `infra:`) and limiting the subject to 72 characters; expand behavior details in the body when needed. PRs must summarize user-visible effects, link issues, list validation (`make test`, mock-run output, screenshots for `web/` changes), and flag infra toggles or secret migrations. Double-check `.env` and generated artifacts stay out of the diff before requesting review.

## Environment & Deployment Tips
Copy `.env.example` to `.env`, then set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` for LLM agents, keeping secrets untracked. For Google Cloud DFHack hosts, rely on `make vm-provision`, `make vm-start`, and `make vm-status`, document non-default service settings, and keep firewall rules focused on ports 5000 and 8000.
