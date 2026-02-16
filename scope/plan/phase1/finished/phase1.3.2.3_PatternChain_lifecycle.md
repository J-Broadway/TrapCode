# Phase 1.3.2.3: PatternChain Lifecycle & Registration Refactor

## Importance

**Critical**

This phase is required to support `phase1.3.3_voicings_comp.md` cleanly.

## Why this phase exists

Current lifecycle control is split across constructor paths (`note(...)`, `MIDI.n(...)`) and `PatternChain.stop()`.
That blocks a robust context-policy model where:

- `MIDI` auto-starts patterns
- `Comp` requires manual `.trigger()`

To scale cleanly, lifecycle must be owned by `PatternChain` itself.

### Current lifecycle issue (in code)

- standalone `note(...)` path creates `PatternChain`, then immediately calls:
  - `pat.start(_get_current_tick())`
  - `_register_chain(parent, chain, cycle, root)`
- `MIDI.n()` does the same (auto-start + auto-register).
- `PatternChain` currently has `.stop()` but no `.trigger()`.

Result: lifecycle control lives in construction functions, not on the chain object.

## Prerequisite

Complete `phase1.3.2.2_unify_chain_construction.md` first.

## Goal

Define and enforce one lifecycle contract:

- `created` -> `running` via `chain.trigger()`
- `running` -> `stopped` via `chain.stop()`
- Optional restart: `stopped` -> `running` via `chain.trigger()` (explicitly supported or disallowed; choose and document)

Lifecycle methods must be idempotent and safe.

Move lifecycle control to `PatternChain` so both contexts can share one pattern-construction path while choosing different start behavior:

- `ts.MIDI` context: auto-trigger after creation (current UX preserved)
- `ts.comp` context: user-triggered (`.trigger()` required)

## Scope

### 1. Add `PatternChain.trigger()`

- start underlying `Pattern` at current tick
- register chain in active registries
- no duplicate registration on repeated calls
- idempotent if already running/registered
- return `self` for chaining

### 2. Normalize `PatternChain.stop()`

- stop underlying `Pattern`
- unregister from active registries
- preserve bus cleanup and parent cleanup behavior
- safe repeated calls

### 3. Remove lifecycle side effects from construction

- constructors/builders create configured chain only
- no direct `pat.start(...)` in constructors
- no direct `_register_chain(...)` in constructors

### 4. Move start policy to context hook

For phase 1.3.3 template method:

- `MIDI._on_pattern_created(chain)` -> `chain.trigger()` (auto)
- `Comp._on_pattern_created(chain)` -> no-op (manual)

### 5. Refactor update loop and cleanup to use lifecycle methods

**Critical:** Remove ad-hoc registry manipulation from:

- `_update_pattern_chains()` — currently deletes from `_chain_registry` directly when `chain._running` is False
- `stop_patterns_for_voice()` — currently manipulates `_chain_registry` and `_voice_chain_map` directly

Both must route through `PatternChain.stop()` or shared lifecycle helpers. The update loop should never need to delete registry entries directly; chains should already be unregistered via their own `stop()` method.

Refactor targets:

```python
# _update_pattern_chains() — remove this:
if not chain._running:
    del _chain_registry[chain_id]
    continue

# stop_patterns_for_voice() — replace direct manipulation:
if chain_id in _chain_registry:
    chain, _, _, _ = _chain_registry[chain_id]
    chain._running = False
    if chain._pattern:
        chain._pattern.stop()
    del _chain_registry[chain_id]

# With:
chain.stop()  # stop() handles all cleanup
```

### 6. Introduce `_CompContextMixin`

Create the shared mixin that both `MIDI` and `Comp` will use. This separates the inheritance refactor from the new `Comp` feature.

**Include all vfx.Voice attributes as defaults.** Since `Comp` has no incoming voice, it needs defaults for all voice parameters. `MIDI` can override these from the incoming voice.

```python
class _CompContextMixin:
    """
    Mixin providing shared pattern creation, scale handling, and voice defaults.
    
    No __init__ — shared config goes through _configure_context().
    Designed to work with multiple inheritance (MIDI inherits from vfx.Voice).
    """
    
    def _configure_context(
        self,
        cycle=4,
        scale=None,
        octave=4,
        # Voice attribute defaults (mirror vfx.Voice)
        velocity=80,       # 0-127 (TrapScript default)
        length=None,       # See "Length resolution" below
        pan=0.0,           # -1 left, 0 center, 1 right
        output=0,          # Voice output port (0-based)
        fcut=0.0,          # Mod X / filter cutoff (-1 to 1)
        fres=0.0,          # Mod Y / filter resonance (-1 to 1)
        finePitch=0.0,     # Microtonal pitch offset
        color=0,           # Note color / MIDI channel (0-15)
        releaseVelocity=0, # Release velocity (0-127)
    ):
        """Initialize shared context state. Called from subclass __init__."""
        # TrapScript-specific
        self._cycle = cycle
        self._octave = octave
        
        # Voice attribute defaults
        self._default_velocity = velocity
        self._default_length = length
        self._default_pan = pan
        self._default_output = output
        self._default_fcut = fcut
        self._default_fres = fres
        self._default_finePitch = finePitch
        self._default_color = color
        self._default_releaseVelocity = releaseVelocity
        
        # Scale parsing
        self._scale = None
        self._scale_root = None
        self._scale_explicit = False
        if scale:
            self._scale, self._scale_root, self._scale_explicit = _parse_scale(scale)
    
    def note(self, pattern_str, cycle=None, scale=None, mute=False, bus=None, **kwargs):
        """Canonical pattern creation — delegates to shared builder."""
        # Build chain through unified constructor (from 1.3.2.2)
        chain = _build_pattern_chain(...)
        chain._root = self._resolve_root(...)  # Template method
        # Apply voice defaults to chain state
        self._apply_voice_defaults(chain)
        self._on_pattern_created(chain)        # Template method
        return chain
    
    n = note  # Alias
    
    def _apply_voice_defaults(self, chain):
        """Apply context's voice defaults to chain state."""
        chain._state['velocity'] = self._default_velocity / 127.0  # Normalize for internal use
        chain._state['length'] = self._default_length
        chain._state['pan'] = self._default_pan
        chain._state['output'] = self._default_output
        chain._state['fcut'] = self._default_fcut
        chain._state['fres'] = self._default_fres
        chain._state['finePitch'] = self._default_finePitch
        chain._state['color'] = self._default_color
        # Note: releaseVelocity stored but may not be used by all output paths
    
    def _resolve_root(self, scale_root, is_explicit):
        """Template method: override in subclasses."""
        raise NotImplementedError
    
    def _on_pattern_created(self, chain):
        """Template method: override for lifecycle policy."""
        pass
```

#### Voice attribute inheritance behavior

| Context | Source for defaults |
|---------|---------------------|
| `MIDI` | Incoming voice (`v.velocity`, `v.pan`, etc.) — can override via `_configure_context` kwargs |
| `Comp` | `_configure_context` kwargs — no incoming voice |

For `MIDI`, the refactor should preserve current behavior: incoming voice attributes take precedence. The mixin defaults are fallbacks when no voice attribute is available or when overridden at context level.

#### Length resolution (special case)

Length behaves differently between contexts:

| Context | Primary length source | Behavior |
|---------|----------------------|----------|
| `MIDI` | Incoming voice (`v.length`) | Notes sustain for the duration the key is held |
| `Comp` | Pattern event `whole` span | Notes sustain until next event in pattern (legato-style) |

The `length=` parameter in `_configure_context` is an **override**, not a default:

- If `length=None` (default): use context-appropriate behavior above
- If `length=<value>`: force all notes to this duration (beats)

Implementation note: `PatternChain.tick()` already calculates duration from event `whole` spans. The `length` override should only apply when explicitly set, not as a fallback.

Then refactor `MIDI` to use it:

```python
class MIDI(vfx.Voice, _CompContextMixin):
    def __init__(self, incomingVoice, cycle=4, scale=None, **kwargs):
        super().__init__(incomingVoice)  # vfx.Voice init
        self._configure_context(cycle=cycle, scale=scale)  # Mixin init
        self.parentVoice = incomingVoice
    
    def _resolve_root(self, scale_root, is_explicit):
        # MIDI-specific: use incoming voice for implicit scales
        ...
    
    def _on_pattern_created(self, chain):
        chain.trigger()  # Auto-start for MIDI
```

Verify `MIDI` still works correctly before 1.3.3 introduces `Comp`.

### 7. API cleanup

- remove global `ts.n()` and global `ts.note()` public APIs (no deprecation period required)
- route standalone usage through `ts.comp().n()/note()` + `.trigger()`

## Non-goals

- No parser changes.
- No scale algorithm changes.
- No timing model changes beyond lifecycle ownership.
- No behavior change to note event timing once a chain is running.
- No API break for existing `MIDI.n()` users (must still auto-start via context hook).

## Design notes

- Prefer a small internal lifecycle flag (`_lifecycle_state`) to make transitions explicit.
- If restart is supported, define whether phase resets or resumes.
- Registry operations should be centralized through lifecycle methods (not scattered call sites).

## Hard invariants

- Only lifecycle boundaries mutate active registries:
  - register on `trigger()` (or equivalent lifecycle entry point)
  - unregister on `stop()`/cleanup lifecycle path
- Constructors/builders never call `pat.start(...)` or `_register_chain(...)`.
- Update/cleanup loops call lifecycle methods (or shared registry helpers), not ad-hoc direct dict edits.
- This invariant prevents accidental duplicate scheduling; it does not block intentional overlap via `trigger(mode='overlap')`.

## Expected API shape after refactor

```python
# Auto lifecycle (voice-bound, unchanged behavior)
def onTriggerVoice(v):
    midi = ts.MIDI(v, scale="c:major")
    midi.n("0 2 4")  # auto-triggered by MIDI context

# Manual lifecycle (new comp behavior — implemented in 1.3.3)
def onTick():
    c = ts.comp(scale="a:minor")
    c.n("0 2 4").trigger()
```

## Verification checklist

- [ ] `midi.n("0 1 2")` still starts automatically (same user-facing behavior)
- [ ] `PatternChain.trigger()` can be called once safely (no duplicate registration)
- [ ] Calling `.trigger()` twice does not duplicate registry entries
- [ ] `PatternChain.stop()` halts playback and unregisters cleanly
- [ ] Calling `.stop()` twice is safe and leaves chain unregistered
- [ ] Parent voice cleanup (`stop_patterns_for_voice(...)`) still halts voice-bound chains
- [ ] `stop_patterns_for_voice()` routes through `chain.stop()`, not direct dict manipulation
- [ ] `_update_pattern_chains()` does not directly delete from `_chain_registry`
- [ ] Bus state/history behavior remains correct after stop/cleanup
- [ ] `MIDI` correctly uses `_CompContextMixin` with no behavior regression
- [ ] global `ts.n(...)` and global `ts.note(...)` are removed

## Exit criteria for 1.3.3 handoff

This phase is complete when:

1. `_CompContextMixin` exists and `MIDI` uses it successfully
2. `_CompContext` (in 1.3.3) can rely on one mechanism:
   - build chain
   - apply context policy (`auto trigger` vs `manual trigger`)
   with no constructor-specific lifecycle branching
3. All registry mutations happen through lifecycle methods
