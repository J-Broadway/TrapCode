# Pattern State Access (Bus System) — Implementation Spec

## Overview

Enable `.n()` patterns (and chained modifiers like `.v()`, `.pan()`, `.chord()`) to expose internal state as a readable dictionary, accessible across VFX Script scopes.

**Primary use case**: Use mini-notation patterns as programmable state machines—sequencing logic, not just notes.

---

## Public API

### Creating Patterns with Bus Registration

Two entry points: `midi.n()` (voice-scoped) and `tc.n()` (standalone).

#### Voice-Scoped: `midi.n()` (in onTriggerVoice)

Pattern is automatically tied to the incoming voice lifecycle:

```python
def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    
    # Register pattern to bus (tied to incomingVoice)
    midi.n("<0 1 2 3>", c=4, bus='melody')
    
    # Ghost pattern (no audio, state only)
    midi.n("<0 1 2 3>", c=4, mute=True, bus='clock')
    
    # Chained modifiers
    midi.n("<0 1 2 3>").v("<100 50 75>").pan("<-1 0 1>", bus='complex')

def onReleaseVoice(incomingVoice):
    tc.stop_patterns_for_voice(incomingVoice)  # Auto-cleanup
```

#### Standalone: `tc.n()` (in onTick or globally)

Pattern lifecycle is manual or optionally tied to a parent voice:

```python
# Option 1: Tied to a parent voice (cleaned up on release)
def onTriggerVoice(v):
    tc.n("<0 3 5>", c=4, parent=v, bus='melody')  # Explicitly tied to v

# Option 2: Truly standalone (persists until .stop())
_clock = None
def onTick():
    global _clock
    if _clock is None:
        _clock = tc.n("<0 1 2 3>", c=1, mute=True, bus='clock')
    
    if _clock:  # onset
        print(f"Beat {_clock['step']}")
    
    tc.update()

# Manual cleanup for standalone patterns
_clock.stop()  # Removes from bus and stops ticking
```

#### Parameter Comparison

| Parameter | `midi.n()` | `tc.n()` |
|-----------|-----------|----------|
| `c` | Cycle beats | Cycle beats |
| `root` | Auto (from MIDI note) | Required or default 60 |
| `parent` | Auto (incomingVoice) | Optional, explicit |
| `bus` | Optional | Optional |
| `mute` | Default False | Default False |

#### Lifecycle Summary

| Type | Created in | Tied to | Cleanup |
|------|-----------|---------|---------|
| `midi.n()` | `onTriggerVoice` | Incoming voice | Auto via `stop_patterns_for_voice()` |
| `tc.n(parent=v)` | Anywhere | Specified voice | Auto via `stop_patterns_for_voice()` |
| `tc.n()` (no parent) | Anywhere | None | Manual via `.stop()` |

### Accessing Bus State

```python
def onTick():
    # Get bus registry (returns BusRegistry, never None)
    melody = tc.bus('melody')
    
    # Access patterns
    melody.oldest()             # Earliest triggered (or None if empty)
    melody.newest()             # Most recently triggered (or None if empty)
    
    # Iterate all active voices (yields PatternChains directly)
    for chain in melody:
        print(chain['notes'])
    
    # Iterate with voice IDs when needed
    for voice_id, chain in melody.items():
        print(f"{voice_id}: {chain['notes']}")
    
    # Check if bus has active patterns
    if melody:
        print(f"{len(melody)} active voices")
    
    # Index access
    melody[0]                       # First chain by index
    melody[-1]                      # Last chain by index
    
    # Debug output
    print(melody)                   # <BusRegistry 'melody': 3 voices>
    
    tc.update()
```

### PatternChain Methods

```python
chain = tc.bus('melody').oldest()  # Or .newest()

# Direct key access (via __getitem__)
chain['n']                      # Same as chain.dict()['n']
chain['velocity']
chain['notes']

# Full state snapshot
chain.dict()                    # Returns complete dict copy

# Change detection
chain.changed()                 # True if onset occurred this tick
chain.changed('n')              # True if 'n' value changed this tick
chain.changed('velocity')       # Works for any key

# Membership test
if 'scale_root' in chain:       # Check if key exists
    print(chain['scale_root'])

# Boolean (truthy if onset this tick)
if chain:                       # True when new event occurred
    print("New event!")

# Debug output
print(chain)                    # <PatternChain step=2 notes=[64, 67]>
```

### History Access (Released Voices)

```python
# After voices are released, access history
tc.bus('melody').last()         # List of chains from most recent release
tc.bus('melody').last(1)        # Second-most recent release batch
tc.bus('melody').history()      # All cached batches (newest first)
tc.bus('melody').history_limit  # Max batches kept (default 10)
```

### Global Bus Access

```python
# tc.buses — dict-like container of all registered buses
tc.buses                        # Returns dict {name: BusRegistry, ...}
tc.buses['drums']               # Access by name (KeyError if missing)
tc.buses.get('drums')           # Access by name (None if missing)
tc.buses.keys()                 # All bus names

# Iterate all buses
for name, bus in tc.buses.items():
    print(f"{name}: {len(bus)} active, {len(bus.history())} released")

# Check existence without auto-creating
if 'drums' in tc.buses:
    ...

# Difference from tc.bus():
# tc.bus('name')    — auto-creates if missing (convenient for registration)
# tc.buses['name']  — raises KeyError if missing (explicit check)
```

---

## State Dictionary Structure

### Base State (Always Present)

```python
{
    # --- Pattern timing ---
    'notes': [],       # list[int]: MIDI note values
    'step': 0,         # int: Current step index (0-based)
    'phase': 0.0,      # float: Phase within cycle [0.0-1.0)
    'cycle': 0,        # int: Current cycle number
    'onset': False,    # bool: True if new event started this tick
    'mute': False,     # bool: False = audible, True = silent/ghost mode
    
    # --- VFX Voice properties ---
    'note': 60.0,      # float: MIDI note number (fractional for microtuning)
    'finePitch': 0.0,  # float: Fine pitch offset
    'velocity': 0.8,   # float: Note velocity [0.0-1.0]
    'pan': 0.0,        # float: Stereo pan [-1.0 to 1.0]
    'length': 0,       # int: Duration in ticks (0 = until release)
    'output': 0,       # int: Voice output channel (0-based)
    'fcut': 0.0,       # float: Mod X [-1.0 to 1.0]
    'fres': 0.0,       # float: Mod Y [-1.0 to 1.0]
}
```

### Extended Keys (Added by Chain Methods)

| Method | Keys Added |
|--------|------------|
| `.n(pattern)` | `'n': [int, ...]` — pattern offset values |
| `.chord(pattern)` | `'chord': str` — chord symbol |
| `.v(pattern)` | `'v': float` — velocity from pattern |
| `.pan(pattern)` | `'pan_pattern': float` — pan from pattern |
| `.scale(scale_str)` | `'scale_root': str`, `'scale_mode': str` |

---

## Implementation Components

### 1. PatternChain Class

```python
class PatternChain:
    """Universal container for pattern-based operations."""
    
    def __init__(self, midi_wrapper, mute=False):
        self._midi = midi_wrapper
        self._mute = mute
        self._patterns = {}           # method_name -> Pattern
        self._updaters = []           # List of update functions
        self._prev_state = {}         # For change detection
        self._state = {
            'notes': [],
            'step': 0,
            'phase': 0.0,
            'cycle': 0,
            'onset': False,
            'mute': mute,
            'note': 60.0,
            'finePitch': 0.0,
            'velocity': 0.8,
            'pan': 0.0,
            'length': 0,
            'output': 0,
            'fcut': 0.0,
            'fres': 0.0,
        }
    
    def _register(self, keys: dict, updater=None):
        """Register state keys and optional per-tick updater."""
        self._state.update(keys)
        if updater:
            self._updaters.append(updater)
    
    # --- Dunder methods for Pythonic access ---
    
    def __getitem__(self, key: str):
        """Direct key access: chain['n'] instead of chain.dict()['n']."""
        return self._state.get(key)
    
    def __contains__(self, key: str) -> bool:
        """Membership test: 'n' in chain."""
        return key in self._state
    
    def __bool__(self) -> bool:
        """Truthy if onset occurred this tick."""
        return self._state.get('onset', False)
    
    def __repr__(self) -> str:
        """Useful debug output."""
        notes = self._state.get('notes', [])
        step = self._state.get('step', 0)
        return f"<PatternChain step={step} notes={notes}>"
    
    # --- State access methods ---
    
    def dict(self) -> dict:
        """Return snapshot of current state."""
        return self._state.copy()
    
    def changed(self, key: str = None) -> bool:
        """
        Detect state changes.
        
        Args:
            key: Specific key to check, or None for onset detection
        
        Returns:
            True if change occurred this tick
        """
        if key is None:
            return self._state.get('onset', False)
        
        current = self._state.get(key)
        previous = self._prev_state.get(key)
        return current != previous
    
    def tick(self, current_tick: int, ppq: int, cycle_beats: float):
        """Update state for this tick. Called by tc.update()."""
        # Store previous state for change detection
        self._prev_state = self._state.copy()
        
        # Update base timing state
        # ... (phase, step, cycle, onset calculation)
        
        # Run all registered updaters
        for updater in self._updaters:
            updater(current_tick, ppq, cycle_beats)
        
        # Trigger notes if not muted and onset occurred
        if not self._mute and self._state['onset']:
            self._fire_notes()
    
    def _fire_notes(self):
        """Fire MIDI notes for current state. Skipped when mute=True."""
        for midi_note in self._state['notes']:
            note_obj = Note(
                m=int(midi_note),
                l=self._state['length'] or self._calculate_duration(),
                v=self._state['velocity'],
                p=self._state['pan'],
            )
            note_obj.trigger(cut=False, parent=self._midi.parentVoice)
    
    # --- Chainable methods ---
    
    def n(self, pattern_str: str, **kwargs) -> 'PatternChain':
        self._patterns['n'] = _parse_mini(pattern_str)
        self._register({'n': []}, updater=self._update_n)
        return self
    
    def v(self, pattern_str: str) -> 'PatternChain':
        self._patterns['v'] = _parse_mini(pattern_str)
        self._register({'v': 0.8}, updater=self._update_v)
        return self
    
    def pan(self, pattern_str: str) -> 'PatternChain':
        self._patterns['pan_pattern'] = _parse_mini(pattern_str)
        self._register({'pan_pattern': 0.0}, updater=self._update_pan)
        return self
    
    def scale(self, scale_str: str) -> 'PatternChain':
        self._scale_str = scale_str
        self._register({
            'scale_root': '',
            'scale_mode': '',
        }, updater=self._update_scale)
        return self
    
    def chord(self, pattern_str: str, **kwargs) -> 'PatternChain':
        self._patterns['chord'] = _parse_mini(pattern_str)
        self._register({'chord': ''}, updater=self._update_chord)
        return self
    
    # --- Lifecycle ---
    
    def stop(self):
        """
        Stop the pattern and remove from bus.
        
        For standalone patterns (tc.n without parent), this is required
        for cleanup. Voice-scoped patterns are cleaned up automatically.
        """
        self._running = False
        
        # Remove from bus if registered
        if self._bus_name and self._bus_voice_id:
            bus = tc.bus(self._bus_name)
            if self._bus_voice_id in bus:
                del bus[self._bus_voice_id]
        
        # Remove from pattern registry
        _unregister_chain(self)
```

### 2. BusRegistry Class

```python
class BusRegistry(dict):
    """Dict-like container for PatternChains keyed by voice ID."""
    
    def __init__(self):
        super().__init__()
        self._history = []            # List of release batches
        self.history_limit = 10       # Max batches to keep
        self._voice_counter = 0       # For unique IDs
        self.name = ''                # Set when registered via tc.bus()
    
    # --- Dunder methods for Pythonic access ---
    
    def __iter__(self):
        """Iterate PatternChains directly (not voice IDs)."""
        return iter(self.values())
    
    def __getitem__(self, key):
        """Access by index (int) or voice_id (tuple)."""
        if isinstance(key, int):
            # tc.bus('clock')[0] — get by index
            values = list(self.values())
            if not values or key >= len(values) or key < -len(values):
                raise IndexError(f"Bus index {key} out of range")
            return values[key]
        return super().__getitem__(key)  # voice_id tuple access
    
    def __bool__(self):
        """Truthy if has active voices."""
        return len(self) > 0
    
    def __repr__(self):
        """Useful debug output."""
        return f"<BusRegistry '{self.name}': {len(self)} voices>"
    
    # --- Core methods ---
    
    def _generate_id(self) -> tuple:
        """Generate unique voice ID: (timestamp, counter)."""
        self._voice_counter += 1
        return (time.time(), self._voice_counter)
    
    def register(self, chain: PatternChain) -> tuple:
        """Add chain to registry, return voice ID."""
        voice_id = self._generate_id()
        dict.__setitem__(self, voice_id, chain)  # Use dict method to avoid override issues
        return voice_id
    
    def release(self, voice_id: tuple, release_tick: int):
        """Move chain to history on voice release."""
        if voice_id not in self:
            return
        
        chain = self.pop(voice_id)
        
        # Group by release tick
        if self._history and self._history[0][0] == release_tick:
            self._history[0][1].append(chain)
        else:
            self._history.insert(0, (release_tick, [chain]))
        
        # Trim history
        while len(self._history) > self.history_limit:
            self._history.pop()
    
    def newest(self) -> PatternChain | None:
        """Get most recently triggered chain."""
        if not self:
            return None
        return dict.__getitem__(self, max(self.keys()))
    
    def oldest(self) -> PatternChain | None:
        """Get earliest triggered chain."""
        if not self:
            return None
        return dict.__getitem__(self, min(self.keys()))
    
    def last(self, n: int = 0) -> list[PatternChain]:
        """Get chains from nth-most-recent release batch."""
        if n >= len(self._history):
            return []
        return self._history[n][1]
    
    def history(self) -> list[list[PatternChain]]:
        """Get all release batches (newest first)."""
        return [batch[1] for batch in self._history]
```

### 3. Global Bus Storage

```python
class BusContainer(dict):
    """Dict-like container for all buses. Accessed via tc.buses."""
    pass

# Module-level storage
_buses = BusContainer()  # bus_name -> BusRegistry

# Expose as tc.buses
buses = _buses

def bus(name: str) -> BusRegistry:
    """Get or create bus registry by name. Auto-creates if missing."""
    if name not in _buses:
        _buses[name] = BusRegistry()
        _buses[name].name = name  # Store name on registry for reference
    return _buses[name]
```

### 4. Standalone tc.n() Function

```python
def n(pattern_str: str, c=4, root=60, parent=None, mute=False, bus=None) -> PatternChain:
    """
    Create a standalone pattern from mini-notation.
    
    Args:
        pattern_str: Mini-notation string (e.g., "0 3 5 7")
        c: Cycle duration in beats (default 4)
        root: Root note (default 60 = C4)
        parent: Optional parent voice (ties pattern to voice lifecycle)
        mute: If True, pattern is ghost (state-only, no audio)
        bus: Optional bus name for state access
    
    Returns:
        PatternChain object
    """
    chain = PatternChain(midi_wrapper=None, mute=mute)
    chain.n(pattern_str, c=c, root=root)
    
    if bus:
        voice_id = tc.bus(bus).register(chain)
        chain._bus_name = bus
        chain._bus_voice_id = voice_id
    
    # Register for update loop
    _register_chain(parent, chain, c, root)
    
    return chain
```

### 5. Integration with MIDI Class

```python
class MIDI:
    def n(self, pattern_str: str, c=4, root=None, mute=False, bus=None, **kwargs):
        """Create pattern, optionally register to bus. Auto-tied to parent voice."""
        chain = PatternChain(self, mute=mute)
        chain.n(pattern_str, c=c, root=root or self.note, **kwargs)
        
        if bus:
            voice_id = tc.bus(bus).register(chain)
            chain._bus_name = bus
            chain._bus_voice_id = voice_id
            self._bus_registrations.append((bus, voice_id))
        
        # Store for update loop (tied to parentVoice)
        _register_chain(self.parentVoice, chain, c, root or self.note)
        
        return chain
    
    def chord(self, pattern_str: str, c=4, mute=False, bus=None, **kwargs):
        """Create chord pattern, optionally register to bus."""
        chain = PatternChain(self, mute=mute)
        chain.chord(pattern_str, c=c, **kwargs)
        
        if bus:
            voice_id = tc.bus(bus).register(chain)
            chain._bus_name = bus
            chain._bus_voice_id = voice_id
            self._bus_registrations.append((bus, voice_id))
        
        _register_chain(self.parentVoice, chain, c, self.note)
        
        return chain
```

### 5. Update Loop Integration

```python
def _update_pattern_chains():
    """Called by tc.update() to tick all active chains."""
    current_tick = _get_current_tick()
    ppq = vfx.context.PPQ
    
    for voice_id, (chain, cycle_beats_raw, root) in list(_chain_registry.items()):
        cycle_beats = _resolve_dynamic(cycle_beats_raw)
        chain.tick(current_tick, ppq, cycle_beats)

def stop_patterns_for_voice(parent_voice):
    """Clean up patterns and bus entries on voice release."""
    voice_id = id(parent_voice)
    release_tick = vfx.context.ticks
    
    # Release from buses
    for bus_name, bus_voice_id in _voice_bus_map.get(voice_id, []):
        tc.bus(bus_name).release(bus_voice_id, release_tick)
    
    # Clean up pattern registry
    # ... existing cleanup logic
```

---

## Implementation Order

### Phase 1: Core Infrastructure
1. Implement `PatternChain` class with base state
2. Implement `BusRegistry` class
3. Add global `tc.bus()` accessor
4. Integrate with existing `MIDI.n()` method

### Phase 2: Chain Methods
5. Implement `.n()` with state updates
6. Implement `.v()`, `.pan()` modifiers
7. Implement `.changed()` detection

### Phase 3: Lifecycle Management
8. Implement voice ID generation (timestamp + counter)
9. Implement release/history tracking
10. Integrate with `stop_patterns_for_voice()`

### Phase 4: Extended Methods
11. Implement `.chord()` with chord symbol parsing
12. Implement `.scale()` modifier
13. Add remaining VFX Voice property modifiers

---

## Test Cases

### Basic State Access
```python
def onTriggerVoice(v):
    midi = tc.MIDI(v)
    midi.n("<0 3 5 7>", c=4, bus='test')

def onTick():
    chain = tc.bus('test').oldest()
    if chain and chain.changed():
        print(f"Step {chain.dict()['step']}: {chain.dict()['notes']}")
    tc.update()
```

### Ghost Pattern for Logic
```python
def onTriggerVoice(v):
    midi = tc.MIDI(v)
    midi.n("<0 1 2 3>", c=1, mute=True, bus='clock')

def onTick():
    clock = tc.bus('clock').oldest()
    if clock and clock.dict()['n'] == [3]:
        print("Fourth beat!")
    tc.update()
```

### Multi-Voice Handling
```python
def onTick():
    melody = tc.bus('melody')
    print(f"Active voices: {len(melody)}")
    for vid, chain in sorted(melody.items()):
        print(f"  {vid}: notes={chain.dict()['notes']}")
    tc.update()
```

### History Access
```python
def onReleaseVoice(v):
    tc.stop_patterns_for_voice(v)
    
    # Check what just released
    last = tc.bus('melody').last()
    if last:
        notes = [c.dict()['notes'] for c in last]
        print(f"Released: {notes}")
```

### Standalone tc.n() with Parent Voice
```python
def onTriggerVoice(v):
    # Standalone pattern tied to voice lifecycle
    tc.n("<0 3 5>", c=4, parent=v, bus='melody')

def onReleaseVoice(v):
    tc.stop_patterns_for_voice(v)  # Cleans up tc.n(parent=v) patterns too
```

### Standalone tc.n() Persistent (Global Clock)
```python
_clock = None

def onTick():
    global _clock
    
    # Create once, persists across all voices
    if _clock is None:
        _clock = tc.n("<0 1 2 3>", c=1, mute=True, bus='clock')
    
    # React to clock steps
    if _clock:
        print(f"Beat {_clock['step'] + 1}")
    
    tc.update()

# Manual cleanup when needed
def cleanup():
    global _clock
    if _clock:
        _clock.stop()
        _clock = None
```

---

## README Updates

Add new section to README.md after existing pattern documentation:

### Bus System (Pattern State Access)

```markdown
## Bus System

Register patterns to named buses for cross-scope state access:

### Basic Usage

```python
def onTriggerVoice(v):
    midi = tc.MIDI(v)
    midi.n("<0 3 5 7>", c=4, bus='melody')

def onTick():
    chain = tc.bus('melody').oldest()
    if chain:  # Truthy when onset occurred
        print(chain['notes'])
    tc.update()
```

### Ghost Patterns (State-Only)

Use `mute=True` for patterns that track state without producing sound:

```python
midi.n("<0 1 2 3>", c=1, mute=True, bus='clock')

# In onTick, use as a sequencer clock
clock = tc.bus('clock').oldest()
if clock and clock['n'] == [3]:
    print("Beat 4!")
```

### State Access

Access pattern state directly via bracket notation or `.dict()`:

```python
chain['notes']            # Direct access (preferred)
chain['step']
chain['velocity']
chain.dict()              # Full state snapshot

# Check if key exists
if 'scale_root' in chain:
    print(chain['scale_root'])
```

### Change Detection

```python
chain.changed()           # True if onset occurred
chain.changed('n')        # True if 'n' value changed

# Or use boolean (truthy = onset)
if chain:
    print("New event!")
```

### Iteration

```python
# Iterate chains directly
for chain in tc.bus('melody'):
    print(chain['notes'])

# With voice IDs
for voice_id, chain in tc.bus('melody').items():
    print(f"{voice_id}: {chain['notes']}")

# Index access
tc.bus('melody')[0]       # First chain
tc.bus('melody')[-1]      # Last chain
```

### Accessors

```python
tc.bus('melody').oldest() # Earliest triggered
tc.bus('melody').newest() # Most recently triggered
len(tc.bus('melody'))     # Count of active voices
```

### History (Released Voices)

```python
tc.bus('melody').last()    # Chains from last release
tc.bus('melody').last(1)   # Second-to-last release
tc.bus('melody').history() # All cached releases
```

### All Buses

```python
for name, bus in tc.buses.items():
    print(f"{name}: {len(bus)} active")

# Debug output
print(tc.bus('melody'))   # <BusRegistry 'melody': 3 voices>
print(chain)              # <PatternChain step=2 notes=[64, 67]>
```
```

---

## References

- Current `has_onset()`: `trapcode.py` lines 1020-1027
- Current `Pattern.tick()`: `trapcode.py` lines 1330-1400
- Current `_midi_patterns`: `trapcode.py` lines 1842, 1903
- FL Studio VFX API: https://www.image-line.com/fl-studio-learning/fl-studio-beta-online-manual/html/plugins/VFX%20Script.htm
