# Prepare-vote timeout implementation and verification report

Date: 2026-09-10 (Asia/Jerusalem)  
Repository: `/Users/shlomy/projects/SmartBFT-v1.0.1`  
Branch: `regional-bft-smartbft`  
Upstream base commit: `294fbd378e5fd45d5d6aa283a2125e30bb7bcd37`  
Result: **PASS**

## Implemented behavior

The fork now exposes `types.Configuration.PrepareVoteCollectionTimeout`. Its default is exactly `5 * time.Minute`.

The timer starts when a replica enters PREPARE-vote collection after accepting and persisting a proposal. It is a maximum deadline, not an unconditional delay:

- a replica that receives the required PREPARE quorum continues immediately to COMMIT;
- a replica that misses the deadline logs the timeout, calls the existing failure detector with `Complain(view, true)`, and aborts the current view;
- SmartBFT's existing view-change mechanism performs recovery;
- aborting the view by another path stops the local timer without generating a second complaint.

This change applies only to PREPARE collection. It does not add a COMMIT timeout and does not alter request batching, quorum calculation, wire messages, or signature behavior.

The new setting is carried through public configuration, consensus-to-view wiring, and reconfiguration conversion. Public validation rejects zero or negative values.

## Before baseline

The baseline was captured from the unmodified base commit before adding the setting.

- Test: upstream `TestBasic`
- Topology: four SmartBFT replicas using the repository's in-process simulated network
- Result: all four replicas delivered the same decision; PASS in 0.88 seconds
- Log: `before-four-node-no-prepare-timeout.log`
- SHA-256: `6cd8a3aae799cd01db8247a57a8b05e492746d65c74d21b77bd1013c8553673f`

## After scenarios

### Four nodes, five-minute setting, healthy quorum

- Setting: `PrepareVoteCollectionTimeout = 5m0s` on all four replicas
- Input: one synthetic request representing an approved QC at MWVN ingress
- Evidence: each replica logged that it was collecting two remote PREPARE votes with timeout `5m0s`
- Result: all four replicas delivered the same decision in about 40 ms; the protocol did not wait five minutes
- Test: `TestFourNodePrepareQuorumDoesNotWaitForDeadline`
- Log: `after-four-node-five-minute-config.log`
- SHA-256: `8858d8adc0d1421c68de07490bf41e5eb4e82fc0bcbe78ba7aaa6e531fc018c3`

### Four nodes, PREPARE loss, timeout, view change, recovery

- Test setting: 250 ms, intentionally shortened to test the same production timer path quickly
- Fault: all PREPARE messages were temporarily filtered
- Evidence: replicas logged zero of two required remote PREPARE votes at expiry
- Recovery: after two local timeout complaints (`f+1` for a four-node, `f=1` cluster), PREPARE delivery was restored
- Result: all four replicas entered view 1 and delivered the same decision; PASS under the Go race detector
- Test: `TestFourNodePrepareTimeoutTriggersViewChangeAndRecovery`
- Log: `after-four-node-timeout-recovery.log`
- SHA-256: `1f37f665e079342d0a0dd6f390847075688779c492074193388821afeb2dd533`

### Unit scenarios

The focused unit suite verifies:

1. the default is exactly five minutes;
2. zero and negative public values are rejected;
3. a PREPARE quorum advances immediately despite a five-minute deadline;
4. an expired deadline complains and returns `ABORT`;
5. an externally aborted view exits without a timeout complaint.

Result: five tests passed.  
Log: `after-unit-scenarios.log`  
SHA-256: `fea3b4ab9b037683ba07d5f47d4b085032c41ff876ed8f81bc2e8f0fff62112a`

### Repetition and regression

- Recovery stability: the race-enabled recovery scenario passed 10 consecutive runs.
  - Log: `recovery-stability-race-count-10.log`
  - SHA-256: `da5919ea69cf200e1ffc73677c070f0d62ade09b70293acf7d3681184576e2cb`
- Full repository race suite: all packages passed, including the existing integration and reconfiguration suites.
  - SmartBFT integration package: PASS in 80.336 seconds
  - Log: `after-full-race-suite.log`
  - SHA-256: `43f3ab64e9934ba9f7f25779f5d7910c35c362937789d0cb2d1cfcfbcb86ac07`
- Full repository build: PASS. Go emits no output for a cached successful build, so `after-build.log` is intentionally empty.
  - SHA-256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

## Reproduction commands

Run from the repository root. The listed `TEST_TELEMETRY_DIR` keeps Go's local telemetry files inside a disposable writable directory; it does not affect the tested code.

```bash
TEST_TELEMETRY_DIR=/tmp/go-telemetry-smartbft GOTOOLCHAIN=local GOPROXY=off go test -mod=vendor -count=1 -run '^TestFourNodePrepareQuorumDoesNotWaitForDeadline$' -v ./test

TEST_TELEMETRY_DIR=/tmp/go-telemetry-smartbft GOTOOLCHAIN=local GOPROXY=off go test -mod=vendor -count=1 -race -run '^TestFourNodePrepareTimeoutTriggersViewChangeAndRecovery$' -v ./test

TEST_TELEMETRY_DIR=/tmp/go-telemetry-smartbft GOTOOLCHAIN=local GOPROXY=off go test -mod=vendor -count=10 -race -run '^TestFourNodePrepareTimeoutTriggersViewChangeAndRecovery$' ./test

TEST_TELEMETRY_DIR=/tmp/go-telemetry-smartbft GOTOOLCHAIN=local GOPROXY=off go test -mod=vendor -count=1 -race ./...

TEST_TELEMETRY_DIR=/tmp/go-telemetry-smartbft GOTOOLCHAIN=local GOPROXY=off go build -mod=vendor ./...
```

The captured run used Go 1.26.0 at `/Users/shlomy/Documents/ChatGPT/bft/toolchains/go1.26.0/go/bin/go`, a dedicated cache, and the vendored dependency tree.

## Limitations and assumptions

- The four replicas are real SmartBFT consensus instances but run inside one Go test process over SmartBFT's simulated in-memory transport. These logs do not claim four operating-system processes or a production network.
- The healthy scenario uses the exact five-minute configuration. The expiry branch uses 250 ms to avoid a five-minute automated test; the exact default is independently asserted by a unit test.
- Timers are local wall-clock deadlines. Operational deployments should distribute the same positive value to every validator.
- The timeout intentionally delegates safety and recovery to SmartBFT's existing persisted PREPARE state and view-change protocol; it introduces no replacement view-change algorithm.
- No COMMIT-stage timeout was added because the requested/paper behavior places the five-minute buffer in PREPARE collection.

## Status against Shlomy's regional-layer task list

This report covers only the current SmartBFT increment and does not mark unrelated work as complete.

| Regional-layer task | Status after this increment |
|---|---|
| Event ingestion, canonical decoding, signature validation, expiry, replay protection | Not part of this fork change |
| Corroboration policy and conflict-preserving state machine | Not part of this fork change |
| Simulator generates Layer 1 and Layer 2 events | Not part of this fork change |
| Integrate a studied PBFT/HotStuff implementation among known validators | **Partial:** SmartBFT PREPARE deadline and four-replica behavior implemented and verified; the local HTTP wrapper is covered by `docs/verification/mwvn-demo/REPORT.md`, while multi-process deployment transport remains separate work |
| Byzantine, duplicate, malformed, partition, stale-version, and conflict tests | **Partial:** PREPARE-message loss, view-change recovery, race checks, and SmartBFT's existing suite pass; QC-domain fault scenarios remain separate work |
| Latency, throughput, storage, recovery, certificate-size measurements | **Partial:** focused latency and recovery evidence captured; benchmark suite remains separate work |
| Reproducible logs and implementation documentation | **Done for this increment** |
