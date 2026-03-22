# Phase 1.3.5: Composite + Lifecycle Implementation Specification

## Purpose

Define one authoritative implementation specification for the Phase 1 composite runtime and lifecycle work in `trapscript.py`.

This document merges and supersedes:

- `phase1.3.3.1_composite_design_pattern.md`
- `phase1.3.4_lifecycle_additions.md`

The target is an implementation-ready contract for:

- composite ownership (`Comp` / `MIDI` -> `PatternChain` -> `PatternInstance`)
- cascading policy resolution
- multi-instance playback
- lifecycle control (`trigger`, `pause`, `play`, `stop`, `restart`)
- future-safe temporal attribute modulation

`MIDI` remains voice-bound with automatic lifecycle behavior. `Comp` remains manually controlled.

## Goal

Unify `ts.comp` and `ts.MIDI` under one scalable model that supports:

- inheritance from context -> pattern -> instance
- overlap and multi-instance playback
- per-instance lifecycle control
- reusable mini-notation timing semantics for future attribute modulation

## Architectural Decision (locked)

Use Composite + Cascading Policy:

- `Comp` / `MIDI` = context node (defaults + child registry)
- `PatternChain` = pattern owner/controller node
- `PatternInstance` = leaf runtime node (actual runner)

The runtime update loop must tick `PatternInstance` objects, not a single chain runtime.

## Public API

### Target API

```python
# PatternChain (pat) or PatternInstance (inst) — see semantics for each
.pause()   /  inst.pause()
.play()    /  inst.play()
.stop()    /  inst.stop()
.restart() /  inst.restart()
.trigger(loop=False, direction="forward", cut=True)   # PatternChain only
```

Locked public predicate shape:

- `.active` is a read-only property on `PatternChain`, `Comp`, and `MIDI`
- `running()` and `paused()` remain method-shaped predicates on `PatternChain`
- this spec does not define `active()` as a method

### Composite usage

```python
comp = ts.comp(scale="c:minor")
pat = comp.n("0 1 2 3", cycle=2)

inst_a = pat.trigger(cut=False)
inst_b = pat.trigger(cut=False)

pat.pause()
pat.play()
pat.stop()
pat.restart()

for inst in pat.instances:  # oldest -> newest
    if inst.id == 2:
        inst.pause()
```

### Slice A usage

```python
comp = ts.comp(scale="c:minor", velocity=80, output=0)
pat = comp.n("0 1 2 3", cycle=2, velocity=72)
pat.trigger(cut=False)
```

### Full target after Slice B

```python
comp = ts.comp(scale="c:minor", velocity=80)
comp.velocity("50 80").output("0 1?")

pat = comp.n("0 1 2 3", cycle=2)
pat2 = comp.n("3 2 1 0", scale="d:minor", velocity="20 [30 40] 100")
```

### Fluent return contract (locked)

When fluent setters exist in Slice B:

- context fluent setters on `Comp` / `MIDI` return `self`
- pattern fluent setters on `PatternChain` return `self`
- instance mutators, if exposed, return `self`

## Scope Inheritance Contract

Any trigger or policy option resolves with precedence:

1. explicit instance arg, for example `trigger(...)`
2. pattern override, for example `comp.n(..., velocity=...)`
3. context default, for example `ts.comp(..., velocity=...)`
4. library default

This precedence rule is global and applies to all future options.

## Context Defaults

| kwarg | default | notes |
|---|---|---|
| octave | 4 | Default octave for note-name root parsing |
| scale | None | Context scale such as `"c:minor"` |
| root | None | Root override for implicit scales |
| cycle | 4 | Default pattern cycle in beats |
| velocity | 80 | Default voice velocity |
| length | None | Default note length override |
| pan | 0.0 | Default pan |
| output | 0 | Default output port |
| fcut | 0.0 | Default Mod X / cutoff |
| fres | 0.0 | Default Mod Y / resonance |
| finePitch | 0.0 | Default microtuning offset |
| color | 0 | Default note color / channel |
| releaseVelocity | 0 | Default release velocity |
| parent | None | Voice binding (`Comp` only; `MIDI` already bound) |
| bypass | False | Output suppression policy; state still ticks |
| loop | context-specific | `Comp=False`, `MIDI=True` |
| direction | `forward` | Default traversal direction |
| cut | `True` | Default owner-scoped trigger cut policy |

## Trigger Contract

### Signature

```python
pat.trigger(loop=False, direction="forward", cut=True)
```

Interpretation rule:

- the shown values describe effective defaults when those options are explicitly provided or when cascade resolves to them
- omitted trigger kwargs are not precedence layer 1
- only caller-supplied kwargs count as explicit instance overrides
- if a kwarg is omitted, resolution continues through pattern override -> context default -> library default

Return contract:

- `PatternChain.trigger(...)` returns the newly spawned `PatternInstance`
- chain-level fluent chaining is not provided through `trigger()`
- owner access remains available through the existing `pat` reference and `pat.instances`

Trigger-time values are latched per runner for deterministic playback.

### `loop`

- `False` is the default for `Comp`: auto-stop when one directional phrase completes
- `True` is the default for `MIDI`: repeat until explicit stop or parent voice release

Context-specific defaults are required:

- `MIDI` defaults to `loop=True` so voice-bound patterns preserve existing behavior and continue until release
- `Comp` defaults to `loop=False` for one-shot semantics

These context defaults still participate in normal cascading resolution:

1. explicit trigger arg
2. pattern override
3. context default
4. library default

### `direction`

Allowed values:

- `forward`
- `reverse`
- `pingpong`
- `pongping`

Traversal semantics:

- `forward`: traverse the phrase start -> end
- `reverse`: traverse the phrase end -> start
- `pingpong`: traverse forward, then backward
- `pongping`: traverse backward, then forward

For `loop=False`, completion boundaries are:

- `forward` / `reverse`: stop after one traversal
- `pingpong` / `pongping`: stop after a full forward-backward pair

### `cut`

- `True`: stop all active owner-scoped runners for that chain, then spawn exactly one new runner
- `False`: keep active owner-scoped runners and add one more

`cut` is owner-scoped, not global.

## Lifecycle Semantics

### `.pause()`

- halt ticking and output generation
- preserve phase position and step context
- keep chain and instance identity available for inspection and resume
- safe and idempotent if already paused
- calling `pause()` on an already stopped instance is a no-op

### `.play()`

- resume a paused chain or instance from preserved phase
- no phase reset
- `pat.play()` follows this order:
  1. if any owned instances are `paused`, resume every paused instance
  2. otherwise, if the active instance registry is empty, treat the owner as stopped and call `trigger(cut=True)` using normal cascading defaults, not `last_trigger_resolved`
  3. otherwise, if owned instances are present and all are already `running`, `pat.play()` is a no-op at the owner level
- a cold-start trigger performed internally by `pat.play()` still follows the normal trigger merge path and still updates `last_trigger_resolved` after that successful trigger
- for a stopped instance, `play()` remains a no-op

### `.stop()`

- stop playback and reset to the beginning (`phase = 0`)
- clear currently running runtime state
- avoid duplicate cleanup side effects on repeated calls
- apply to all owner-scoped active instances when invoked on `PatternChain`
- if stop-side effects differ from pause for bus or history state, that behavior must be documented and preserved consistently with existing runtime behavior
- repeated `stop()` on an already stopped instance is idempotent

### `.restart()`

#### `pat.restart()`

Equivalent to:

1. `pat.stop()` on all owner-scoped instances
2. `pat.trigger(**last_trigger_resolved)`

Rules:

- `last_trigger_resolved` must include `cut`, `loop`, `direction`, and future trigger kwargs
- the replay snapshot must be captured after full policy merge
- do not fall back to library-only defaults unless no prior trigger exists
- if no prior successful trigger exists, perform the same resolution as a first `pat.trigger()` with no extra kwargs so normal cascade applies
- `MIDI` auto-trigger on pattern creation counts as a trigger and must seed the replay snapshot

Replaying `cut=False` after `stop()` still produces exactly one new runner, because the stop has already removed all overlap candidates.

#### `inst.restart()`

- restart the same instance in place
- keep `inst.id` stable
- reset runtime to the beginning (`phase = 0`, tick state cleared)
- transition state back to `running`
- reuse that instance's `spawn_resolved` policy snapshot
- if the instance was previously stopped and removed from `pat.instances`, re-enter the owner's active instance registry before ticking resumes
- if the instance is already `running`, `inst.restart()` resets it to the beginning in place and leaves it in `running`
- do not affect sibling instances

## Composite Ownership Model

### Context level

- `Comp` and `MIDI` are context nodes
- each context owns child `PatternChain` objects
- both `Comp` and `MIDI` expose `.patterns` for top-level iteration over owned `PatternChain` objects
- both `Comp` and `MIDI` expose `.active`, which is true if any owned pattern is active

### Pattern level

`PatternChain` responsibilities:

- own an ordered active instance collection: `pat.instances`
- maintain per-owner monotonic instance IDs: `1, 2, 3, ...`
- spawn one new `PatternInstance` per `trigger()`
- insert the new instance into `pat.instances` before returning from a successful `trigger()`
- on `trigger(cut=True)`, stop all owner-scoped active instances before spawning
- on `trigger(cut=False)`, spawn one additional instance
- on `pause()` / `stop()` with no selectors, apply to all owner-scoped active instances
- update `last_trigger_resolved` after each successful trigger

Canonical iteration is `pat.instances`, ordered oldest to newest.

Membership rule:

- `pat.instances` contains active owner-scoped instances only
- active means `running` or `paused`
- stopped instances are removed from the active instance collection and no longer appear in `pat.instances`
- an in-place `inst.restart()` on a stopped instance re-enters that same object into the active collection without changing `inst.id`
- ordering is by increasing `inst.id`, which is the canonical oldest-to-newest rule for active instances
- re-entry after `inst.restart()` must preserve that ordering rule and must not append a lower `inst.id` after a newer sibling

### Instance level

Each `PatternInstance` is a leaf runtime node.

Public identity and timing:

- `inst.id`: stable per-owner integer ID
- `inst.created_at_tick`: engine tick captured at spawn time
- `inst.spawn_resolved`: full policy snapshot latched at spawn time
- no wall-clock creation field in this phase

## PatternInstance Contract

- explicit lifecycle state: `created | running | paused | stopped`
- runtime internals live in `inst.runtime`
- convenience read proxies are allowed, for example `inst.phase` and `inst.tick`

Mutable playback data belongs in `inst.runtime`, not on the owner:

- phase
- cycle position or count
- tick tracking
- duration caches
- direction traversal internals

Separation must remain clear:

- metadata and policy: `id`, `state`, `created_at_tick`, `spawn_resolved`
- runtime evolution: `runtime.phase`, `runtime.tick`, timing buffers, directional state

## Derived Owner State

Owner-level state on `PatternChain` is derived from instances:

- `running()` => any owned instance is running
- `paused()` => no instance is running and at least one is paused
- `active` => any owned instance is running or paused

The same aggregate concept applies at the context level:

- `pat.active` => any instance in that pattern is running or paused
- `comp.active` => any pattern in that context is active

## State Model

### Allowed transitions

- `created -> running` via trigger activation before `trigger()` returns
- `running -> paused` via `pause()`
- `paused -> running` via `play()`
- `running | paused -> stopped` via `stop()`
- `running | paused | stopped -> running` via `restart()` on the same instance
- `stopped -> running` via `trigger(...)` on the chain, which creates a new instance

`play()` on a stopped instance is intentionally a no-op.

Successful `trigger()` returns an instance that is already in `running` and already present in `pat.instances`. If a transient internal `created` state exists, it must not survive past the end of `trigger()`.

## Composite Aggregation Helpers (locked)

Implement shared helpers for scalable owner and context operations:

- `_any_child(predicate)`
- `_all_children(predicate)`
- `_map_children(fn)`

Derived state and future aggregate actions should use these helpers instead of open-coded loops.

## Cascading Policy Model

Use a hierarchical policy system so new options scale without ad-hoc branching.

- `Comp` holds defaults policy, including `loop=False`, `direction`, `cut`, `bypass`, and voice attributes
- `MIDI` holds defaults policy, including `loop=True` for voice-bound continuity
- `PatternChain` stores optional overrides; `None` means inherit from context
- `PatternInstance` latches a resolved policy snapshot at trigger time
- `cycle` remains a context / pattern playback setting owned by `PatternChain`, not a trigger-level policy field in Phase 1

For trigger kwargs specifically:

- caller-supplied kwargs are the only values that count as explicit instance overrides
- omitted kwargs must not be treated as hard-coded trigger defaults if a lower scope provides a value
- example: bare `pat.trigger()` under `MIDI` resolves `loop=True` from the `MIDI` context, not `False` from the illustrative signature

Resolution order for any option:

1. explicit trigger arg
2. pattern override
3. context default
4. library default

### Backend contract

```python
class Policy:
    loop: bool
    direction: str
    cut: bool
    bypass: bool
    velocity: object
    length: object
    output: object
    pan: object
    fcut: object
    fres: object
    finePitch: object
    color: object
    releaseVelocity: object

class PatternChain:
    defaults: dict
    cycle_config: object
    instances: OrderedDict[int, PatternInstance]
    def resolve(self, trigger_overrides: dict) -> Policy: ...
    def trigger(self, **kwargs) -> "PatternInstance": ...

class PatternInstance:
    id: int
    created_at_tick: int
    state: str
    runtime: object
    spawn_resolved: Policy
```

Locked split for `cycle`:

- `cycle` the configuration value means beats-per-cycle playback length inherited from context or pattern scope
- `runtime.cycle` means playhead cycle position or count inside instance runtime
- the configuration value is chain-authoritative in Phase 1 and is not stored inside `spawn_resolved`
- instances may keep runtime timing state derived from the chain's effective cycle configuration, but `spawn_resolved` does not own that configuration
- `inst.restart()` reuses the current chain-authoritative cycle configuration while resetting only instance runtime state

## Bypass Contract

Default: `bypass=False` at the library level.

Meaning:

- a resolved true `bypass` suppresses note emission for that instance
- the pattern engine still advances state, phase, playhead, bus updates, and inspectable values
- lifecycle behavior is unchanged by `bypass`

Scope behavior:

- `ts.comp(..., bypass=True)` sets inherited bypass for all child patterns and instances unless overridden
- `comp.n(..., bypass=...)` overrides at pattern scope
- `trigger(..., bypass=...)` overrides at instance scope

Implementation note:

- store the fully resolved value at spawn in `spawn_resolved`
- allow an optional runtime override on the instance if later mutability is exposed
- runtime override wins when set; otherwise use the latched resolved value

Relation to existing `mute`:

- resolved `bypass` and legacy `mute` compose as logical OR
- if either is true, note emission is suppressed for that step or runner
- lifecycle, state, and playhead advancement remain unaffected

## Runtime and Tick Model

- the top-level update loop still iterates registered `PatternChain` objects
- each `PatternChain.tick(...)` delegates runtime ticking to its owned active `PatternInstance` objects
- the chain is the owner and dispatcher; the instance is the actual runner
- trigger-time policy is latched per instance for deterministic playback

Direction and completion behavior belongs to instance runtime logic, not to shared owner state.

## Mini-Notation Strategy (no duplicate parsers)

Do not create separate full parsers for context attributes vs pattern attributes.

Use:

- one temporal parser core for timing and sequence operators
- per-attribute coercers for domain-specific adaptation

Parser core handles operators such as:

- `[]`
- `!`
- `?`

Coercers adapt values for:

- velocity
- length
- output
- pan
- fcut
- fres
- finePitch
- color
- releaseVelocity
- future scale and root normalization
- nullable domains where allowed

## Probability Operator (`?`) Contract

`?` is treated as a native degrade operator.

For a value `x?`:

- emit `x` with probability `p` where the default is `0.5`
- otherwise emit `Null(attr)`, not hold

For literal `None`:

- `None` is deterministic `Null(attr)`
- `None?` is invalid in Phase 1

## `Null(attr)` Mapping

| Attribute | Null behavior |
|---|---|
| velocity | `0` |
| length | `drop_note` |
| output | `drop_note` |
| pan | `0` |
| fcut | `0` |
| fres | `0` |
| finePitch | `0` |
| color | `0` |
| releaseVelocity | `0` |

Notes:

- `drop_note` means the note is not emitted for that step
- for users, `drop_note` is effectively a rest at emit time
- structural attributes defer `?` and nullable semantics to a later phase unless explicitly specified

## Phase-1 Attribute Scope (locked)

Included in Phase 1 temporal modulation:

- `velocity`
- `length`
- `output`
- `pan`
- `fcut`
- `fres`
- `finePitch`
- `color`
- `releaseVelocity`

Deferred:

- `scale`
- `root`
- `octave`
- `cycle`

Current runtime note on `cycle`:

- cycle length is currently one scalar beats-per-cycle value per chain
- it may be dynamic through callable or knob input
- it is latched at cycle boundaries
- sequenced or probabilistic `cycle` mini-notation is out of scope for Phase 1

## Emit Pipeline Gate Order (locked)

For each note step:

1. resolve attribute values for the step
2. apply `?` degrade to produce a concrete value or `Null(attr)`
3. if `length` or `output` resolves to `drop_note`, abort note emission immediately
4. otherwise emit the note with resolved attributes

This keeps suppression deterministic and avoids create-then-discard note behavior.

## Typed Literal Support Requirement

The parser must support typed literals through extension points, not ad-hoc regex patches.

Example target:

```python
"0 1 2 [None 3]!2 4"
```

Contract:

- parser emits literal token values including `None` for Phase-1 modulated attributes
- coercers map `None` to `Null(attr)` deterministically where supported
- structural attrs continue deferring `None` and `?` until explicitly enabled
- unsupported token or domain combinations must produce clear errors

## Implementation Phasing (locked)

| Slice | Focus | Out of scope until done |
|------|--------|-------------------------|
| **A — Core composite + lifecycle** | `PatternInstance`, instance registry, chain-to-instance tick delegation, `Policy` + `resolve()`, trigger kwargs (`loop`, `direction`, `cut`), lifecycle methods, `pat.instances`, `comp.patterns`, aggregation helpers, bypass cascading, tests with scalar kwargs | Fluent attribute strings on context / pattern; `?` on attributes; `None` in attribute mini-notation; typed literal parser extension for modulated attrs |
| **B — Temporal fluency** | Fluent setters on `Comp` / `MIDI` / `PatternChain`; one temporal parser core + per-attribute coercers; `?`, literal `None -> Null(attr)`, emit pipeline gating for Phase-1 attrs; parser-dependent validation items | Structural `scale` / `root` / `octave` / `cycle` mini-notation remains deferred |

Rationale:

- validate ownership, overlap, precedence, and lifecycle on a smaller API surface first
- layer parser and fluent temporal work on top of a stable `resolve()` and `Policy` path

## Implementation Sequence

### Slice A — Core composite + lifecycle

1. introduce `PatternInstance` and owner instance registry in `PatternChain`
2. move update loop responsibility from single chain runtime to per-instance runtime
3. implement full scalar `Policy.resolve()` precedence using context, pattern, and trigger values for all Slice A policy fields
4. add trigger-facing lifecycle options: `loop`, `direction`, `cut`, plus any Slice A trigger-scoped policy overrides such as `bypass`
5. add lifecycle methods and replay snapshots: `pause`, `play`, `stop`, `restart`, `last_trigger_resolved`, `spawn_resolved`
6. add public iteration APIs: `pat.instances`, `comp.patterns`, aggregate `active`
7. add bypass cascading semantics and tests

### Slice B — Temporal fluency

8. extend parser core with typed literals such as `None` and per-attribute coercers
9. implement fluent setters on `Comp`, `MIDI`, and `PatternChain` using the same policy map
10. implement full emit pipeline including degrade and `Null(attr)` gating

## Compatibility Notes

- `MIDI` auto policy on pattern creation is `trigger(loop=True, cut=True)`
- this preserves existing behavior where MIDI patterns continue until parent voice release
- `MIDI` still stops on parent release
- `MIDI` chains still expose the full lifecycle surface just like `Comp`
- `Comp` remains manual lifecycle and defaults to one-shot `loop=False`

## Unified Validation Checklist

### Core composite + lifecycle

- context defaults inherit to patterns unless overridden
- pattern overrides inherit to instances unless overridden on trigger
- `trigger(cut=False)` creates additional instances without registry corruption
- `pat.instances` order is oldest to newest
- per-instance pause and stop work while sibling instances continue
- `created_at_tick` is present and stable
- instance IDs are per-owner monotonic integers and remain stable
- `running()` and `paused()` methods, plus the `.active` property, reflect mixed instance states correctly
- `pause()` preserves phase and `play()` resumes from the same phase
- `stop()` resets phase to `0` and halts output
- `pat.restart()` stops all then calls `trigger(**last_trigger_resolved)`
- `inst.restart()` resets runtime in place, keeps the same `inst.id`, and re-enters `running`
- `trigger(loop=False, direction="forward", cut=True)` behaves deterministically
- `cut=True` stops owner-scoped active runners before replay
- `cut=False` creates audible and state overlap without registry corruption
- `loop=False` stops at the exact directional completion boundary
- `loop=True` continues until explicit stop or release lifecycle action
- directional traversal (`forward`, `reverse`, `pingpong`, `pongping`) follows the contract
- options resolve by scope precedence: instance > pattern > context > library
- bypass inheritance and overrides behave consistently across scopes
- MIDI auto-trigger uses `loop=True` and preserves pre-composite behavior
- `Comp` defaults to `loop=False` unless explicitly overridden
- repeated lifecycle calls are safe and idempotent where expected

### Parser and temporal fluency

- `?` degraded attribute values resolve using `Null(attr)` mapping
- literal `None` resolves deterministically to `Null(attr)`
- `None?` is rejected with a clear error
- structural attrs reject or defer `?` semantics until explicitly enabled
- parser rejects invalid domain and value combinations with clear errors

## Resolved Decisions

Structural attributes (`scale`, `root`, `octave`, `cycle`) and their `None` / `?` semantics are explicitly deferred past Phase 1 for this work.

Phase 1 includes only:

- `velocity`
- `length`
- `output`
- `pan`
- `fcut`
- `fres`
- `finePitch`
- `color`
- `releaseVelocity`

For those Phase-1 attributes, Slice B still includes:

- `?` degrade behavior
- literal `None -> Null(attr)`
- typed literal parser support
- emit-pipeline gating based on resolved null behavior

Future plans will define if structural fields gain:

- mini-notation
- nullability
- probability behavior
- sequenced `cycle` semantics such as polymetric lengths

## Out of Scope

- selector-based owner lifecycle methods such as targeted `pat.stop(...)`
- structural attribute modulation
- sequenced or probabilistic `cycle`
- alternate instance identity aliases such as `.number`
- wall-clock instance timestamps

## API Enhancements (non-blocking)

- `status()` helper for `running / paused / stopped`
- `playhead()` helper for phase, cycle, and step snapshots
- debug tracing for trigger option transitions
