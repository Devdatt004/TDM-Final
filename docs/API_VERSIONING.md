# API Versioning and Compatibility (Step 15)

## The contract

* Everything clients may rely on lives under **`/api/v1`** and is described by
  [`docs/openapi-v1.json`](openapi-v1.json) (66 paths). `/health` stays unversioned for probes.
* `tests/test_api_contract.py` fails when the live schema differs from that file. To make an intentional
  change, run `python scripts/export_openapi.py` and commit the regenerated file — the diff is the
  contract review.

## Compatibility policy

| Change | Allowed in v1? |
|---|---|
| New endpoint, new optional query parameter, new response field | Yes |
| Removing/renaming a field or endpoint, changing a type or a status code meaning, making an optional input required | No — needs `/api/v2` |
| Tightening validation that rejects previously accepted input | Only for security fixes, announced in release notes |

Clients must ignore unknown response fields.

## Legacy unversioned paths

The routes that predate versioning (`/analyze`, `/generate`, `/mask`, `/runs`, `/relationships`, `/logs`…)
are still served **by the same handler functions** (one business-logic path) but are hidden from OpenAPI
and answer with:

```
Deprecation: true
Sunset: Wed, 30 Jun 2027 00:00:00 GMT
Link: </api/v1/...>; rel="successor-version"
```

The bundled frontend already uses `/api/v1` exclusively. Remove the aliases (one line in `api/main.py`)
after the sunset date.

## Errors

Every error response keeps FastAPI's `detail` and adds a stable envelope:

```json
{"detail": "...", "error": {"code": "not_found", "message": "...", "request_id": "..."}}
```

Codes: `bad_request` 400 · `unauthenticated` 401 · `forbidden` 403 · `not_found` 404 · `conflict` 409 ·
`validation_error` 422 · `rate_limited` 429 · `internal_error` 500 · `unavailable` 503.
Unhandled exceptions return a generic 500; details go to the server log only.
Every response carries `X-Request-ID` (echoed when the client sent a safe value).

## Pagination

List endpoints take `limit` (default 100, **max 500**) and `offset`, and return `total`, `limit`,
`offset` alongside the items: rules, sources, jobs, workflows, datasets (`GET /api/v1/datasets`),
dataset history. Logs and audit are capped at 500.

## Idempotency

Send `Idempotency-Key: <1-128 chars of A-Z a-z 0-9 _ . : ->` on any POST/PATCH under `/api/v1`
(profiling, generation, masking, related generation, uploads, jobs) to make retries safe:

* same caller + key + identical request → the stored response is replayed (`Idempotent-Replayed: true`);
* same key with a different request → 409; a retry while the first is still running → 409;
* only successful (2xx) responses are stored; keys expire after 24 hours; keys are scoped per caller.
