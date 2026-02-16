# Phase 1.3.3: ts.comp() — Standalone Pattern Context

## Role of this phase

This document is the **architecture blueprint** for `Comp` context class.

Implementation-level lifecycle/registration constraints are defined in:

- `phase1.3.2.2_unify_chain_construction.md`
- `phase1.3.2.3_PatternChain_lifecycle.md`

`1.3.3` should be implemented by applying those constraints through the mixin-based design in this file.

**Prerequisite:** `_CompContextMixin` is introduced and `MIDI` is refactored to use it in phase 1.3.2.3.

## Problem

`ts.MIDI` provides OOP defaults (scale, cycle) that `.n()` inherits. We are removing global standalone pattern APIs (`ts.n()` and global `ts.note()`) and need a standalone replacement with equivalent OOP defaults and scale behavior. This creates an architectural gap.

## Solution

Introduce `ts.comp()` — a standalone pattern context with the same OOP structure as `ts.MIDI`, minus required voice binding.

## Scale Root Resolution (see Phase 1.3.2.1)

`ts.comp()` follows the explicit/implicit scale root behavior:

| Scale String | Root Resolution | Example |
|-------------|-----------------|---------|
| `a4:minor` (explicit) | Use scale root directly | `n("0")` → A4 |
| `a:minor` (implicit) | Use scale root as default | `n("0")` → A4 (default octave 4) |
| `a:minor` + `root="c4"` | Use `root=` param, snap to scale | `n("0")` → C4's degree in A minor |

**Key difference from ts.MIDI:** Since `ts.comp()` has no incoming voice, implicit scales default to the scale root (octave 4). The `root=` parameter is optional and only needed when you want degree 0 to be something other than the scale root.

```python
# Explicit scale — root= ignored, degree 0 = A4
ts.comp(scale="a4:minor").note("0")  # Plays A4

# Implicit scale — defaults to scale root (A4)
ts.comp(scale="a:minor").note("0")  # Plays A4

# Implicit scale with root override — degree 0 = C4's position
ts.comp(scale="a:minor", root="c4").note("0")  # Plays C4 (snapped, it's in scale)
```

## Design: Mixin Pattern

Since `MIDI` must inherit from `vfx.Voice` (external FL Studio class with incompatible `__init__` signature), we use a **mixin pattern** rather than abstract base class inheritance.

`_CompContextMixin` is introduced in phase 1.3.2.3 and verified with `MIDI` before this phase begins.

```python
class _CompContextMixin:
    """
    Mixin providing shared pattern creation, scale handling, and voice defaults.
    
    No __init__ — shared config goes through _configure_context().
    Designed to work with multiple inheritance (MIDI inherits from vfx.Voice).
    
    See phase1.3.2.3 for full _configure_context() signature with all voice attributes.
    """
    
    def _configure_context(
        self,
        cycle=4,
        scale=None,
        octave=4,
        velocity=80,       # 0-127 (TrapScript default)
        length=None,       # None = pattern spans; value = override
        pan=0.0,           # -1 to 1
        output=0,          # Voice output port
        fcut=0.0,          # Mod X (-1 to 1)
        fres=0.0,          # Mod Y (-1 to 1)
        finePitch=0.0,     # Microtonal offset
        color=0,           # Note color (0-15)
        releaseVelocity=0, # Release velocity (0-127)
    ):
        """Initialize shared context state. Called from subclass __init__."""
        # ... stores all defaults (see 1.3.2.3 for full implementation)
    
    def note(self, pattern_str, cycle=None, scale=None, mute=False, bus=None, **kwargs):
        """Canonical pattern creation — delegates to shared builder."""
        chain = _build_pattern_chain(...)
        chain._root = self._resolve_root(...)
        self._apply_voice_defaults(chain)  # Apply context defaults to chain
        self._on_pattern_created(chain)
        return chain
    
    n = note  # Alias
    
    def _apply_voice_defaults(self, chain):
        """Apply context's voice defaults to chain state."""
        # ... applies all defaults to chain._state
    
    def _resolve_root(self, scale_root, is_explicit):
        """Template method: override in subclasses."""
        raise NotImplementedError
    
    def _on_pattern_created(self, chain):
        """Template method: override for lifecycle policy."""
        pass


class MIDI(vfx.Voice, _CompContextMixin):
    """Voice-bound context. Auto-triggers, auto-releases."""
    
    def __init__(self, incomingVoice, cycle=4, scale=None, **kwargs):
        super().__init__(incomingVoice)  # vfx.Voice init
        self._configure_context(cycle=cycle, scale=scale)  # Mixin init
        self.parentVoice = incomingVoice
    
    def _resolve_root(self, scale_root, is_explicit):
        if is_explicit:
            # Explicit: degree 0 = scale root, ignore incoming voice
            return scale_root, 0  # (root, base_degree)
        else:
            # Implicit: degree 0 = incoming voice's position
            snapped = _quantize_to_scale(self.note, scale, scale_root)
            base_deg = _midi_to_scale_degree(self.note, scale, scale_root)
            return snapped, base_deg
    
    def _on_pattern_created(self, chain):
        chain.trigger()  # Auto lifecycle policy


class Comp(_CompContextMixin):
    """Standalone context. Manual trigger/release."""
    
    def __init__(
        self,
        octave=4,
        scale=None,
        root=None,
        cycle=4,
        # Voice attribute defaults (mirror vfx.Voice)
        velocity=80,       # 0-127 (TrapScript default)
        length=None,       # None = use pattern event spans (legato); value = override
        pan=0.0,           # -1 left, 0 center, 1 right
        output=0,          # Voice output port (0-based)
        fcut=0.0,          # Mod X / filter cutoff (-1 to 1)
        fres=0.0,          # Mod Y / filter resonance (-1 to 1)
        finePitch=0.0,     # Microtonal pitch offset
        color=0,           # Note color / MIDI channel (0-15)
        releaseVelocity=0, # Release velocity (0-127)
        parent=None,       # Optional voice binding for auto-cleanup
    ):
        self._configure_context(
            cycle=cycle, scale=scale, octave=octave,
            velocity=velocity, length=length, pan=pan,
            output=output, fcut=fcut, fres=fres,
            finePitch=finePitch, color=color,
            releaseVelocity=releaseVelocity,
        )
        self._root_param = root  # Optional root override
        self._parent = parent   # Optional voice binding
    
    def _resolve_root(self, scale_root, is_explicit):
        if is_explicit:
            # Explicit: degree 0 = scale root, ignore root= param
            return scale_root, 0
        elif self._root_param is not None:
            # Implicit with root=: snap root param to scale
            snapped = _quantize_to_scale(self._root_param, scale, scale_root)
            base_deg = _midi_to_scale_degree(self._root_param, scale, scale_root)
            return snapped, base_deg
        else:
            # Implicit without root=: default to scale root
            return scale_root, 0
    
    def _on_pattern_created(self, chain):
        # Manual lifecycle policy; user calls .trigger(...)
        # But still register parent binding if provided
        if self._parent:
            chain._parent_voice = self._parent
        pass
```

## parent= Binding Semantics

When `parent=v` is provided to `ts.comp()`:

- The chain is registered into `_voice_chain_map` for automatic cleanup
- `stop_patterns_for_voice(v)` will clean up the chain when the parent voice releases
- This creates a **mixed-policy chain**: manual start via `.trigger()`, automatic cleanup via voice release

This is the intentional design: `parent=` provides lifecycle binding without forcing auto-start.

```python
def onTriggerVoice(v):
    # Manual trigger, but auto-cleanup when v releases
    pat = ts.comp(scale="c5:major", parent=v)
    pat.note("0 2 4").trigger()
```

## Chain Count Guard (Memory Leak Protection)

`ts.comp()` is designed to be called from `onTick()`. A naive user could create unbounded chains:

```python
# BAD: Creates new chain every tick — memory leak!
def onTick():
    ts.comp(scale="c:minor").n("0 1 2").trigger()
    ts.update()
```

### Two-stage guard on unbound Comp chains

Implement a guard that tracks active chains without `parent=` binding:

```python
_UNBOUND_CHAIN_WARN_THRESHOLD = 32
_UNBOUND_CHAIN_ERROR_THRESHOLD = 128

def _check_unbound_chain_count():
    """Check for potential memory leak from unbound Comp chains."""
    unbound_count = sum(
        1 for chain_id, (chain, _, _, parent_id) in _chain_registry.items()
        if parent_id is None
    )
    
    if unbound_count >= _UNBOUND_CHAIN_ERROR_THRESHOLD:
        raise RuntimeError(
            f"[TrapScript] {unbound_count} unbound pattern chains detected. "
            f"This indicates a memory leak — patterns created in onTick() without "
            f"parent= binding or .stop() cleanup. Use global variables with "
            f"'if None' guards, or provide parent= for automatic cleanup."
        )
    elif unbound_count >= _UNBOUND_CHAIN_WARN_THRESHOLD:
        print(
            f"[TrapScript] Warning: {unbound_count} unbound pattern chains. "
            f"Consider using parent= binding or manual .stop() cleanup."
        )
```

Call `_check_unbound_chain_count()` in `PatternChain.trigger()` when the chain has no parent binding.

### Idiomatic usage patterns (document prominently)

```python
# GOOD: Create once, guard with global
_melody = None
def onTick():
    global _melody
    if _melody is None:
        _melody = ts.comp(scale="c:minor").n("0 1 2").trigger()
    ts.update()

# GOOD: Use parent= for automatic cleanup
def onTriggerVoice(v):
    ts.comp(scale="c:minor", parent=v).n("0 1 2").trigger()

# GOOD: Manual cleanup
_pattern = ts.comp(scale="c:minor").n("0 1 2").trigger()
# ... later ...
_pattern.stop()
```

## API Comparison

| Aspect | `ts.MIDI(v)` | `ts.comp()` |
|--------|-------------|-------------|
| Root source | `v.note` (or scale root if explicit) | Scale root (or `root=` if implicit) |
| Lifecycle | Auto (bound to `v`) | Manual (`.trigger()` / `.stop()`) |
| Context | `onTriggerVoice` | `onTick` / anywhere |
| Parent binding | Required (`v`) | Optional (`parent=`) |
| Cleanup | Automatic via `stop_patterns_for_voice` | Manual, or automatic if `parent=` provided |

## Usage

```python
# Voice-reactive (implicit scale, root from incoming voice)
def onTriggerVoice(v):
    midi = ts.MIDI(v, scale="c:major")
    midi.n("0 2 4")  # degree 0 = incoming voice's position

# Voice-reactive (explicit scale, root is C5 regardless of incoming)
def onTriggerVoice(v):
    midi = ts.MIDI(v, scale="c5:major")
    midi.n("0 2 4")  # Plays C5, E5, G5

# Compositional (explicit scale)
def onTick():
    pat = ts.comp(scale="a4:minor")
    pat.note("0 2 4").trigger()  # Plays A4, C5, E5

# Compositional (implicit scale, defaults to scale root)
def onTick():
    pat = ts.comp(scale="a:minor")
    pat.note("0 2 4").trigger()  # Plays A4, C5, E5 (same result)

# Compositional (implicit scale with root override)
def onTick():
    pat = ts.comp(scale="a:minor", root="c4")
    pat.note("0 2 4").trigger()  # degree 0 = C4's position in A minor

# Compositional with voice binding (manual trigger, auto cleanup)
def onTriggerVoice(v):
    pat = ts.comp(scale="c5:major", parent=v)
    pat.note("0 2 4").trigger()  # Manual trigger, cleanup when parent releases
```

## API Direction

Global `ts.n()` and global `ts.note()` are removed in this phase progression. Standalone composition should use `ts.comp()`.

```python
def onTick():
    comp = ts.comp(scale="c:minor")
    comp.n("0 1 2").trigger()
```

### Migration

```python
# Old
ts.n("0 1 2", cycle=4, root=60)
ts.note("0 1 2", cycle=4, root=60)

# New
ts.comp(root=60).n("0 1 2", cycle=4).trigger()
```

## Sequencing

Recommended order:

1. `1.3.2.2` unify construction + remove legacy pattern systems
2. `1.3.2.3` explicit lifecycle ownership + introduce `_CompContextMixin` + refactor `MIDI`
3. `1.3.3` `Comp` class implementation (this blueprint)
4. `1.3.4` lifecycle additions (`pause/play/restart`, advanced trigger modes)

`1.3.4` should be implemented **after** `1.3.3`, not bundled into `1.3.3`.

## Verification checklist

- [ ] `Comp` class exists and uses `_CompContextMixin`
- [ ] `ts.comp(scale="c:minor").n("0 1 2").trigger()` creates and plays pattern
- [ ] `ts.comp()` without `.trigger()` does NOT play (manual lifecycle)
- [ ] `ts.comp(parent=v)` registers chain for automatic cleanup via `stop_patterns_for_voice`
- [ ] Chain count guard warns at 32 unbound chains
- [ ] Chain count guard errors at 128 unbound chains
- [ ] `_resolve_root` behaves correctly for explicit vs implicit scales
- [ ] `_resolve_root` respects `root=` parameter for implicit scales
- [ ] `MIDI` still works correctly (regression test from 1.3.2.3)
