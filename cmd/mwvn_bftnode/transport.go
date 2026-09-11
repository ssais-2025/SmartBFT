// Copyright IBM Corp. All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0

package main

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/binary"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/hyperledger-labs/SmartBFT/pkg/types"
	"github.com/hyperledger-labs/SmartBFT/smartbftprotos"
	"google.golang.org/protobuf/proto"
)

type traceEvent struct {
	Index          uint64    `json:"index"`
	Timestamp      time.Time `json:"timestamp"`
	NodeID         uint64    `json:"node_id"`
	Direction      string    `json:"direction"`
	Sender         uint64    `json:"sender,omitempty"`
	Receiver       uint64    `json:"receiver,omitempty"`
	MessageType    string    `json:"message_type"`
	View           *uint64   `json:"view,omitempty"`
	Sequence       *uint64   `json:"sequence,omitempty"`
	ProposalDigest string    `json:"proposal_digest,omitempty"`
	SizeBytes      int       `json:"size_bytes"`
	Outcome        string    `json:"outcome"`
}

type traceStore struct {
	mu     sync.RWMutex
	next   uint64
	events []traceEvent
}

func (s *traceStore) add(event traceEvent) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.next++
	event.Index = s.next
	event.Timestamp = time.Now().UTC()
	s.events = append(s.events, event)
	if len(s.events) > 5000 {
		s.events = append([]traceEvent(nil), s.events[len(s.events)-5000:]...)
	}
}

func (s *traceStore) list(after uint64, limit int) []traceEvent {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := make([]traceEvent, 0, limit)
	for _, event := range s.events {
		if event.Index <= after {
			continue
		}
		result = append(result, event)
		if len(result) == limit {
			break
		}
	}
	return result
}

type httpComm struct {
	id         uint64
	networkID  string
	members    []member
	privateKey ed25519.PrivateKey
	client     *http.Client
	trace      *traceStore
}

func newHTTPComm(id uint64, config membership, privateKey ed25519.PrivateKey, trace *traceStore) *httpComm {
	return &httpComm{
		id:         id,
		networkID:  config.NetworkID,
		members:    append([]member(nil), config.Nodes...),
		privateKey: privateKey,
		client:     &http.Client{Timeout: 3 * time.Second},
		trace:      trace,
	}
}

func (c *httpComm) Nodes() []uint64 {
	result := make([]uint64, 0, len(c.members))
	for _, node := range c.members {
		result = append(result, node.ID)
	}
	return result
}

func (c *httpComm) peerURL(id uint64) string {
	for _, node := range c.members {
		if node.ID == id {
			return node.PeerURL
		}
	}
	return ""
}

func (c *httpComm) SendConsensus(targetID uint64, message *smartbftprotos.Message) {
	raw, err := proto.Marshal(message)
	if err != nil {
		return
	}
	kind, view, sequence, digest := consensusMessageDetails(message)
	c.trace.add(traceEvent{NodeID: c.id, Direction: "send", Sender: c.id, Receiver: targetID, MessageType: kind, View: view, Sequence: sequence, ProposalDigest: digest, SizeBytes: len(raw), Outcome: "queued_http"})
	go c.post(targetID, "/internal/v1/consensus", "application/x-protobuf", raw, kind)
}

func (c *httpComm) SendTransaction(targetID uint64, request []byte) {
	raw := append([]byte(nil), request...)
	c.trace.add(traceEvent{NodeID: c.id, Direction: "send", Sender: c.id, Receiver: targetID, MessageType: "FORWARDED-REQUEST", SizeBytes: len(raw), Outcome: "queued_http"})
	go c.post(targetID, "/internal/v1/transaction", "application/json", raw, "FORWARDED-REQUEST")
}

func (c *httpComm) post(targetID uint64, path, contentType string, raw []byte, messageType string) {
	endpoint := c.peerURL(targetID)
	if endpoint == "" {
		c.trace.add(traceEvent{NodeID: c.id, Direction: "transport_error", Sender: c.id, Receiver: targetID, MessageType: messageType, SizeBytes: len(raw), Outcome: "unknown_peer"})
		return
	}
	request, err := http.NewRequest(http.MethodPost, endpoint+path, bytes.NewReader(raw))
	if err != nil {
		return
	}
	request.Header.Set("Content-Type", contentType)
	request.Header.Set("X-MWVN-Network", c.networkID)
	request.Header.Set("X-MWVN-Sender", strconv.FormatUint(c.id, 10))
	request.Header.Set("X-MWVN-Signature", base64.StdEncoding.EncodeToString(ed25519.Sign(c.privateKey, transportSigningPayload(c.networkID, path, raw))))
	response, err := c.client.Do(request)
	if err != nil {
		c.trace.add(traceEvent{NodeID: c.id, Direction: "transport_error", Sender: c.id, Receiver: targetID, MessageType: messageType, SizeBytes: len(raw), Outcome: err.Error()})
		return
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 64<<10))
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		c.trace.add(traceEvent{NodeID: c.id, Direction: "transport_error", Sender: c.id, Receiver: targetID, MessageType: messageType, SizeBytes: len(raw), Outcome: fmt.Sprintf("http_%d", response.StatusCode)})
	}
}

func transportSigningPayload(networkID, path string, body []byte) []byte {
	result := make([]byte, 0, len(networkID)+len(path)+len(body)+24)
	for _, field := range [][]byte{[]byte("mwvn-peer-http/v1"), []byte(networkID), []byte(path), body} {
		var size [8]byte
		binary.BigEndian.PutUint64(size[:], uint64(len(field)))
		result = append(result, size[:]...)
		result = append(result, field...)
	}
	return result
}

func consensusMessageDetails(message *smartbftprotos.Message) (string, *uint64, *uint64, string) {
	copyNumber := func(value uint64) *uint64 { result := value; return &result }
	if value := message.GetPrePrepare(); value != nil {
		digest := ""
		if value.Proposal != nil {
			proposal := types.Proposal{Header: value.Proposal.Header, Payload: value.Proposal.Payload, Metadata: value.Proposal.Metadata, VerificationSequence: int64(value.Proposal.VerificationSequence)}
			digest = proposal.Digest()
		}
		return "PRE-PREPARE", copyNumber(value.View), copyNumber(value.Seq), digest
	}
	if value := message.GetPrepare(); value != nil {
		return "PREPARE", copyNumber(value.View), copyNumber(value.Seq), value.Digest
	}
	if value := message.GetCommit(); value != nil {
		return "COMMIT", copyNumber(value.View), copyNumber(value.Seq), value.Digest
	}
	if value := message.GetViewChange(); value != nil {
		return "VIEW-CHANGE", copyNumber(value.NextView), nil, ""
	}
	if message.GetViewData() != nil {
		return "VIEW-DATA", nil, nil, ""
	}
	if message.GetNewView() != nil {
		return "NEW-VIEW", nil, nil, ""
	}
	if value := message.GetHeartBeat(); value != nil {
		return "HEARTBEAT", copyNumber(value.View), copyNumber(value.Seq), ""
	}
	if value := message.GetHeartBeatResponse(); value != nil {
		return "HEARTBEAT-RESPONSE", copyNumber(value.View), nil, ""
	}
	if message.GetStateTransferRequest() != nil {
		return "STATE-TRANSFER-REQUEST", nil, nil, ""
	}
	if message.GetStateTransferResponse() != nil {
		return "STATE-TRANSFER-RESPONSE", nil, nil, ""
	}
	return "UNKNOWN", nil, nil, ""
}
