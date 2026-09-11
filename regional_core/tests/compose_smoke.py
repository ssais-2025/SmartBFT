"""Happy-flow verification executed inside the Compose network."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:8080"


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE_URL + path, timeout=5) as response:
        return json.load(response)


def post(path: str, value: dict) -> dict:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(value).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def main() -> None:
    suffix = str(int(time.time() * 1_000_000))
    request_id = f"compose-{suffix}"
    qc = {
        "schema_version": "mwvn-approved-qc/v1",
        "request_id": request_id,
        "qc_id": f"qc-{suffix}",
        "claim_hash": "7a9e667f3b8d94b7c0c5f590a8a2c26d662f8e86d73e631cdd8c39f24f40a9b4",
        "window_start": "2026-09-10T07:00:00Z",
        "window_end": "2026-09-10T07:05:00Z",
        "region": "med-east-demo",
        "classification": "AUTHENTIC",
        "policy_version": "demo-policy-v1",
        "evidence_refs": [f"synthetic-vdes-{suffix}"],
        "conflict_links": [],
    }
    admission = post("/api/v1/qcs", qc)
    if admission["status"]["state"] != "pending":
        raise AssertionError(f"unexpected admission: {admission}")

    deadline = time.monotonic() + 20
    committed = None
    while time.monotonic() < deadline:
        committed = get(f"/api/v1/qcs/{request_id}")
        if committed["state"] == "committed":
            break
        time.sleep(0.1)
    if not committed or committed["state"] != "committed":
        raise AssertionError(f"request did not commit: {committed}")
    if len(committed["committed_validators"]) < 3:
        raise AssertionError(f"decision proof has no quorum: {committed}")

    deadline = time.monotonic() + 10
    ledgers = None
    while time.monotonic() < deadline:
        ledgers = get("/api/v1/ledgers")["ledgers"]
        if all(isinstance(records, list) and records for records in ledgers.values()):
            heads = {records[-1]["record_hash"] for records in ledgers.values()}
            if len(heads) == 1:
                break
        time.sleep(0.1)
    if not ledgers or len(ledgers) != 4:
        raise AssertionError(f"missing ledgers: {ledgers}")
    heads = {records[-1]["record_hash"] for records in ledgers.values() if isinstance(records, list) and records}
    if len(heads) != 1:
        raise AssertionError(f"four Python ledgers did not converge: {ledgers}")

    validators = get("/api/v1/validators")["validators"]
    if len(validators) != 4 or any(node["status"] != "ok" for node in validators):
        raise AssertionError(f"not all four engine processes are healthy: {validators}")
    phases = {event["message_type"] for event in get("/api/v1/trace")["events"]}
    required = {"PRE-PREPARE", "PREPARE", "COMMIT", "LEDGER-APPEND"}
    if not required.issubset(phases):
        raise AssertionError(f"trace is missing phases {sorted(required - phases)}")

    print(
        json.dumps(
            {
                "result": "PASS",
                "request_id": request_id,
                "committed_validators": committed["committed_validators"],
                "ledger_head": next(iter(heads)),
                "engine_processes": [node["id"] for node in validators],
                "observed_phases": sorted(required),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as error:
        raise SystemExit(f"demo API is unavailable: {error}") from error
