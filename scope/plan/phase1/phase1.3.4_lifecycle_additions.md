# Phase 1.3.4: Lifecycle Additions (`pause` / `play` / `stop` + trigger API)

## Purpose

Extend post-`1.3.3` lifecycle ergonomics for `PatternChain` and `ts.comp()` while keeping behavior deterministic and explicit.

This phase assumes:

- `1.3.2.2` unified construction is complete + legacy systems removed
- `1.3.2.3` lifecycle ownership is in `PatternChain` + `_CompContextMixin` introduced
- `1.3.3` `Comp` class is implemented (`MIDI` auto, `Comp` manual)

## Target API

```python
.pause()                     # Pause pattern, keep current phase position
.play()                      # Resume from paused position (not equivalent to trigger)
.stop()                      # Stop and reset to cycle start (phase = 0)
.trigger(loop=False, direction='forward', cut=True)
```

Trigger kwargs:

- `loop`: `False` (default), `True`
- `direction`: `forward` (default), `reverse`, `pingpong`, `pongping`
- `cut`: `True` (default), `False`

## Semantics (explicit contract)

### `.pause()`

- Halts ticking/output generation
- Preserves phase position and step context
- Keeps chain identity/state available for inspection and resume
- Safe/idempotent if already paused

### `.play()`

- Resumes a paused chain from preserved phase
- No phase reset
- If already running, no-op
- If stopped (reset state), call `trigger(cut=True)` (defaults apply)

### `.stop()`

- Stops playback and resets to beginning (`phase=0`)
- Clears "currently running" runtime state
- Should not duplicate cleanup side effects on repeated calls
- If bus/history behavior differs from pause, document clearly

### `.trigger(loop=False, direction='forward', cut=True)`

- `cut=True`: stop all active owner-scoped runners for this chain/context, then start exactly one new runner using provided `loop` + `direction`
- `cut=False`: keep active owner-scoped runners and add one more (overlap behavior)
- Trigger-time values are latched per runner for deterministic playback

## Trigger Contract Notes

### `loop`

- `False` (default): auto-stop when one directional phrase completes
- `True`: repeat indefinitely until explicit stop/release lifecycle action

### `direction`

- `forward`: traverse phrase start -> end
- `reverse`: traverse phrase end -> start
- `pingpong`: forward then backward
- `pongping`: backward then forward
- For `loop=False`, completion boundaries:
  - `forward` / `reverse`: stop after one traversal
  - `pingpong` / `pongping`: stop after forward+backward pair (two traversals)

### `cut`

- Owner-scoped policy, not global
- `True` is equivalent to "stop owner-scoped active runners, then play one"
- `False` permits overlapped runners within the same owner scope

## Ownership + Instance Model

- `PatternChain` is the owner/controller
- Each `trigger()` creates or replaces `PatternInstance` runners based on `cut`
- `Comp` tracks created owner patterns for top-level iteration (`comp.patterns`)
- Runtime update loop ticks active instances, not just a single chain runtime

### `PatternChain` responsibilities

- Keep ordered active instance collection (`pat.instances`) in oldest -> newest creation order
- Maintain per-owner monotonic instance IDs (integer: `1, 2, 3, ...`)
- On `trigger(cut=True)`: stop all owner-scoped active instances, then spawn exactly one
- On `trigger(cut=False)`: spawn one additional active instance
- On `pause()` / `stop()` with no selector args: apply to all owner-scoped active instances

### `PatternInstance` identity and timing

- `inst.id`: stable per-owner integer ID (no timestamp IDs)
- `inst.created_at_tick`: engine tick captured at spawn time
- No wall-clock creation field (`created_at_time`) in this phase

### Public instance surface

- `pat.instances` iterable returns active instances oldest first
- `comp.patterns` iterable returns owner patterns created from that `Comp` context
- Instance-level control is supported (`inst.pause()`, `inst.stop()`, etc.)

## Suggested Internal State Model

- Owner-level (`PatternChain`) state is derived from instances:
  - `running()` is `True` if any owned instance is running
  - `paused()` is `True` if no instance is running and at least one is paused
  - `active()` is `True` if any owned instance is running or paused
- Instance-level (`PatternInstance`) state is explicit:
  - `created`
  - `running`
  - `paused`
  - `stopped`

Allowed transitions:

- `created -> running` via `trigger()` / `play()` (if chosen)
- `running -> paused` via `pause()`
- `paused -> running` via `play()`
- `running|paused -> stopped` via `stop()`
- `stopped -> running` via `trigger(...)` (new instance spawn)

## Runtime Data Layout

- Keep mutable playback internals in `inst.runtime` (not flattened onto owner)
- Store values like phase/cycle/tick/duration caches in runtime object
- Provide convenience proxies on `PatternInstance` for common reads (`inst.phase`, etc.)
- Preserve clean separation:
  - instance metadata/policy (`id`, `state`, `loop`, `direction`, `created_at_tick`)
  - runtime evolution (`runtime.phase`, `runtime.tick`, timing buffers)

## Cascading Policy Model (Comp -> Pattern -> Instance)

Use hierarchical policy resolution so new API options scale without ad-hoc branching.

- `Comp` holds defaults policy (e.g., `loop`, `direction`, `cut`, `bypass`)
- `PatternChain` stores optional overrides (`None` means inherit from `Comp`)
- `PatternInstance` latches resolved policy snapshot at `trigger()` time

Resolution order for any option:

1. explicit trigger arg (instance scope)
2. pattern override (`comp.n(..., option=...)`)
3. comp default (`ts.comp(..., option=...)`)
4. library default

### Bypass in cascading policy

- `bypass` is supported at comp, pattern, and instance scopes via same resolution order
- `Comp`-level `bypass` sets default behavior for all child patterns unless overridden
- Pattern-level override can opt in/out independent of comp default
- Instance-level override can diverge per trigger
- `bypass` controls output behavior; lifecycle control (`trigger`, `pause`, `stop`, `cut`) remains active
- Recommended in this phase: bypassed instances still tick/playhead state, but suppress note output

## What was missing (now captured)

1. Clear difference between `play()` and `trigger()`
2. Behavior of `play()` when called from `stopped`
3. Overlap implementation ownership and cleanup rules
4. `loop=False` completion boundary definition
5. Idempotency requirements across all lifecycle methods
6. Explicit state transitions for testing and debugging
7. Cascading policy inheritance across comp/pattern/instance scopes

## Compatibility Notes

- `MIDI` context auto policy is `trigger(cut=True)` on creation, then `stop()` on parent release.
- `MIDI` chains still expose and respect full `PatternChain` lifecycle methods (`pause()`, `play()`, `stop()`) just like `Comp`.
- `Comp` context remains manual and can use all trigger options directly.
- `Comp` context remains manual and can use trigger options directly.

## Pre-implementation decision gate

Ownership model is now selected:

- Maintain a multi-runner list owned by a single chain/context scope
- `cut=True` and `.stop()` apply to owner-scoped active runners
- More granular `.stop(...)` targeting API is intentionally deferred to a follow-up

## Verification Checklist

- `pause()` preserves phase and `play()` resumes from same phase
- `stop()` resets phase to 0 and halts output
- `trigger(loop=False, direction='forward', cut=True)` replays deterministically
- `cut=True` stops owner-scoped active runners before replay
- `cut=False` creates audible/state overlap without registry corruption
- `loop=False` stops at exact directional completion boundary
- `loop=True` continues until explicit stop/release lifecycle action
- directional traversal (`forward`, `reverse`, `pingpong`, `pongping`) follows contract
- `pat.instances` iteration order is oldest -> newest by creation
- instance IDs are per-owner monotonic integers and remain stable
- each instance stores `created_at_tick`
- owner-level derived state helpers reflect mixed multi-instance state correctly
- options resolve by scope precedence (instance > pattern > comp > library defaults)
- `bypass` inheritance/overrides behave consistently across scopes
- repeated lifecycle calls are safe (idempotent where expected)

## API Enhancements

- `status()` helper (`running/paused/stopped`)
- optional `playhead()` helper (phase, cycle, step snapshot)
- debug tracing for trigger option transitions
