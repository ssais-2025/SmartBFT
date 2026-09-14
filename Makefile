.PHONY: test-mwvn-bftnode test-prepare-timeout
test-mwvn-bftnode:
	go test -mod=vendor -count=1 ./cmd/mwvn_bftnode
test-prepare-timeout:
	go test -mod=vendor -count=1 ./internal/bft ./test -run 'Test.*Prepare'
