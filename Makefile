COMPOSE := COMPOSE_PARALLEL_LIMIT=1 docker compose -f deploy/local/compose.yaml

.PHONY: demo-build demo-up demo-status demo-logs demo-test demo-test-faults demo-down test-unit

demo-build:
	docker build --file deploy/local/Dockerfile.dummy-validator --tag mwvn-dummy-validator:local .
	docker build --file deploy/local/Dockerfile.bftnode --tag mwvn-smartbft-engine:local .

demo-up: demo-build
	@$(COMPOSE) down --volumes --remove-orphans >/dev/null 2>&1 || true
	$(COMPOSE) up --detach --wait --wait-timeout 180
	@echo "MWVN demo is ready at http://127.0.0.1:8090"

demo-status:
	$(COMPOSE) ps

demo-logs:
	$(COMPOSE) logs --follow

demo-test:
	$(COMPOSE) exec -T dummy-validator-1 python -m dummy_validator.tests.compose_smoke

demo-test-faults:
	$(COMPOSE) stop bft-node-4
	$(COMPOSE) exec -T dummy-validator-1 python -m dummy_validator.tests.compose_faults one-down
	$(COMPOSE) stop bft-node-3
	$(COMPOSE) exec -T dummy-validator-1 python -m dummy_validator.tests.compose_faults no-quorum
	@echo "Fault tests passed. Run 'make demo-up' to restore a fresh four-engine demo."

demo-down:
	$(COMPOSE) down --volumes --remove-orphans

test-unit:
	go test -mod=vendor -count=1 ./cmd/mwvn_bftnode
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v dummy_validator.tests.test_app
