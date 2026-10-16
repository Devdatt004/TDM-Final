"""Post-deploy smoke test (Step 17).

    python scripts/smoke_test.py https://tdm-api.example.org [--token <bearer JWT>]

Exits non-zero if any check fails. Read-only: it never creates data.
Checks: health, auth enforced (anonymous + forged dev headers rejected), the
versioned contract is served, request ids are returned, and - with a token -
an authenticated read works.
"""
import argparse
import sys

import httpx


def run(client, token: str = None) -> list:
    """Return a list of failure messages (empty = healthy)."""
    failures = []

    def check(name, ok):
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            failures.append(name)

    r = client.get("/health")
    check("health endpoint returns 200", r.status_code == 200)
    check("responses carry X-Request-ID", bool(r.headers.get("X-Request-ID")))

    r = client.get("/api/v1/reviews")
    check("anonymous access is rejected (401)", r.status_code == 401)
    r = client.get("/api/v1/reviews", headers={"X-Dev-User": "smoke", "X-Dev-Roles": "admin"})
    check("development auth headers are NOT trusted", r.status_code == 401)
    r = client.get("/openapi.json")
    check("versioned contract is served", r.status_code == 200 and "/api/v1/reviews" in r.json().get("paths", {}))

    if token:
        r = client.get("/api/v1/datasets?limit=1", headers={"Authorization": f"Bearer {token}"})
        check("authenticated read succeeds", r.status_code == 200)
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TDM Platform post-deploy smoke test")
    parser.add_argument("base_url")
    parser.add_argument("--token")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=15.0) as http:
        failed = run(http, args.token)
    sys.exit(1 if failed else 0)
