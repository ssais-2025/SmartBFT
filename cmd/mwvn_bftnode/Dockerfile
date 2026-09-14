FROM golang:1.27-alpine AS build

WORKDIR /src
COPY go.mod go.sum ./
COPY vendor ./vendor
COPY internal ./internal
COPY pkg ./pkg
COPY smartbftprotos ./smartbftprotos
COPY cmd/mwvn_bftnode ./cmd/mwvn_bftnode
RUN CGO_ENABLED=0 go build -mod=vendor -trimpath -o /out/mwvn-bftnode ./cmd/mwvn_bftnode

FROM alpine:3.23
RUN addgroup -S mwvn && adduser -S -G mwvn mwvn
RUN mkdir /data && chown mwvn:mwvn /data
COPY --from=build /out/mwvn-bftnode /usr/local/bin/mwvn-bftnode
USER mwvn
ENTRYPOINT ["/usr/local/bin/mwvn-bftnode"]
