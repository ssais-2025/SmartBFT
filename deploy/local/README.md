# MWVN regional BFT demo

This demo runs four independent regional-validator pairs on one computer:

```text
Python regional core 1 <-> Go SmartBFT engine 1
Python regional core 2 <-> Go SmartBFT engine 2
Python regional core 3 <-> Go SmartBFT engine 3
Python regional core 4 <-> Go SmartBFT engine 4
```

The four Go engines are separate operating-system processes and communicate over the Compose network. Every engine has its own identity, development key, API, and write-ahead log. Every Python core independently validates the synthetic approved-QC input and stores its own application ledger.

## Prerequisites

Install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/).

The demo also uses `make`, which is included with macOS developer tools. Confirm both commands work:

```bash
docker compose version
make --version
```

Go and Python do not need to be installed on the host.

## Installation

Open a terminal and enter the repository:

```bash
cd /Users/shlomy/projects/SmartBFT-v1.0.1
```

No additional packages are required.

## Run

```bash
make demo-up
```

Open <http://127.0.0.1:8090>, select **Submit**, and wait for **Committed by a 3-of-4 SmartBFT quorum**.

The screen shows the four validator pairs, their Python application ledgers, and PRE-PREPARE, PREPARE, COMMIT, and LEDGER-APPEND traffic.

## Test

```bash
make demo-test
```

A successful test prints `"result": "PASS"`.

## Status and logs

```bash
make demo-status
make demo-logs
```

Press `Ctrl-C` to leave the log view. The services continue running.

## Stop

```bash
make demo-down
```

## Configuration

- `deploy/local/compose.yaml` defines the eight processes, ports, data volumes, and health checks.
- `deploy/local/membership.json` defines the four SmartBFT identities and peer addresses.
- `deploy/local/dev-keys/` contains reproducible development-only Ed25519 keys.

The included keys are public test material and must never be used outside this local demo. Each `make demo-up` starts with empty demo volumes.

## Result boundary

A committed result means that the regional SmartBFT engines reached consensus on the supplied synthetic approved-QC fixture. It does not prove physical vessel authenticity and does not construct a witness quorum certificate.

The Python core currently performs strict schema, hash, time-ordering, duplicate-reference, proposal-linkage, replay-ID, and commit-proof checks. Witness signature verification, QC expiry policy, model-version policy, and the full conflict-preserving MWVN state machine remain later work.

Peer requests use real Ed25519 development signatures, but the local network does not use TLS. Restart/state transfer is not implemented; this demo starts with fresh volumes.
