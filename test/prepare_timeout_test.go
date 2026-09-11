// Copyright IBM Corp. All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0
//

package test

import (
	"os"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/hyperledger-labs/SmartBFT/smartbftprotos"
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

func newFourNodePrepareTimeoutNetwork(t *testing.T, timeout time.Duration) ([]*App, *Network) {
	t.Helper()

	network := NewNetwork()
	t.Cleanup(network.Shutdown)

	testDir, err := os.MkdirTemp("", t.Name())
	if err != nil {
		t.Fatalf("create temporary test directory: %v", err)
	}
	t.Cleanup(func() {
		if err := os.RemoveAll(testDir); err != nil {
			t.Errorf("remove temporary test directory: %v", err)
		}
	})

	nodes := make([]*App, 0, 4)
	for id := uint64(1); id <= 4; id++ {
		node := newNode(id, network, t.Name(), testDir, false, 0)
		node.Consensus.Config.PrepareVoteCollectionTimeout = timeout
		nodes = append(nodes, node)
	}
	return nodes, network
}

func waitForEqualDeliveries(t *testing.T, nodes []*App, timeout time.Duration) []*AppRecord {
	t.Helper()

	records := make([]*AppRecord, len(nodes))
	for i, node := range nodes {
		select {
		case records[i] = <-node.Delivered:
		case <-time.After(timeout):
			t.Fatalf("node %d did not deliver within %s", node.ID, timeout)
		}
	}
	for i := 1; i < len(records); i++ {
		if !reflect.DeepEqual(records[0], records[i]) {
			t.Fatalf("node %d delivered a different decision", nodes[i].ID)
		}
	}
	return records
}

func TestFourNodePrepareQuorumDoesNotWaitForDeadline(t *testing.T) {
	nodes, network := newFourNodePrepareTimeoutNetwork(t, 5*time.Minute)
	startNodes(nodes, network)

	started := time.Now()
	nodes[0].Submit(Request{ID: "approved-qc-normal", ClientID: "mwvn-ingress"})
	waitForEqualDeliveries(t, nodes, 10*time.Second)
	elapsed := time.Since(started)

	if elapsed >= 10*time.Second {
		t.Fatalf("a reached quorum waited %s instead of proceeding before the five-minute deadline", elapsed)
	}
	t.Logf("scenario=normal-four-node configured_prepare_timeout=%s result=committed elapsed=%s", 5*time.Minute, elapsed)
}

func TestFourNodePrepareTimeoutTriggersViewChangeAndRecovery(t *testing.T) {
	const prepareTimeout = 250 * time.Millisecond
	nodes, network := newFourNodePrepareTimeoutNetwork(t, prepareTimeout)

	timeoutEvents := make(chan uint64, len(nodes))
	var eventLock sync.Mutex
	timedOut := make(map[uint64]struct{})
	var dropPrepares atomic.Bool
	dropPrepares.Store(true)
	for _, node := range nodes {
		node := node
		logger := node.logger.Desugar().WithOptions(zap.Hooks(func(entry zapcore.Entry) error {
			if !strings.Contains(entry.Message, "prepare vote collection timeout") {
				return nil
			}
			eventLock.Lock()
			_, alreadyRecorded := timedOut[node.ID]
			if !alreadyRecorded {
				timedOut[node.ID] = struct{}{}
			}
			eventLock.Unlock()
			if !alreadyRecorded {
				select {
				case timeoutEvents <- node.ID:
				default:
				}
			}
			return nil
		})).Sugar()
		node.logger = logger
		node.Consensus.Logger = logger
		node.LoseMessages(func(message *smartbftprotos.Message) bool {
			return dropPrepares.Load() && message.GetPrepare() != nil
		})
	}

	startNodes(nodes, network)
	nodes[0].Submit(Request{ID: "approved-qc-recovery", ClientID: "mwvn-ingress"})

	observed := make([]uint64, 0, len(nodes))
	deadline := time.After(5 * time.Second)
	for len(observed) < 2 {
		select {
		case nodeID := <-timeoutEvents:
			observed = append(observed, nodeID)
		case <-deadline:
			t.Fatalf("observed prepare timeouts on nodes %v; expected at least two", observed)
		}
	}

	dropPrepares.Store(false)
	waitForEqualDeliveries(t, nodes, 15*time.Second)
	t.Logf("scenario=prepare-loss-and-recovery configured_prepare_timeout=%s timed_out_nodes=%v result=committed-after-view-change", prepareTimeout, observed)
}
