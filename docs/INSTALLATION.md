# Installation

Requirements: Go 1.20+ or Docker.

```bash
go test -mod=vendor ./cmd/mwvn_bftnode
docker build -f cmd/mwvn_bftnode/Dockerfile -t mwvn-smartbft-engine:local .
```

Use `ssais-2025/mwvn-regional-deployment` for the supported four-node deployment.
