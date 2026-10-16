# DataReconcile AI

> **Match transaction exports, resolve exceptions, and produce auditable reports.**

Part of **ForgeWorks**, a collection of five complementary API services for software engineering and operations.

## What the product does

DataReconcile AI compares bounded transaction exports using exact, explainable matching rules. It records matches and exceptions so reviewers can investigate differences and produce an audit-friendly reconciliation result.

**Who uses it:** Finance operations and data reconciliation teams.

## Capabilities and outputs

| Capability | Input / action | Output |
| --- | --- | --- |
| Source intake | Authorized development-scoped CSV artifacts | Validated imports with integrity checks |
| Transaction matching | Rows in the same currency, amounts in integer minor units | Deterministic one-to-one matches |
| Exception management | Unmatched rows and authorized review decisions | Traceable exception resolution |
| Reporting | Reconciliation run and reviewed outcomes | Immutable reporting records within the scoped implementation |

## Example workflow

1. Import supported CSV exports and validate source integrity.
2. Match eligible transactions using deterministic same-currency rules.
3. Review unmatched transactions as exceptions and record resolutions.
4. Produce the immutable reconciliation report for follow-up and audit.

**What a team gets:** explicit inputs, a repeatable processing path, and inspectable outputs for review. CSV artifacts and immutable reporting are governed by the service's documented scope and PostgreSQL controls.

## Technical design

- **API:** Python service with versioned REST/OpenAPI contracts and structured error handling.
- **Data:** PostgreSQL domain adapter and tenant-scoped data access controls.
- **Auth:** explicit development authentication for local use; never reuse local keys or sample identities on hosted infrastructure.
- **Verification:** automated code tests, contract checks, and scoped evidence documents. Their meaning is limited to the scenarios they exercised.

## Run locally

Install Python and the runtime/test dependencies from the repository root:

```bash
python -m pip install --require-hashes -r requirements-runtime.lock
python -m pip install -e 'apps/api[test]' -r scripts/requirements-verification.txt
export APP_ENV=development AUTH_MODE=development
export AUTH_ISSUER=https://issuer.synthetic.invalid AUTH_AUDIENCE=forgeworks-api
export DEV_AUTH_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export ARTIFACT_SIGNING_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python scripts/development_token.py
RECONCILE_SEED_FIXTURE=1 PYTHONPATH=apps/api/src uvicorn datareconcile_ai.main:app --reload
```

The generated token is short-lived and is only for local development with synthetic data. To run the test suite, use `python -W error -m pytest tests` with the same explicit development environment.

## API and technical references

- [Product scope](docs/product/PRODUCT_SCOPE.md)
- [Architecture](docs/architecture/)
- [OpenAPI contract](contracts/openapi.yaml) and [event schemas](contracts/events.schema.json)
- [Verification evidence](docs/verification/CURRENT_GATE_EVIDENCE.md)
- [Release verification runbook](ops/runbooks/RUNTIME_RELEASE_VERIFICATION.md)
- [One-app / five-services design](docs/platform/ONE_APP_FIVE_SERVICES.md)

## ForgeWorks service family

- [APIShield Agent](https://github.com/ivan-agentic-labs/forgeworks-apishield-agent) · API contract-change analysis
- [AccessFix AI](https://github.com/ivan-agentic-labs/forgeworks-accessfix-ai) · accessibility review
- [SpecForge AI](https://github.com/ivan-agentic-labs/forgeworks-specforge-ai) · requirements-to-API contracts
- [AgentTest Lab](https://github.com/ivan-agentic-labs/forgeworks-agenttest-lab) · AI agent evaluation
- [DataReconcile AI](https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai) · reconciliation and exceptions

The services have separate repositories and explicit interfaces. A single customer-facing ForgeWorks portal is an architectural direction, not a claim of independently verified live integration.

## Usage boundary

Matching is intentionally one-to-one and same-currency; this service does not move money, execute bank settlement, or claim verified reconciliation of live customer financial records. Consult the linked evidence register and runbook before claiming customer-level or production acceptance.
