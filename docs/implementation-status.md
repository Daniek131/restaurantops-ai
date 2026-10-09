# Implementation evidence

## Initial audit

The inputs were project instructions, five resume variants, and pasted LinkedIn project descriptions. No RestaurantOps source directory, data export, earlier test report, or deployment evidence was supplied. The connected GitHub account returned no accessible repositories. Original code quality, dead code, duplication, dependencies, and historical implementation cannot be rated from those inputs.

The local repository was initialized before this implementation was written. This is newly authored code, prepared with coding assistance in October 2026. It has no fabricated historical commits.

## Evidence by claim

| Resume or LinkedIn claim | Current source supports | Still needed |
| --- | --- | --- |
| Relational inventory and recipe architecture | Tables, foreign keys, recipe mapping, supplier references | Prior-source provenance if describing the earlier MVP |
| POS sales to ingredient depletion | A normalized event API and atomic depletion | Actual Heartland/POS authentication, ID mapping, and export reconciliation |
| COGS and usage | Cost snapshots, movement ledger, SQL aggregates | Actual purchasing-cost and waste/yield policies |
| Demand forecasts | Moving-average baseline and chronological evaluation | Real operating data, seasonal comparison, measured accuracy |
| Anomaly detection | Usage-spike and stock-count rules | Validated thresholds and known incident labels |
| Redis-backed Celery workers | Worker task and broker/scheduler configuration | Live Redis delivery and deployment verification |
| Controlled LLM interface | Fixed read-only tools and Responses adapter | A live model/provider integration run |
| MVP completed Feb–Sep 2026 | A runnable software foundation authored now | Earlier source or other evidence of that historical version |
| Preparing restaurant pilot | A reasonable next stage | A real venue's approved data and integration testing |

The repository's implemented features do not retroactively verify earlier dates, authorship, or deployments. PyTorch is not used here; this repository does not substantiate a trained ML model.

## Verification

Local behavior tests use SQLite and include rollback after a partially attempted multi-ingredient sale, duplicate and conflicting events, cost snapshots, invalid inputs, API-token checks, forecast values, chronological evaluation, variance flags, an hourly check retry, and an eager Celery task. The assistant test uses fake provider output and verifies that write tools and arbitrary arguments are rejected.

See `verification.json` for the final measured results. PostgreSQL, Docker, live Redis worker delivery, and a live OpenAI call must be checked separately. These are not implied by a passing SQLite or mocked-provider test.

## File privacy

No actual credentials, private restaurant records, POS exports, or `.env` files are committed. Demo suppliers and transactions are intentionally synthetic. The project does not need an actual API key to run the core scenario.
