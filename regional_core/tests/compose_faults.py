"""Fault-tolerance checks executed inside the Compose network."""

from __future__ import annotations

import json
import sys
import time
import urllib.request


BASE_URL = "http://127.0.0.1:8080"


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE_URL + path, timeout=5) as response:
        return json.load(response)


def post_qc(prefix: str) -> str:
    suffix = str(int(time.time() * 1_000_000))
    request_id = f"{prefix}-{suffix}"
    qc = {
        "schema_version": "mwvn-approved-qc/v1",
        "request_id": request_id,
        "qc_id": f"qc-{request_id}",
        "claim_hash": "7a9e667f3b8d94b7c0c5f590a8a2c26d662f8e86d73e631cdd8c39f24f40a9b4",
        "window_start": "2026-09-10T07:00:00Z",
        "window_end": "2026-09-10T07:05:00Z",
        "region": "med-east-demo",
        "classification": "AUTHENTIC",
        "policy_version": "demo-policy-v1",
        "evidence_refs": [f"synthetic-vdes-{request_id}"],
        "conflict_links": [],
    }
    request = urllib.request.Request(
        BASE_URL + "/api/v1/qcs",
        data=json.dumps(qc).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        admission = json.load(response)
    if admission["status"]["state"] != "pending":
        raise AssertionError(f"unexpected admission: {admission}")
    return request_id


def ledger_heights() -> dict[str, int]:
    ledgers = get("/api/v1/ledgers")["ledgers"]
    return {name: len(records) for name, records in ledgers.items() if isinstance(records, list)}


def one_down() -> None:
    before = ledger_heights()
    request_id = post_qc("one-down")
    deadline = time.monotonic() + 20
    status = None
    while time.monotonic() < deadline:
        status = get(f"/api/v1/qcs/{request_id}")
        if status["state"] == "committed":
            break
        time.sleep(0.1)
    if not status or status["state"] != "committed":
        raise AssertionError(f"3-of-4 request did not commit: {status}")
    deadline = time.monotonic() + 5
    after = ledger_heights()
    while time.monotonic() < deadline and any(after.get(f"validator-{node}") != before.get(f"validator-{node}", 0) + 1 for node in (1, 2, 3)):
        time.sleep(0.1)
        after = ledger_heights()
    for node in (1, 2, 3):
        name = f"validator-{node}"
        if after.get(name) != before.get(name, 0) + 1:
            raise AssertionError(f"{name} did not append with one engine down: before={before} after={after}")
    if after.get("validator-4") != before.get("validator-4"):
        raise AssertionError(f"stopped validator unexpectedly appended: before={before} after={after}")
    validators = get("/api/v1/validators")["validators"]
    if next(item for item in validators if item["id"] == 4)["status"] != "offline":
        raise AssertionError(f"engine 4 was not reported offline: {validators}")
    print(json.dumps({"result": "PASS", "scenario": "one engine stopped", "request_id": request_id, "ledger_heights": after}, indent=2))


def no_quorum() -> None:
    before = ledger_heights()
    request_id = post_qc("no-quorum")
    time.sleep(3)
    status = get(f"/api/v1/qcs/{request_id}")
    after = ledger_heights()
    if status["state"] != "pending":
        raise AssertionError(f"two engines incorrectly committed: {status}")
    if after != before:
        raise AssertionError(f"ledger changed without quorum: before={before} after={after}")
    print(json.dumps({"result": "PASS", "scenario": "only two engines running", "request_id": request_id, "state": status["state"], "ledger_heights": after}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"one-down", "no-quorum"}:
        raise SystemExit("usage: python -m regional_core.tests.compose_faults one-down|no-quorum")
    one_down() if sys.argv[1] == "one-down" else no_quorum()
