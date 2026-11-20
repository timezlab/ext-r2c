# The remote's thread is keyed by owner and context

**Status:** accepted, 2026-11-20.

## Context

To resume an interrupted graph, the A2A adapter maps protocol ids to an internal thread. The
official A2A LangGraph sample uses the bare `contextId` as `thread_id`. Read from the a2a-sdk
1.3.1 wheel: the client **may choose** `contextId` on its first message, and the TaskStore is
scoped by owner (`OwnerResolver`), but LangGraph checkpoints are not scoped at all.

## Decision

- `thread_id = f(owner, contextId)`, where `owner` comes from the same `OwnerResolver` as the
  TaskStore. Never the bare `contextId`.
- **One unfinished task per context.** The adapter refuses a second task in a context that has
  one open, because both would write to one thread.
- A follow-up (same `contextId`, no `taskId`) opens a new task on the same thread; that is core
  A2A.
- On MCP, which has no task id, the stopping point travels in `requestState`, sealed and expiring
  through the MCP SDK's `RequestStateBoundary`.

## Alternatives

- **Bare `contextId`** (the sample). Two users who pick the same `contextId` read and resume
  one conversation.
- **Ignore the client's `contextId` and always generate one.** Breaks follow-ups and differs
  from what the SDK accepts.

## Consequences

- **Better:** no cross-user leak through the checkpointer, whatever ids clients choose.
- **Worse:** the adapter must know the owner resolver; a remote that changes its identity model
  orphans old threads.
- **Must now be true:** a remote uses a durable checkpointer and TaskStore to survive restarts,
  and SHOULD document how long it keeps a context.
