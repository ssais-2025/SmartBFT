# MWVN four-process SmartBFT demo verification report

Date: 2026-09-11 (Asia/Jerusalem)  
Repository: `/Users/shlomy/projects/SmartBFT-v1.0.1`  
Branch: `regional-bft-smartbft`  
Result: **PASS for the standalone regional-consensus milestone**

## Delivered architecture

The local Compose demo runs eight separate operating-system processes:

```text
Python regional core 1 <-> Go SmartBFT engine 1
Python regional core 2 <-> Go SmartBFT engine 2
Python regional core 3 <-> Go SmartBFT engine 3
Python regional core 4 <-> Go SmartBFT engine 4
```

The four SmartBFT engines communicate over the Compose IP network and use an explicit shared membership file. Each engine has a distinct Ed25519 development identity, write-ahead log, HTTP endpoint, and paired Python regional core. Each Python core independently validates a synthetic already-approved QC and stores the committed application record in its own durable JSON ledger.

The demo provides:

- a browser form at `http://127.0.0.1:8090`;
- an HTTP API for submitting a synthetic approved QC and reading health, request status, traces, and ledgers;
- actual SmartBFT PRE-PREPARE, PREPARE, and COMMIT processing with a `3-of-4` quorum;
- signed engine-to-engine HTTP messages using development-only Ed25519 keys;
- a configurable PREPARE collection timeout, set to five minutes in the local deployment;
- independent application validation and ledger storage in four Python processes;
- reproducible happy-flow and fault tests.

## Automated verification

The following checks passed in the target repository:

```text
go test -mod=vendor -count=1 ./cmd/mwvn_bftnode
PASS

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v regional_core.tests.test_app
Ran 4 tests - OK

docker compose -f deploy/local/compose.yaml config --quiet
PASS

make demo-test
PASS
```

The Compose happy-flow test verified:

1. all four Python cores and all four SmartBFT engines were healthy;
2. a synthetic approved QC reached SmartBFT commitment;
3. PRE-PREPARE, PREPARE, COMMIT, and LEDGER-APPEND appeared in the trace;
4. all four Python ledgers reached the same height and record hash.

The Compose fault test also passed:

- with one of four engines stopped, the remaining three engines committed;
- with two engines stopped, the request stayed pending and no ledger advanced.

The browser sanity check passed. Submitting the preloaded fixture displayed `Committed by a 3-of-4 SmartBFT quorum`, all four validator pairs reached height 1 with the same ledger head, and the protocol phases were visible on screen.

During verification, a ledger-divergence issue was found and fixed: different validators can retain different valid three-signature subsets for the same SmartBFT decision. The consensus record hash now covers only consensus-decided application data, while each node's local decision proof is stored separately. A unit test confirms that different valid proof subsets produce the same ledger hash.

## Implemented validation boundary

The Python regional core currently implements:

- strict JSON/schema decoding;
- canonical request hashing;
- required hash formats and event time ordering;
- duplicate evidence-reference rejection;
- request-ID replay detection and conflict rejection;
- proposal and previous-ledger-link validation;
- validation of the SmartBFT commit proof before durable ledger append.

A `committed` result means that at least three regional SmartBFT engines agreed on the same supplied synthetic approved-QC record. It does not prove physical vessel authenticity and does not construct the witness quorum certificate.

## Remaining work

This milestone intentionally does not yet implement:

- witness or QC cryptographic-signature verification;
- QC expiry and stale-model-version policy;
- the full corroboration and conflict-preserving MWVN state machine;
- simulator-generated Layer 1 and Layer 2 event streams;
- TLS or production key management;
- restart/state transfer with retained demo volumes;
- Byzantine message mutation beyond stopped-node/no-quorum tests;
- the full latency, throughput, storage, recovery, and certificate-size benchmark suite.

## Task status

| Shlomy regional-layer task | Status |
|---|---|
| Event ingestion, canonical decoding, signature validation, expiry, replay protection | **Partial:** ingestion, strict decoding, canonical hashing, time ordering, duplicate-reference checks, and replay/conflict handling are implemented. Witness/QC signature verification and expiry remain. |
| Corroboration policy and conflict-preserving state machine | **Not yet implemented:** the input is already an approved QC. |
| Simulator generates Layer 1 and Layer 2 events | **Not yet implemented:** this standalone demo uses synthetic approved-QC input. |
| Integrate a studied PBFT/HotStuff implementation among known regional validators | **Done for this milestone:** four independent SmartBFT engine processes, explicit membership, signed IP transport, `3-of-4` consensus, Python wrappers, and four ledgers work locally. |
| Byzantine validators, duplicate witnesses, malformed events, partitions, stale model versions, conflicting events | **Partial:** malformed input, duplicate evidence, replay conflicts, one stopped engine, and loss of quorum are tested. The remaining scenarios are open. |
| Measure latency, throughput, storage, recovery, and certificate size | **Partial:** trace timestamps and message sizes are exposed; the benchmark suite remains. |
| Reproducible logs and implementation documentation | **Done for this milestone:** Make targets, tests, browser trace, ledger output, concise user guide, and this report are included. |

## How to reproduce

Follow the concise user guide at `deploy/local/README.md`. The normal path is:

```bash
make demo-up
make demo-test
```

Then open `http://127.0.0.1:8090`. Run `make demo-down` when finished.
