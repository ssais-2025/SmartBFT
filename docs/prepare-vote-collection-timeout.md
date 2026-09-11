# Prepare vote collection timeout

This fork adds `types.Configuration.PrepareVoteCollectionTimeout` with a default of five minutes.

The value is a **maximum PREPARE-vote collection time**, measured independently by each replica from the moment it enters `processPrepares` after accepting and persisting a proposal. It is not a mandatory delay:

- when the replica receives the required matching PREPARE votes before the deadline, it immediately signs and broadcasts COMMIT;
- when the deadline expires first, it logs the timeout, complains about the current view with `stopView=true`, and returns `ABORT` so SmartBFT's existing view-change path can recover;
- when the view is aborted for another reason, the local timer is stopped and no timeout complaint is emitted.

The timeout applies only to PREPARE collection. This change does not add a COMMIT collection timeout and does not change `RequestBatchMaxInterval`, request forwarding, leader heartbeats, view-change timers, quorum computation, message formats, or signature behavior.

Every validator should use the same positive configuration value. `Configuration.Validate` rejects zero and negative values. Directly constructed internal test views retain zero as a disabled timer to avoid changing helpers that bypass public configuration validation.

## Configuration

```go
config := types.DefaultConfig
config.SelfID = validatorID
config.PrepareVoteCollectionTimeout = 5 * time.Minute
```

Use a short value only in automated tests. Five minutes are real wall-clock time in a deployed validator.

## MWVN interpretation

This implements the clarified MWVN behavior: continue immediately at the PREPARE threshold, with five minutes as the maximum wait. It does not implement QC batching and does not claim to reproduce any separate rolling/sliding-window semantics in the paper.

## Operational caution

This fork-level change requires protocol qualification. A timeout expiring at different replicas can cause some replicas to join view change while others complete the proposal; SmartBFT's existing prepared-state and view-change logic remains responsible for safety. Unit, integration, partition, recovery, and race tests must pass before the change is used outside the experiment.
