# Phase 1.3.2.2: Unify PatternChain Construction

## Why this phase exists

`phase1.3.3_voicings_comp.md` introduces `_CompContext` so `MIDI` and `Comp` share one pattern creation API with different lifecycle policy.

Today, chain setup logic is duplicated across:

- `note(...)` (standalone path)
- `_midi_n(...)` (MIDI path)

This duplication makes lifecycle and root/scale behavior drift likely as we add `_CompContext`.

## API direction (explicit decision)

- global `ts.n()` and global `ts.note()` will be removed (no deprecation period required).
- Canonical standalone path becomes `ts.comp().note(...)` / `ts.comp().n(...)`.
- `MIDI.n(...)` remains for voice-bound reactive use.

## Goal

Create one internal construction pipeline for `PatternChain` so all contexts build chains consistently, then apply context-specific policy after construction.

## Scope

### 1. Extract shared chain construction into one internal builder

- parse mini-notation
- instantiate `PatternChain`
- attach parsed `Pattern`
- set shared chain metadata (`_cycle_beats`, `_parent_voice`, bus metadata, state exposure)

**Important:** Builder does NOT call `pat.start()` or `_register_chain()`. Those are lifecycle concerns handled in 1.3.2.3.

### 2. Keep context-specific concerns outside the builder

- scale/root/base-degree resolution
- lifecycle policy (auto/manual trigger)
- context-owned tracking fields

### 3. Update call paths to use builder

- `MIDI.n(...)`
- `_CompContext.note(...)` (for phase 1.3.3)

### 4. Remove global `ts.n(...)` and global `ts.note(...)` APIs

Remove these and their docs/usages in active phase plans.

### 5. Remove legacy pattern systems

Once all paths use `PatternChain` via the unified builder, remove:

- `_midi_patterns` dict (line ~2720)
- `_update_midi_patterns()` function
- `_update_patterns()` function (if unused)
- Related cleanup in `stop_patterns_for_voice()` for `_midi_patterns`

**Identify dependencies first:** Before removal, verify no active code paths still use `_midi_patterns`. Current analysis shows `_midi_n()` already creates `PatternChain` and uses `_chain_registry`, so `_midi_patterns` appears to be legacy dead code.

### 6. Consolidate update loop

After removing legacy systems, `update()` should simplify to:

```python
def update():
    _base_update()
    _update_pattern_chains()  # Single update path
    _internal_tick += 1
```

## Non-goals

- Do not change event timing semantics in this phase.
- Do not change parser behavior in this phase.
- Do not implement full lifecycle state machine here (handled in 1.3.2.3).

## Recommended implementation order

1. Build internal constructor helper (`_build_pattern_chain`).
2. Switch `_midi_n()` to use the builder; verify no behavior regression.
3. Switch standalone `note()` to use the builder (temporary, before removal).
4. Identify and audit any remaining `_midi_patterns` usage.
5. Remove `_midi_patterns`, `_update_midi_patterns()`, `_update_patterns()` if safe.
6. Remove global `ts.n(...)` and global `ts.note(...)` API entry points.
7. Update examples to `ts.comp(...).n(...).trigger()` (phase 1.3.3 target shape).

## Verification checklist

- [ ] `MIDI.n("0 2 4")` still constructs and plays as expected
- [ ] Constructed chain fields are consistent regardless of caller path
- [ ] No duplicate constructor logic remains
- [ ] global `ts.n(...)` and global `ts.note(...)` are no longer available
- [ ] `_midi_patterns` dict is removed
- [ ] `_update_midi_patterns()` function is removed
- [ ] `_update_patterns()` function is removed (if applicable)
- [ ] `update()` only calls `_update_pattern_chains()` for pattern updates
- [ ] `stop_patterns_for_voice()` no longer references `_midi_patterns`
