import json
import tempfile
import unittest
from pathlib import Path

from regional_core.app import ConflictError, RegionalCore, ValidationError, canonical_bytes, validate_qc


def sample_qc(request_id: str = "test-001") -> dict:
    return {
        "schema_version": "mwvn-approved-qc/v1",
        "request_id": request_id,
        "qc_id": f"qc-{request_id}",
        "claim_hash": "7a9e667f3b8d94b7c0c5f590a8a2c26d662f8e86d73e631cdd8c39f24f40a9b4",
        "window_start": "2026-09-10T07:00:00Z",
        "window_end": "2026-09-10T07:05:00Z",
        "region": "med-east-demo",
        "classification": "AUTHENTIC",
        "policy_version": "demo-policy-v1",
        "evidence_refs": ["synthetic-vdes-event-001"],
        "conflict_links": [],
    }


class RegionalCoreTests(unittest.TestCase):
    def test_qc_validation_rejects_unknown_and_duplicate_evidence(self) -> None:
        unknown = sample_qc()
        unknown["unexpected"] = True
        with self.assertRaisesRegex(ValidationError, "unknown QC fields"):
            validate_qc(unknown)

        duplicate = sample_qc()
        duplicate["evidence_refs"] = ["same", "same"]
        with self.assertRaisesRegex(ValidationError, "duplicate"):
            validate_qc(duplicate)

    def test_proposal_validation_and_durable_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            core = RegionalCore(1, "http://unused", Path(directory), ["a"] * 4, ["b"] * 4)
            qc = sample_qc()
            verification = core.verify_proposal(
                canonical_bytes(
                    {
                        "header": {"sequence": 1, "previous_hash": "0" * 64},
                        "approved_qcs": [qc],
                    }
                )
            )
            self.assertEqual(["test-001"], verification["request_ids"])

            commit = {
                "schema_version": "mwvn-bft-commit/v1",
                "node_id": 1,
                "sequence": 1,
                "view": 0,
                "previous_hash": "0" * 64,
                "proposal_digest": "1" * 64,
                "approved_qcs": [qc],
                "decision_proof": [
                    {"validator_id": 3, "value": "a", "auxiliary": ""},
                    {"validator_id": 1, "value": "b", "auxiliary": ""},
                    {"validator_id": 2, "value": "c", "auxiliary": ""},
                ],
            }
            result = core.commit(canonical_bytes(commit))
            self.assertTrue(result["created"])
            self.assertEqual(1, core.state()["height"])
            self.assertEqual([1, 2, 3], core.request_status("test-001")["committed_validators"])

            saved = json.loads((Path(directory) / "ledger.json").read_text())
            self.assertEqual(core.state()["ledger_head"], saved["records"][0]["record_hash"])
            restored = RegionalCore(1, "http://unused", Path(directory), ["a"] * 4, ["b"] * 4)
            self.assertEqual(core.state(), restored.state())

    def test_commit_conflict_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            core = RegionalCore(1, "http://unused", Path(directory), ["a"] * 4, ["b"] * 4)
            base = {
                "schema_version": "mwvn-bft-commit/v1",
                "node_id": 1,
                "sequence": 1,
                "view": 0,
                "previous_hash": "0" * 64,
                "proposal_digest": "1" * 64,
                "approved_qcs": [sample_qc()],
                "decision_proof": [
                    {"validator_id": node, "value": str(node), "auxiliary": ""}
                    for node in (1, 2, 3)
                ],
            }
            core.commit(canonical_bytes(base))
            conflicting = dict(base)
            conflicting["proposal_digest"] = "2" * 64
            with self.assertRaisesRegex(ConflictError, "another proposal"):
                core.commit(canonical_bytes(conflicting))

    def test_valid_signature_subsets_produce_the_same_ledger_hash(self) -> None:
        with tempfile.TemporaryDirectory() as first_directory, tempfile.TemporaryDirectory() as second_directory:
            first = RegionalCore(1, "http://unused", Path(first_directory), ["a"] * 4, ["b"] * 4)
            second = RegionalCore(2, "http://unused", Path(second_directory), ["a"] * 4, ["b"] * 4)
            common = {
                "schema_version": "mwvn-bft-commit/v1",
                "sequence": 1,
                "view": 0,
                "previous_hash": "0" * 64,
                "proposal_digest": "1" * 64,
                "approved_qcs": [sample_qc()],
            }
            first_commit = common | {
                "node_id": 1,
                "decision_proof": [
                    {"validator_id": node, "value": str(node), "auxiliary": ""}
                    for node in (1, 2, 3)
                ],
            }
            second_commit = common | {
                "node_id": 2,
                "decision_proof": [
                    {"validator_id": node, "value": str(node), "auxiliary": ""}
                    for node in (1, 3, 4)
                ],
            }
            first_record = first.commit(canonical_bytes(first_commit))["record"]
            second_record = second.commit(canonical_bytes(second_commit))["record"]
            self.assertNotEqual(first_record["decision_proof"], second_record["decision_proof"])
            self.assertEqual(first_record["record_hash"], second_record["record_hash"])


if __name__ == "__main__":
    unittest.main()
