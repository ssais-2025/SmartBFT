#!/usr/bin/env python3
"""MWVN regional-validator core for the four-process SmartBFT demonstration."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


QC_SCHEMA = "mwvn-approved-qc/v1"
COMMIT_SCHEMA = "mwvn-bft-commit/v1"
ZERO_HASH = "0" * 64
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
QC_FIELDS = {
    "schema_version",
    "request_id",
    "qc_id",
    "claim_hash",
    "window_start",
    "window_end",
    "region",
    "classification",
    "policy_version",
    "evidence_refs",
    "conflict_links",
}


class ValidationError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def parse_rfc3339(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be an RFC3339 string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError(f"{name} must use RFC3339") from error


def validate_digest(value: Any, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValidationError(f"{name} must be a 64-character SHA-256 digest")
    try:
        bytes.fromhex(value)
    except ValueError as error:
        raise ValidationError(f"{name} must be hexadecimal") from error


def validate_qc(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("approved QC must be a JSON object")
    unknown = set(value) - QC_FIELDS
    missing = (QC_FIELDS - {"conflict_links"}) - set(value)
    if unknown:
        raise ValidationError(f"unknown QC fields: {', '.join(sorted(unknown))}")
    if missing:
        raise ValidationError(f"missing QC fields: {', '.join(sorted(missing))}")
    if value["schema_version"] != QC_SCHEMA:
        raise ValidationError(f"schema_version must be {QC_SCHEMA!r}")
    for name in ("request_id", "qc_id", "region", "classification", "policy_version"):
        if not isinstance(value[name], str) or not IDENTIFIER.fullmatch(value[name]):
            raise ValidationError(f"{name} is missing or invalid")
    validate_digest(value["claim_hash"], "claim_hash")
    start = parse_rfc3339(value["window_start"], "window_start")
    end = parse_rfc3339(value["window_end"], "window_end")
    if end < start:
        raise ValidationError("window_end must not be before window_start")
    evidence = value["evidence_refs"]
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item for item in evidence):
        raise ValidationError("evidence_refs must contain non-empty strings")
    if len(set(evidence)) != len(evidence):
        raise ValidationError("evidence_refs contains a duplicate")
    conflicts = value.get("conflict_links", [])
    if not isinstance(conflicts, list):
        raise ValidationError("conflict_links must be an array")
    if len(set(conflicts)) != len(conflicts):
        raise ValidationError("conflict_links contains a duplicate")
    for conflict in conflicts:
        validate_digest(conflict, "conflict_links entry")
    normalized = dict(value)
    normalized["conflict_links"] = list(conflicts)
    return normalized


def parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"invalid JSON: {error}") from error


class RegionalCore:
    def __init__(self, node_id: int, bft_url: str, data_dir: Path, core_urls: list[str], engine_urls: list[str]):
        self.node_id = node_id
        self.bft_url = bft_url.rstrip("/")
        self.data_dir = data_dir
        self.core_urls = [url.rstrip("/") for url in core_urls]
        self.engine_urls = [url.rstrip("/") for url in engine_urls]
        self.ledger_path = data_dir / "ledger.json"
        self.lock = threading.RLock()
        self.records: list[dict[str, Any]] = []
        self.requests: dict[str, dict[str, Any]] = {}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._load_ledger()

    def _load_ledger(self) -> None:
        if not self.ledger_path.exists():
            return
        document = json.loads(self.ledger_path.read_text())
        if document.get("node_id") != self.node_id or not isinstance(document.get("records"), list):
            raise RuntimeError("ledger file does not match this regional core")
        self.records = document["records"]
        for record in self.records:
            for qc in record.get("approved_qcs", []):
                self.requests[qc["request_id"]] = self._committed_status(qc, record)

    def _persist(self) -> None:
        document = {"node_id": self.node_id, "records": self.records}
        handle, temporary = tempfile.mkstemp(prefix=".ledger-", suffix=".tmp", dir=self.data_dir)
        try:
            with os.fdopen(handle, "w") as stream:
                json.dump(document, stream, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.ledger_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def state(self) -> dict[str, Any]:
        with self.lock:
            head = self.records[-1]["record_hash"] if self.records else ZERO_HASH
            return {"node_id": self.node_id, "height": len(self.records), "ledger_head": head}

    def ledger(self) -> list[dict[str, Any]]:
        with self.lock:
            return json.loads(json.dumps(self.records))

    def verify_request(self, raw: bytes) -> dict[str, Any]:
        qc = validate_qc(parse_json(raw))
        return {"request_ids": [qc["request_id"]]}

    def verify_proposal(self, raw: bytes) -> dict[str, Any]:
        value = parse_json(raw)
        if not isinstance(value, dict) or set(value) != {"header", "approved_qcs"}:
            raise ValidationError("proposal verification requires header and approved_qcs")
        header = value["header"]
        if not isinstance(header, dict):
            raise ValidationError("proposal header must be an object")
        qcs = [validate_qc(qc) for qc in value["approved_qcs"]]
        with self.lock:
            expected_sequence = len(self.records) + 1
            expected_previous = self.records[-1]["record_hash"] if self.records else ZERO_HASH
        if header.get("sequence") != expected_sequence:
            raise ValidationError(f"proposal sequence must be {expected_sequence}")
        if header.get("previous_hash") != expected_previous:
            raise ValidationError("proposal previous_hash does not match the local Python ledger")
        return {"request_ids": [qc["request_id"] for qc in qcs]}

    def submit(self, raw: bytes) -> tuple[int, dict[str, Any]]:
        qc = validate_qc(parse_json(raw))
        normalized = canonical_bytes(qc)
        content_hash = hashlib.sha256(normalized).hexdigest()
        with self.lock:
            existing = self.requests.get(qc["request_id"])
            if existing:
                if existing["content_hash"] != content_hash:
                    raise ConflictError("request_id already exists with different content")
                return HTTPStatus.OK, {"created": False, "status": existing}
            status = {
                "request_id": qc["request_id"],
                "qc_id": qc["qc_id"],
                "state": "pending",
                "content_hash": content_hash,
                "committed_validators": [],
                "submitted_at": datetime.now().astimezone().isoformat(),
            }
            self.requests[qc["request_id"]] = status
        try:
            post_json(self.bft_url + "/v1/requests", qc)
        except Exception:
            with self.lock:
                self.requests.pop(qc["request_id"], None)
            raise
        return HTTPStatus.ACCEPTED, {"created": True, "status": status}

    def request_status(self, request_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.requests.get(request_id)
            return json.loads(json.dumps(value)) if value else None

    def commit(self, raw: bytes) -> dict[str, Any]:
        value = parse_json(raw)
        required = {"schema_version", "node_id", "sequence", "view", "previous_hash", "proposal_digest", "approved_qcs", "decision_proof"}
        if not isinstance(value, dict) or set(value) != required:
            raise ValidationError("commit callback has invalid fields")
        if value["schema_version"] != COMMIT_SCHEMA or value["node_id"] != self.node_id:
            raise ValidationError("commit callback identity mismatch")
        validate_digest(value["previous_hash"], "previous_hash")
        validate_digest(value["proposal_digest"], "proposal_digest")
        qcs = [validate_qc(qc) for qc in value["approved_qcs"]]
        proof = value["decision_proof"]
        if not isinstance(proof, list) or len(proof) < 3:
            raise ValidationError("decision_proof requires at least three validator signatures")
        proof = sorted(proof, key=lambda item: item.get("validator_id", 0))
        validator_ids = [item.get("validator_id") for item in proof]
        if len(set(validator_ids)) != len(validator_ids) or any(not isinstance(item, int) for item in validator_ids):
            raise ValidationError("decision_proof validator IDs must be unique integers")
        with self.lock:
            expected_sequence = len(self.records) + 1
            expected_previous = self.records[-1]["record_hash"] if self.records else ZERO_HASH
            if value["sequence"] < expected_sequence:
                existing = self.records[value["sequence"] - 1]
                if existing["proposal_digest"] == value["proposal_digest"]:
                    return {"record": existing, "created": False}
                raise ConflictError("commit sequence already contains another proposal")
            if value["sequence"] != expected_sequence or value["previous_hash"] != expected_previous:
                raise ConflictError("commit does not extend the local Python ledger")
            decided_record = {
                "schema_version": "mwvn-regional-ledger/v1",
                "sequence": value["sequence"],
                "view": value["view"],
                "previous_hash": value["previous_hash"],
                "proposal_digest": value["proposal_digest"],
                "approved_qcs": qcs,
            }
            record = dict(decided_record)
            record["record_hash"] = digest(decided_record)
            record["decision_proof"] = proof
            record["committed_at"] = datetime.now().astimezone().isoformat()
            self.records.append(record)
            for qc in qcs:
                self.requests[qc["request_id"]] = self._committed_status(qc, record)
            self._persist()
            return {"record": record, "created": True}

    def _committed_status(self, qc: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": qc["request_id"],
            "qc_id": qc["qc_id"],
            "state": "committed",
            "content_hash": hashlib.sha256(canonical_bytes(qc)).hexdigest(),
            "committed_record_hash": record["record_hash"],
            "committed_validators": [proof["validator_id"] for proof in record["decision_proof"]],
            "committed_at": record["committed_at"],
        }


class ConflictError(RuntimeError):
    pass


def request_json(url: str, timeout: float = 2.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def post_json(url: str, value: Any, timeout: float = 5.0) -> Any:
    request = urllib.request.Request(url, data=canonical_bytes(value), method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        raise RuntimeError(f"{url} returned HTTP {error.code}: {body}") from error


class Handler(BaseHTTPRequestHandler):
    server_version = "MWVNRegionalCore/1"

    @property
    def core(self) -> RegionalCore:
        return self.server.core  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        print(f"core={self.core.node_id} {self.address_string()} {format % args}", flush=True)

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path == "/":
                self._html((Path(__file__).parent / "web" / "index.html").read_bytes())
            elif path == "/health":
                self._json(HTTPStatus.OK, self.core.state() | {"status": "ok"})
            elif path == "/internal/v1/state":
                self._json(HTTPStatus.OK, self.core.state())
            elif path == "/internal/v1/ledger":
                self._json(HTTPStatus.OK, {"node_id": self.core.node_id, "records": self.core.ledger()})
            elif path == "/api/v1/health":
                self._json(HTTPStatus.OK, self._cluster_health())
            elif path == "/api/v1/validators":
                self._json(HTTPStatus.OK, {"validators": self._validators()})
            elif path == "/api/v1/ledgers":
                self._json(HTTPStatus.OK, {"ledgers": self._ledgers()})
            elif path == "/api/v1/trace":
                self._json(HTTPStatus.OK, {"events": self._traces()})
            elif path.startswith("/api/v1/qcs/"):
                request_id = urllib.parse.unquote(path.removeprefix("/api/v1/qcs/"))
                status = self.core.request_status(request_id)
                if status is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "unknown request_id"})
                else:
                    self._json(HTTPStatus.OK, status)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception as error:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        try:
            raw = self._read_body()
            if path == "/api/v1/qcs":
                status, response = self.core.submit(raw)
                self._json(status, response)
            elif path == "/internal/v1/requests/verify":
                self._json(HTTPStatus.OK, self.core.verify_request(raw))
            elif path == "/internal/v1/proposals/verify":
                self._json(HTTPStatus.OK, self.core.verify_proposal(raw))
            elif path == "/internal/v1/commits":
                self._json(HTTPStatus.OK, self.core.commit(raw))
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except ValidationError as error:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
        except ConflictError as error:
            self._json(HTTPStatus.CONFLICT, {"error": str(error)})
        except Exception as error:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2 * 1024 * 1024:
            raise ValidationError("request body must be between 1 byte and 2 MiB")
        return self.rfile.read(length)

    def _cluster_health(self) -> dict[str, Any]:
        validators = self._validators()
        healthy = sum(1 for validator in validators if validator.get("status") == "ok")
        return {"status": "ok" if healthy >= 3 else "degraded", "architecture": "four Python cores paired with four independent Go SmartBFT engines", "healthy_engines": healthy, "required_quorum": 3}

    def _validators(self) -> list[dict[str, Any]]:
        validators = []
        for index, url in enumerate(self.core.engine_urls, start=1):
            try:
                value = request_json(url + "/v1/status")
                validators.append({"id": value["node_id"], "leader_id": value["leader_id"], "ledger_height": value["ledger_height"], "ledger_head": value["ledger_head"], "status": "ok"})
            except Exception as error:
                validators.append({"id": index, "leader_id": 0, "ledger_height": 0, "ledger_head": "", "status": "offline", "error": str(error)})
        return validators

    def _ledgers(self) -> dict[str, Any]:
        ledgers = {}
        for index, url in enumerate(self.core.core_urls, start=1):
            try:
                value = request_json(url + "/internal/v1/ledger")
                ledgers[f"validator-{index}"] = value["records"]
            except Exception as error:
                ledgers[f"validator-{index}"] = {"error": str(error)}
        return ledgers

    def _traces(self) -> list[dict[str, Any]]:
        events = []
        for url in self.core.engine_urls:
            try:
                events.extend(request_json(url + "/v1/trace?limit=2000")["events"])
            except Exception:
                continue
        events.sort(key=lambda event: (event.get("timestamp", ""), event.get("node_id", 0), event.get("index", 0)))
        for index, event in enumerate(events, start=1):
            event["index"] = index
        return events[-2000:]

    def _json(self, status: int, value: Any) -> None:
        body = canonical_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    node_id = int(os.environ.get("MWVN_NODE_ID", "0"))
    if node_id < 1:
        raise SystemExit("MWVN_NODE_ID must be a positive integer")
    listen = os.environ.get("MWVN_CORE_LISTEN", "0.0.0.0:8080")
    host, port = listen.rsplit(":", 1)
    bft_url = os.environ.get("MWVN_BFT_URL", "")
    if not bft_url:
        raise SystemExit("MWVN_BFT_URL is required")
    core_urls = [item for item in os.environ.get("MWVN_CORE_URLS", "").split(",") if item]
    engine_urls = [item for item in os.environ.get("MWVN_ENGINE_URLS", "").split(",") if item]
    if len(core_urls) != 4 or len(engine_urls) != 4:
        raise SystemExit("MWVN_CORE_URLS and MWVN_ENGINE_URLS must each contain four comma-separated URLs")
    core = RegionalCore(node_id, bft_url, Path(os.environ.get("MWVN_DATA_DIR", "/data")), core_urls, engine_urls)
    server = ThreadingHTTPServer((host, int(port)), Handler)
    server.core = core  # type: ignore[attr-defined]
    print(f"MWVN Python regional core ready: node={node_id} listen={listen} bft={bft_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
