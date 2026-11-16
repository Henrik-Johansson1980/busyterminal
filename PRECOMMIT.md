# Pre-commit gate

Never commit or push with a failing test, a lint, type or coverage error, an
unresolved formatting diff, a known vulnerability, or a leaked secret.

## Setup

```sh
python3 -m pip install --user -r requirements-dev.txt
```

Also needed, outside pip: [uv](https://docs.astral.sh/uv/) (runs pip-audit)
and [gitleaks](https://github.com/gitleaks/gitleaks).

## Run it

```sh
./check.sh
```

It runs, in this order:

| Step | Command | Why here |
| --- | --- | --- |
| Auto-fix | `ruff check --fix .` | Applies safe fixes (imports, pyupgrade). Its output is not always formatter-clean, so it runs first. |
| Format | `ruff format .` | Formats whatever the fixer left. |
| Lint | `ruff check .` | Anything left needs a manual fix. |
| Format check | `ruff format --check .` | Confirms no formatting diff remains. |
| Types | `mypy` | Strict mode, on `busy.py` and the tests. |
| Tests and coverage | `pytest -q` | Unit tests plus end-to-end tests in a pseudo-terminal. Fails below 100% line and branch coverage, including code run in child processes. |
| Advisories | `uvx pip-audit -r requirements-dev.txt` | Checks the locked dev dependencies for known vulnerabilities. |
| Secret scan | `git add -A` then `gitleaks git . --staged` | Scans the staged diff, so a leak is caught before it is committed. |

## Rules

1. Run the full gate, fix everything, then **re-run the whole gate from the top**.
   A fix in one step can break an earlier one; a green step from before a fix
   proves nothing.
2. If something cannot be fixed now, stop and report which step fails and why.
   Never commit partially fixed work.
3. Weakening a gate is not a fix: no deleting or skipping tests, no `# noqa`,
   `# type: ignore` or `# pragma: no cover` to hide a finding, no lowering
   `fail_under`, no widening the gitleaks allowlist.

## Dependencies

`busy.py` has no runtime dependencies. The dev tools are listed in
`requirements-dev.in` and locked, with hashes, in `requirements-dev.txt`.
After editing the `.in` file, regenerate the lock:

```sh
uv pip compile --python-version 3.10 --generate-hashes requirements-dev.in -o requirements-dev.txt
```

## Known exception

Coverage treats `if sys.platform` checks as partial branches
(`partial_branches` in `pyproject.toml`), because only one side can run on
any one machine. The Windows side is not exercised by the tests.
