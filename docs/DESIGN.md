# Design

`mwvn_bftnode` wraps SmartBFT with HTTP peer transport and callbacks to one paired Python validator. It orders admitted records; it does not perform MWVN QC validation.

## File structure

```text
cmd/mwvn_bftnode/  adapter, transport, membership, callbacks and Dockerfile
internal/bft/       consensus protocol and PREPARE timeout
pkg/consensus/      public consensus wrapper
pkg/types/          configuration and interfaces
pkg/wal/            write-ahead log
docs/               installation, API, design and timeout documentation
```

The five-minute setting is a maximum PREPARE deadline; quorum proceeds immediately. Compose, membership, keys, and end-to-end tests belong to `mwvn-regional-deployment`.
