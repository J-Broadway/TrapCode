# Phase 1.3.3.1: Composite Design Pattern Contract

## Goal

Unify `ts.comp` and `ts.MIDI` under one scalable composition model that supports:

- inheritance from context -> pattern -> instance
- overlap/multi-instance playback
- per-instance lifecycle control
- reusable mini-notation timing semantics for future attribute modulation

`MIDI` remains voice-bound (auto lifecycle), while `Comp` remains manual lifecycle.

## Architectural Decision (locked)

Use Composite + Cascading Policy:

- `Comp`/`MIDI` = context node (defaults + child registry)
- `PatternChain` = pattern owner/controller node
- `PatternInstance` = leaf runtime node (actual runner)

The update loop ticks `PatternInstance` objects.

## Scope Inheritance Contract

Any trigger/policy option resolves with precedence:

1. explicit instance arg (e.g. `trigger(...)`)
2. pattern override (e.g. `comp.n(..., velocity=...)`)
3. context default (e.g. `ts.comp(..., velocity=...)`)
4. library default

This rule is global and applies to all future options.

## Context Defaults (current + planned)

| kwarg | default | notes |
|---|---|---|
| octave | 4 | Default octave for note-name root parsing |
| scale | None | Context scale (`"c:minor"`) |
| root | None | Root override for implicit scales |
| cycle | 4 | Default pattern cycle in beats |
| velocity | 80 | Default voice velocity |
| length | None | Default note length override |
| pan | 0.0 | Default pan |
| output | 0 | Default output port |
| fcut | 0.0 | Default Mod X / cutoff |
| fres | 0.0 | Default Mod Y / resonance |
| finePitch | 0.0 | Default microtuning offset |
| color | 0 | Default note color/channel |
| releaseVelocity | 0 | Default release velocity |
| parent | None | Voice binding (Comp only; MIDI already bound) |
| bypass | False | Output suppression policy (state still ticks) |

## Pattern API Shape (recommended)

Support both constructor kwargs and fluent setters, with one internal policy map.

**Implementation phasing:** Deliver in **two slices** (see [Implementation phasing](#implementation-phasing-locked) below).

- **Slice A (core):** `Comp` / `MIDI` and `PatternChain` use **constructor kwargs** (and existing pattern-level kwargs) for voice attributes — **static numeric values** for precedence / `Policy` / tests. No fluent mini-notation strings on context or pattern yet.
- **Slice B (fluency):** Add **fluent temporal setters** (`comp.velocity("50 80")`, `pat.velocity("80 70 60")`, etc.), unified parser core, coercers, `?` / `None` / `Null(attr)` for **Phase-1 Attribute Scope** only.

### Usage mock (public API) — full target after Slice B

```python
comp = ts.comp(scale="c:minor", velocity=80)
comp.velocity("50 80").output("0 1?")  # fluent dynamic defaults (Slice B)

pat = comp.n("0 1 2 3", cycle=2)       # inherits comp defaults
pat2 = comp.n("3 2 1 0", scale="d:minor", velocity="20 [30 40] 100")
```

### Slice A usage (intermediate)

```python
comp = ts.comp(scale="c:minor", velocity=80, output=0)
pat = comp.n("0 1 2 3", cycle=2, velocity=72)
pat.trigger(cut=False)
```

### Fluent return contract (locked)

When fluent setters exist (**Slice B**), the following applies:

- Context fluent setters on `Comp`/`MIDI` return the same context object (`self`)
- Pattern fluent setters on `PatternChain` return the same pattern object (`self`)
- (If exposed) instance mutators on `PatternInstance` return the same instance (`self`)

This ensures stable chainability:

```python
comp = ts.comp(scale="c:minor").velocity("50 80").output("0 1?")
pat = comp.n("0 1").velocity("80 70 60")  # pattern-level override of inherited comp defaults
```

Inheritance order remains:

1. instance explicit args
2. pattern overrides
3. context defaults
4. library defaults

### Trigger/lifecycle mock (public API)

```python
pat.trigger(loop=False, direction="forward", cut=False)  # spawn runner
pat.trigger(loop=False, direction="forward", cut=False)  # spawn another

for inst in pat.instances:          # oldest -> newest
    if inst.phase > 0.5:
        inst.stop()                 # per-instance control
```

### Composite iteration mock (public API)

```python
for pattern in comp.patterns:
    if pattern.running():
        pattern.pause()  # default: pause all active instances in owner
```

## PatternInstance Contract

- stable per-owner integer `inst.id` (`1,2,3...`)
- `inst.created_at_tick` from engine tick at spawn
- explicit lifecycle state: `created|running|paused|stopped`
- runtime internals in `inst.runtime` (phase/tick/durations/etc.)
- convenience read proxies allowed (`inst.phase`, `inst.tick`)

Owner-level state on `PatternChain` is derived:

- `running()` => any owned instance running
- `paused()` => no running and at least one paused
- `active()` => any owned instance running or paused

`active` is exposed as a public property at both `PatternChain` and `Comp` levels:

- `pat.active` => any instance in that pattern is running or paused
- `comp.active` => any pattern in that comp has `active == True`

## Composite aggregation helper (locked)

To keep future composite methods scalable, implement shared internal helpers:

- `_any_child(predicate)`
- `_all_children(predicate)`
- `_map_children(fn)`

Derived state properties should use these helpers instead of custom loops per method.
This prevents repeated boilerplate when adding future state predicates/actions.

## Mini-Notation Strategy (no duplicate parsers)

Do not create separate full parsers for context vs pattern attributes.
Use one temporal parser core + per-attribute value coercers.

- parser core handles timing/sequence operators (`[]`, `!`, `?`, etc.)
- coercers adapt values for specific targets:
  - velocity/output/pan/fcut/fres...
  - root/scale parsing and note-name normalization
  - nullable domains (`None`) where allowed

This keeps temporal semantics unified across all attributes.

## Probability Operator (`?`) Contract

`?` is treated as a native Strudel probability/degrade operator.
For attribute patterns, degraded events resolve to attribute-specific null behavior.

Contract for value `x?`:

- emit `x` with probability `p` (default 0.5)
- otherwise emit `Null(attr)` (not `hold`)

Contract for literal `None`:

- `None` is explicit deterministic `Null(attr)` (no probability)
- `None?` is invalid in phase 1 (ambiguous double-null syntax)

### `Null(attr)` mapping (phase 1 target)

| Attribute | Null behavior |
|---|---|
| velocity | `0` (silent note) |
| length | `drop_note` |
| output | `drop_note` |
| pan | `0` (center) |
| fcut | `0` |
| fres | `0` |
| finePitch | `0` |
| color | default color (`0`) |
| releaseVelocity | default (`0`) |

Notes:

- `drop_note` means the note event is not emitted for that step.
- For users, `drop_note` is equivalent to a rest at emit time (e.g. output degrade behaves like no-note for that step, similar to `~` in note patterns).
- Structural attributes (`scale`, `root`, `octave`, `cycle`) defer `?` support to a follow-up phase unless explicit per-attribute policy is defined.

## Phase-1 Attribute Scope (locked)

Phase-1 mini-notation/coercer modulation includes:

- `velocity`
- `length`
- `output`
- `pan`
- `fcut`
- `fres`
- `finePitch`
- `color`
- `releaseVelocity`

Deferred to follow-up phase:

- `scale`
- `root`
- `octave`
- `cycle`

**Current runtime note (`cycle`):** In `trapscript.py` today, cycle length is a **single scalar** beats-per-cycle per chain (optionally **dynamic** via callable/knob, **latched at cycle boundaries** in `Pattern.tick`). There is **no** mini-notation sequencer for cycle (e.g. Strudel-style **polymetric** step lengths like `"2 2 1"` as a `.cycle(...)` pattern). Supporting sequenced / probabilistic / nullable `cycle` is **out of scope for Phase 1** and implies additional temporal design in a follow-up phase.

## Emit Pipeline Gate Order (locked)

For each note step:

1. Resolve attribute values for the step.
2. Apply `?` degrade to produce concrete or `Null(attr)` values.
3. If `length` or `output` resolves to `drop_note`, abort note emission immediately.
4. Otherwise emit note with resolved attributes.

This keeps note suppression deterministic and avoids creating-and-discarding voice events.

## Typed literal support requirement

Target examples like:

```python
"0 1 2 [None 3]!2 4"
```

must be supported through parser extension points (typed literals + coercers), not ad-hoc regex hacks in each feature.

Contract:

- parser should emit literal token values including `None` for phase-1 modulated attributes
- coercer maps `None` -> `Null(attr)` deterministically for phase-1 modulated attributes
- structural attrs keep `None` and `?` support deferred until explicitly enabled in follow-up phase
- clear errors for unsupported token/domain combinations

## Backend mock (critical internal interfaces)

```python
class Policy:
    # immutable/resolved snapshot for a runner
    loop: bool
    direction: str
    cut: bool
    bypass: bool
    velocity: object
    output: object

class PatternChain:
    defaults: dict           # owner-level overrides
    instances: OrderedDict[int, PatternInstance]
    def resolve(self, trigger_overrides: dict) -> Policy: ...
    def trigger(self, **kwargs) -> "PatternChain": ...

class PatternInstance:
    id: int
    created_at_tick: int
    state: str
    runtime: object
    policy: Policy
```

## Implementation phasing (locked)

| Slice | Focus | Out of scope until done |
|------|--------|-------------------------|
| **A — Core composite** | `PatternInstance`, instance registry, tick targets `PatternInstance`, `Policy` + `resolve()`, trigger kwargs (`loop`, `direction`, `cut`), `pat.instances`, `comp.patterns`, aggregation helpers, **bypass** cascading, tests with **scalar** kwargs | Fluent attribute strings on context/pattern; `?` on attributes; `None` in attribute mini-notation; typed-literal parser extension for modulated attrs |
| **B — Temporal fluency** | Fluent setters on `Comp`/`MIDI`/`PatternChain`; one temporal parser core + per-attribute coercers; `?`, literal `None` → `Null(attr)`, emit pipeline steps 2–3 for phase‑1 attributes; validation checklist items that require parser | (unchanged) structural `scale`/`root`/`octave`/`cycle` mini-notation — still deferred per [Resolved decisions](#resolved-decisions) |

**Rationale:** Validate ownership, overlap, and precedence on a small API surface first; layer Strudel-style attribute strings on top of a working `resolve()` / `Policy` path so parser work is not reworked when cascade rules change.

## Implementation Sequence

**Slice A — Core composite**

1. Introduce `PatternInstance` and owner instance registry in `PatternChain`
2. Move update loop tick target from chain runtime -> instance runtime
3. Implement policy resolution precedence (instance > pattern > context > default) using **scalar** context/pattern/trigger values
4. Add trigger options (`loop`, `direction`, `cut`) on top of instance model
5. Add per-instance/public iteration APIs (`pat.instances`, `comp.patterns`)
6. Add bypass cascading semantics and tests for Slice A checklist items

**Slice B — Temporal fluency**

7. Extend parser core with typed literals (`None`) + coercer layer for **Phase-1 Attribute Scope** attributes
8. Implement fluent setters on `Comp`/`MIDI`/`PatternChain` that feed the same policy map
9. Full emit pipeline (including `?` degrade and `Null(attr)` gating) per [Emit Pipeline Gate Order](#emit-pipeline-gate-order-locked); complete remaining validation checklist rows that depend on parser

## Validation Checklist

**Slice A** covers inheritance, instances, triggers, ordering, lifecycle aggregates, and structural deferral. **Slice B** covers `?`, literal `None`, `None?`, and parser/domain errors for phase‑1 modulated attributes.

- context defaults inherit to patterns unless overridden
- pattern overrides inherit to instances unless overridden on trigger
- `trigger(cut=False)` creates additional instances without registry corruption
- `pat.instances` order is oldest -> newest
- per-instance stop/pause works while sibling instances continue
- `created_at_tick` is present and stable
- `running()/paused()/active()` reflect mixed instance states correctly
- `?` degraded attribute values resolve using `Null(attr)` mapping
- literal `None` resolves deterministically to `Null(attr)` mapping
- `None?` is rejected with clear error
- structural attrs reject/defer `?` semantics until explicitly enabled
- parser rejects invalid domain/value combinations with clear errors

## Resolved decisions

1. **Structural attrs (`scale`, `root`, `octave`, `cycle`) and `None` / `?`:** Explicitly **deferred past Phase 1** for this composite work. Phase 1 implements only **Phase-1 Attribute Scope** (velocity, length, output, pan, fcut, fres, finePitch, color, releaseVelocity) with the `?` and `None` contracts in this document. **When** and **how** structural fields gain mini-notation, nullability, and probability — including whether `cycle` becomes a **sequenced** pattern (polymetric lengths) versus staying **scalar-only** — will be specified in a **follow-up plan**, after Phase 1 composite + parser foundations are in place. This is **not** a blocker to start coding Phase 1.