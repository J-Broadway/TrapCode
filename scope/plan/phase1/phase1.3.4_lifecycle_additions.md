# Phase 1.3.4: Lifecycle Additions (`pause` / `play` / `stop` + trigger API)

## Purpose

Extend post-`1.3.3` lifecycle ergonomics for `PatternChain` and `ts.comp()` while keeping behavior deterministic and explicit.

This phase assumes:

- `1.3.2.2` unified construction is complete + legacy systems removed
- `1.3.2.3` lifecycle ownership is in `PatternChain` + `_CompContextMixin` introduced
- `1.3.3` `Comp` class is implemented (`MIDI` auto, `Comp` manual)

## Target API

```python
# PatternChain (pat) or PatternInstance (inst) — see semantics for each
.pause()   /  inst.pause()
.play()    /  inst.play()    # resume paused; pat.play() can cold-start if nothing paused
.stop()    /  inst.stop()
.restart() /  inst.restart()
.trigger(loop=False, direction='forward', cut=True)   # PatternChain only (spawns instances)
```

Trigger kwargs:

- `loop`: `False` (default), `True`
- `direction`: `forward` (default), `reverse`, `pingpong`, `pongping`
- `cut`: `True` (default), `False`

## Composite usage mock (owner + leaf instances)

`PatternChain` is the **composite** owner: one pattern definition (`comp.n(...)`), **many** `PatternInstance` runners. Address leaves by **`inst.id`** (monotonic integers per owner: `1, 2, 3, …`)

```python
comp = ts.comp(scale="c:minor")
pat = comp.n("0 1 2 3", cycle=2)

# Overlap: each trigger adds a runner (cut=False)
inst_a = pat.trigger(cut=False)
inst_b = pat.trigger(cut=False)

# Owner-level: every owned instance
pat.pause()       # all pause; phases preserved
pat.play()        # resume all paused instances (see `.play()` semantics)
pat.stop()        # all stop; playheads reset
pat.restart()     # stop all + trigger(**last_trigger_resolved); see `.restart()` for cut after stop

# Leaf-level: iterate instances (oldest → newest)
for inst in pat.instances:
    if inst.id == 2:
        inst.pause()
# inst.stop() / inst.pause() / inst.play() — per runner; inst.restart() = stop this + one new runner (see below)
```

- **Canonical iteration:** `pat.instances` (ordered). An optional `PatternChain.__iter__` may alias `iter(pat.instances)`; spec consumers should prefer **`pat.instances`** for clarity.

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

### `.restart()`

- **`pat.restart()` (owner):** Equivalent to `pat.stop()` (all owner-scoped instances), then **`trigger(**replay)`** where **`replay`** is the full **`last_trigger_resolved`** snapshot — including **`cut`**, **`loop`**, **`direction`**, and any future trigger kwargs from the **most recent** `pat.trigger(...)` (including MIDI auto-trigger on pattern create). **Do not** drop back to library-only defaults unless no prior trigger exists (see below).
- **Why this isn’t in tension with `cut=False`:** `restart()` always does **`stop()` first**, so there are **no** active instances left. A follow-up **`trigger(cut=False)`** has **nothing left to overlap**, so you still get **exactly one** new runner — same observable outcome as **`trigger(cut=True)`** in that situation. Replaying **`cut`** keeps the call consistent with “same flags as last time” and avoids special cases in the implementation; the “collapse to one runner” effect comes from **`stop()`**, not from overriding `cut`.
- **No prior `trigger()` on this `pat`:** If the chain has never been explicitly triggered (rare for `Comp`; `MIDI` auto-trigger counts as a trigger and must populate the replay snapshot), `replay` falls back to resolving **`trigger()`** with **no** extra kwargs — i.e. cascading policy (Comp → Pattern → library default) the same as a first-time `trigger()`.
- **Implementation note:** `PatternChain` stores a **`last_trigger_resolved`** (name TBD) snapshot whenever `trigger()` runs, after full policy merge — so `restart()` is deterministic and matches user expectations (“play it again the same way”).
- **`inst.restart()` (leaf):** Restarts **the same instance in-place** — keeps **`inst.id`** stable and the user’s reference valid. Semantics: reset runtime to beginning (**phase = 0**, tick state cleared), transition state back to **`running`**, using the **`spawn_resolved`** policy already latched on this instance (`loop`, `direction`, etc.). **Other** overlapping instances on the same `pat` are **not** affected.
- **Each `PatternInstance` stores** its own **`spawn_resolved`** (or equivalent) at creation time. This serves two purposes: (1) **`inst.restart()`** replays the same settings without re-resolving the cascade, and (2) each instance’s policy is independent of **`last_trigger_resolved`** on the chain (which tracks only the **latest** `pat.trigger()`).

### `.trigger(loop=False, direction='forward', cut=True)`

- `cut=True`: stop all active owner-scoped runners for this chain/context, then start exactly one new runner using provided `loop` + `direction`
- `cut=False`: keep active owner-scoped runners and add one more (overlap behavior)
- Trigger-time values are latched per runner for deterministic playback

## Trigger Contract Notes

### `loop`

- `False` (library default for `Comp`): auto-stop when one directional phrase completes
- `True` (library default for `MIDI`): repeat indefinitely until explicit stop/release lifecycle action

**Context-specific defaults:** `MIDI` defaults to `loop=True` because voice-bound patterns must loop continuously until parent voice release — matching existing behavior where MIDI patterns play indefinitely. `Comp` defaults to `loop=False` for one-shot semantics. These context defaults participate in normal cascading resolution (explicit trigger arg > pattern override > context default > library default).

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
- After each successful **`trigger()`**, update **`last_trigger_resolved`** (resolved `loop`, `direction`, `cut`, and any future trigger kwargs) for use by **`pat.restart()`** replay

### `PatternInstance` identity and timing

- `inst.id`: stable per-owner integer ID (no timestamp IDs)
- `inst.created_at_tick`: engine tick captured at spawn time
- `inst.spawn_resolved`: policy snapshot latched at **`trigger()`** spawn time — used by **`inst.restart()`** to replay **`loop` / `direction` / …** when resetting playback in-place (same `id`)
- No wall-clock creation field (`created_at_time`) in this phase

### Public instance surface

- `pat.instances` iterable returns active instances oldest first
- `comp.patterns` iterable returns owner patterns created from that `Comp` context
- Instance-level control is supported (`inst.pause()`, `inst.stop()`, etc.)
- Instance identity for user code: **`inst.id`** only (no `.number` alias in this phase)

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

- `created -> running` via activation after `trigger()` (runner starts)
- `running -> paused` via `pause()`
- `paused -> running` via `play()` on that instance (or `pat.play()` affecting it)
- `running|paused -> stopped` via `stop()`
- `running|paused|stopped -> running` via **`restart()`** on the same instance (resets runtime, keeps `id`)
- `stopped -> running` via **`trigger(...)`** on the **chain** creates a **new** instance — `play()` on a stopped instance is still a **no-op**

## Runtime Data Layout

- Keep mutable playback internals in `inst.runtime` (not flattened onto owner)
- Store values like phase/cycle/tick/duration caches in runtime object
- Provide convenience proxies on `PatternInstance` for common reads (`inst.phase`, etc.)
- Preserve clean separation:
  - instance metadata/policy (`id`, `state`, `spawn_resolved`, `created_at_tick`)
  - runtime evolution (`runtime.phase`, `runtime.tick`, timing buffers)

## Cascading Policy Model (Comp -> Pattern -> Instance)

Use hierarchical policy resolution so new API options scale without ad-hoc branching.

- `Comp` holds defaults policy (e.g., `loop=False`, `direction`, `cut`, `bypass`)
- `MIDI` holds defaults policy with `loop=True` (voice-bound patterns loop until release)
- `PatternChain` stores optional overrides (`None` means inherit from context)
- `PatternInstance` latches resolved policy snapshot at `trigger()` time

Resolution order for any option:

1. explicit trigger arg (instance scope)
2. pattern override (`comp.n(..., option=...)`)
3. comp default (`ts.comp(..., option=...)`)
4. library default

### Bypass in cascading policy

**Default:** `bypass=False` at the **library** level; set explicitly on `ts.comp(...)`, `comp.n(...)`, or `trigger(..., bypass=...)` when needed.

**Meaning:** After resolution (same order as above: instance → pattern → comp → library), a **true** `bypass` means **do not emit voice / MIDI note output** for that instance’s playback steps. The pattern **engine still runs**: playhead, phase, step, bus/state, and `changed()`-style signals can advance so scripts can **observe** the pattern in the background and drive other logic. **Do not** read “events still fire” as “notes still go out” — logical **steps** advance; **audible output** is gated off.

**Scopes (composite):**

- **`ts.comp(..., bypass=True)`** — all patterns and **all** instances spawned under that comp **inherit** effective bypass unless a lower scope overrides it.
- **`comp.n(..., bypass=...)`** — pattern-level override for every runner on that `PatternChain` (unless instance overrides).
- **Instance level (does not break architecture):** each `PatternInstance` resolves **effective** `bypass` with the usual precedence (**trigger** → **pattern** → **comp** → **library**). So a comp-wide `bypass=True` flows to every instance; a **single** instance can still **opt out** with **`trigger(..., bypass=False)`** at spawn, or **flip** bypass later (runtime mutator on `inst`, e.g. set/clear a leaf override) so one runner can be audible while siblings stay bypassed — and vice versa if comp is `False` but **`trigger(..., bypass=True)`** for one runner only.

**Implementation note:** store a **latched** value from cascade at spawn (`spawn_resolved`) plus an optional **runtime override** on the instance (`inst._bypass_override` or `None`) with a clear rule: **override wins when set**, else use latched effective.

**Not in scope for `bypass`:** lifecycle. **`trigger`**, **`pause`**, **`stop`**, **`cut`**, and **`restart()`** behave the same regardless of `bypass`; only the **emit path** (notes to the host) is suppressed when resolved true.

**Relation to `mute` (implementation detail):** both can silence output; keep **one** resolved `bypass` flag in policy and document how existing **`mute`** on `PatternChain` composes (e.g. either is sufficient to suppress notes — exact OR/AND rule should match `trapscript.py` when wired).

## What was missing (now captured)

1. Clear difference between `play()` and `trigger()`
2. Behavior of `play()` when called from `stopped`
3. Overlap implementation ownership and cleanup rules
4. `loop=False` completion boundary definition
5. Idempotency requirements across all lifecycle methods
6. Explicit state transitions for testing and debugging
7. Cascading policy inheritance across comp/pattern/instance scopes

## Compatibility Notes

- `MIDI` context auto policy is `trigger(loop=True, cut=True)` on creation, then `stop()` on parent release. The `loop=True` default preserves existing behavior where MIDI patterns play continuously until voice release.
- `MIDI` chains still expose and respect full `PatternChain` lifecycle methods (`pause()`, `play()`, `stop()`) just like `Comp`. Users can override `loop` per-pattern or per-trigger if needed.
- `Comp` context remains manual and can use all trigger options directly. `Comp` defaults to `loop=False` for one-shot semantics.

## Pre-implementation decision gate

Ownership model is now selected:

- Maintain a multi-runner list owned by a single chain/context scope
- `cut=True` and `.stop()` apply to owner-scoped active runners
- More granular `.stop(...)` targeting API is intentionally deferred to a follow-up

## Verification Checklist

- `pause()` preserves phase and `play()` resumes from same phase
- `stop()` resets phase to 0 and halts output
- `pat.restart()` stops all then **`trigger(**last_trigger_resolved)`** (includes **`cut`**); after a full stop, **`cut=False` vs `cut=True`** yields one new runner either way — MIDI auto-trigger must seed `last_trigger_resolved`
- `inst.restart()` resets runtime in-place (phase = 0), keeps **same `inst.id`**, re-enters **`running`** using **`spawn_resolved`**; overlapping siblings unchanged
- `trigger(loop=False, direction='forward', cut=True)` behaves deterministically
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
- MIDI auto-trigger uses `loop=True` — patterns loop until voice release, matching pre-composite behavior
- `Comp` trigger defaults to `loop=False` — one-shot unless explicitly overridden
- repeated lifecycle calls are safe (idempotent where expected)

## API Enhancements

- `status()` helper (`running/paused/stopped`)
- `playhead()` helper (phase, cycle, step snapshot)
- debug tracing for trigger option transitions
