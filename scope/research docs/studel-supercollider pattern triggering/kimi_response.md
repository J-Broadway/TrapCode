Now let me search for more specific information about SuperCollider's Pmono and voice allocation:
Now I have comprehensive information about both Strudel and SuperCollider. Let me compile the findings into API design recommendations:
Based on my research into Strudel and SuperCollider, here's a comprehensive analysis for your FL Studio VFX Script MIDI API design:

---

## Strudel Analysis

### Mini-Notation: Notes, Velocity, Duration

**Notes** are represented in multiple ways:
- **Pitch names**: `c3`, `e3`, `g3` (note name + octave)
- **MIDI numbers**: `60`, `62`, `64` (middle C = 60)
- **Scale degrees**: combined with `\scale` and `\octave` parameters

**Velocity** is controlled via:
- `.velocity(0.8)` — multiplies with gain, range 0-1
- `.gain(0.8)` — exponential gain control
- Patterns can control velocity dynamically: `.velocity(".4 1")`

**Duration** uses several mechanisms:
- **Cycle-based**: Events fill one cycle by default, subdivided equally
- **Legato**: `.legato(0.5)` — note length as fraction of duration
- **Elongation**: `@` symbol — `"c3@3 e3"` makes c3 3x longer than e3
- **TimeCat**: explicit time-weighted sequences

### Pattern Triggering/Scheduling

Strudel uses a **pure functional reactive** approach:
```javascript
// Pattern is a pure function of time
const haps = pattern.queryArc(time, time + interval);

// Scheduler queries at fixed intervals (50ms)
// Events have: begin time, end time, value
```

Key insight: **Patterns are queries, not streams**. The scheduler asks "what events should be playing at time T?" rather than pushing events.

### Polyphony Handling

Strudel handles polyphony elegantly through **structural operators**:

| Notation | Meaning |
|----------|---------|
| `[c3,e3,g3]` | Chord (simultaneous notes) |
| `c3,e3,g3` | Stack (parallel patterns) |
| `<c3 e3 g3>` | Slowcat (sequential over multiple cycles) |

**Polymeter**: `{a b c, d e}` — different subdivisions share the same pulse
**Polyrhythm**: `[a b c, d e]` — different subdivisions, different speeds

### Note-On/Note-Off Semantics

Strudel abstracts this away — events have **intrinsic duration**:
- Events specify `whole.begin` and `whole.end`
- The audio engine handles the lifecycle
- **No explicit release() call needed**

For MIDI specifically, the `note` parameter triggers note-on at start, note-off at end.

---

## SuperCollider Analysis

### Synth & Pbind Note Creation

**Direct Synth creation**:
```supercollider
Synth(\default, [\freq, 440, \amp, 0.5])
```

**Pbind (pattern-based)**:
```supercollider
Pbind(
    \degree, Pseq([0, 2, 4, 7], inf),
    \dur, 0.25,
    \amp, 0.8
).play;
```

**Key insight**: Pbind generates **Events** that are `.play`-ed. The Event prototype handles synth creation.

### Note Release Mechanisms

SuperCollider provides multiple release strategies:

| Method | Description |
|--------|-------------|
| **Gated envelopes** | `Env.adsr` with `gate` argument — most common |
| **Fixed duration** | `Env.perc`, `Env.linen` — self-terminating |
| **Explicit release** | `synth.set(\gate, 0)` or `synth.release` |
| **Linen** | Shortcut for gated envelope with doneAction |

Critical: The `gate` argument must be named `\gate` (convention), default > 0, and use `doneAction: 2` (or higher) to free the node.

### Voice Allocation & Polyphony

SuperCollider has **no built-in voice allocator** for MIDI-style polyphony. Common patterns:

```supercollider
// Track active notes in a Dictionary
~activeNotes = Dictionary.new;

// Note on
~activeNotes[noteNum] = Synth(\mySynth, [\freq, noteNum.midicps]);

// Note off
~activeNotes[noteNum].set(\gate, 0);
~activeNotes.removeAt(noteNum);
```

**Pmono**: Reuses a single synth, good for monophonic lines with legato.

### Parameter Modulation During Note Lifetime

Several patterns:

| Approach | Use Case |
|----------|----------|
| **Pseg** | Envelope-like parameter changes over time |
| **Pkey** | Cross-parameter dependencies |
| **Synth control bus** | External modulation sources |
| **NodeProxy/Ndef** | Live code parameter changes |

```supercollider
// Pseg for parameter envelopes
Pbind(
    \freq, Pseg([440, 880, 440], [2, 2], \exp),
    \dur, 0.1
).play;

// Pkey for inter-parameter relationships
Pbind(
    \degree, Pwhite(1, 10),
    \dur, 1 / Pkey(\degree)  // higher notes = shorter
)
```

---

## API Design Recommendations for Your Tick-Based System

Given your constraints:
- Tick-based `onTick()` execution
- Need to store note references for release
- Minimal boilerplate
- Your current thinking: `note = tc.Note(72, v=100).trigger()` then `note.release()`

### Patterns to Adopt

#### 1. **Fluent/Builder Pattern** (from Strudel)
```python
# Chain parameters naturally
note = tc.Note(72).velocity(0.8).pan(0.5).trigger()

# Or with kwargs
note = tc.Note(72, velocity=0.8, pan=0.5).trigger()
```

#### 2. **Context-Aware Note Factory** (from SuperCollider Pbind)
```python
# Track active notes automatically
with tc.pattern() as p:
    p.note(60).trigger()  # C3
    p.note(64).trigger()  # E3
# Auto-release all on context exit
```

#### 3. **Duration-Based Auto-Release** (from Strudel)
```python
# Auto-release after N ticks (no manual release needed)
tc.Note(72).duration(480).trigger()  # 480 ticks = 1 quarter at PPQ=480

# Or use legato for relative duration
tc.Note(72).legato(0.5).trigger()  # 50% of time to next event
```

#### 4. **Voice Pool/Allocator** (SuperCollider-inspired)
```python
# Automatic voice stealing if max polyphony reached
allocator = tc.VoicePool(max_voices=16)

# On note on
voice = allocator.allocate(72)  # Returns voice ID or None
if voice:
    voice.trigger()

# On note off  
allocator.release(72)  # Releases specific note
# or
allocator.release_voice(voice_id)  # Releases by voice ID
```

### Anti-Patterns to Avoid

| Anti-Pattern | Why | Better Alternative |
|--------------|-----|------------------|
| **Manual memory management** | Easy to leak voices | Use context managers or auto-release |
| **Synchronous blocking in onTick** | Blocks audio thread | Queue events, process in tick |
| **Creating new objects every tick** | GC pressure | Object pooling for Voice objects |
| **MIDI note numbers as only input** | Less readable | Accept note names + octave |
| **Implicit global state** | Hard to test | Explicit context/pattern objects |

### Recommended API Sketch

```python
import flvfx as vfx

class NoteContext:
    """Manages a group of notes with automatic cleanup"""
    def __init__(self):
        self._active = {}  # note_id -> Voice
    
    def note(self, pitch, velocity=0.8, **kwargs):
        """Create a note (but don't trigger yet)"""
        n = NoteBuilder(self, pitch, velocity, **kwargs)
        return n
    
    def trigger(self, note_builder):
        """Internal: trigger and track the note"""
        v = vfx.Voice()
        v.note = note_builder.pitch
        v.velocity = note_builder.velocity
        # ... apply other params
        v.trigger()
        self._active[note_builder.id] = v
        return NoteHandle(v, self)
    
    def release(self, note_id):
        """Release a specific note"""
        if note_id in self._active:
            self._active[note_id].release()
            del self._active[note_id]

class NoteBuilder:
    """Fluent interface for note parameters"""
    def __init__(self, ctx, pitch, velocity, **kwargs):
        self.ctx = ctx
        self.pitch = pitch  # Accept "C4" or 60
        self.velocity = velocity
        self.pan = kwargs.get('pan', 0.0)
        self.length = kwargs.get('length')  # Auto-release if set
        self.id = id(self)
    
    def pan(self, val):
        self.pan = val
        return self
    
    def duration(self, ticks):
        self.length = ticks
        return self
    
    def trigger(self):
        return self.ctx.trigger(self)

class NoteHandle:
    """Reference to a playing note"""
    def __init__(self, voice, ctx):
        self.voice = voice
        self.ctx = ctx
    
    def release(self):
        self.voice.release()
    
    def set(self, param, value):
        """Live parameter update (like SuperCollider's .set)"""
        setattr(self.voice, param, value)

# Usage in onTick
tc = NoteContext()

def onTick():
    if should_trigger:
        handle = tc.note("C4", velocity=0.9).pan(-0.5).trigger()
        # Store handle for later release, or...
        
    if should_release:
        handle.release()  # Explicit release
        
    # Or use auto-release
    tc.note("E4").duration(240).trigger()  # Auto-releases after 240 ticks
```

### Key Insights from Research

1. **Strudel's query-based model** is elegant but may not fit tick-based execution — stick with your event-driven approach.

2. **SuperCollider's gate mechanism** is powerful — consider supporting both explicit release AND duration-based auto-release.

3. **Voice allocation is hard** — SuperCollider punts on this; consider providing a built-in allocator.

4. **Parameter modulation** — Support live `.set()` calls on playing notes for filter sweeps, etc.

5. **Naming matters** — Strudel's mini-notation is readable; consider accepting note names ("C4") alongside MIDI numbers.