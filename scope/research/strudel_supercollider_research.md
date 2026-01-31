# Strudel & SuperCollider Research

Combined research on note triggering patterns from Strudel and SuperCollider for TrapCode voice API design.

---

## Strudel

### Overview
JavaScript-based live coding environment inspired by TidalCycles. Uses mini-notation for patterning sounds and MIDI events. Operates on repeating cycles tied to tempo.

### Mini-Notation: Notes, Velocity, Duration

**Notes:**
- Pitch names: `c3`, `e3`, `g3` (note name + octave)
- MIDI numbers: `60`, `62`, `64` (middle C = 60)
- Sequences are space-separated, dividing cycle evenly: `"c3 d3 e3 f3"` gives each 1/4 of cycle

**Velocity:**
- `.velocity(0.8)` — range 0-1 (scaled to 0-127 for MIDI)
- Patternable: `.velocity("<0.5 0.7 0.9>")`

**Duration:**
- Cycle-based: Events fill one cycle by default, subdivided equally
- Elongation `@`: `"c3@2 d3"` makes first note span 2x
- Legato: `.legato(0.5)` — note length as fraction of step duration
- Sustain: `.sustain("<0.5 0.75>")` sets hold time relative to event step

### Pattern Triggering/Scheduling

**Key insight: Patterns are queries, not streams.**

```javascript
// Pattern is a pure function of time
const haps = pattern.queryArc(time, time + interval);

// Scheduler queries at fixed intervals (50ms)
// Events have: begin time, end time, value
```

The scheduler asks "what events should be playing at time T?" rather than pushing events.

- Patterns run in fixed cycles (e.g., 1 cycle = 1 second at 1 BPS)
- Events are queued and sent at exact timestamps
- `noteOffsetMs` (default 10ms) delays note-off for glitch prevention

### Polyphony

Handled via structural operators:

| Notation | Meaning |
|----------|---------|
| `[c3,e3,g3]` | Chord (simultaneous notes) |
| `c3,e3,g3` | Stack (parallel patterns) |
| `<c3 e3 g3>` | Slowcat (sequential over multiple cycles) |

**Polymeter**: `{a b c, d e}` — different subdivisions share same pulse
**Polyrhythm**: `[a b c, d e]` — different subdivisions, different speeds

Unlimited polyphony (limited by hardware). No built-in voice limits or stealing.

### Note-On/Note-Off Semantics

Events have **intrinsic duration** — no explicit release() needed:
- Events specify `whole.begin` and `whole.end`
- Audio engine handles the lifecycle
- For MIDI, `note` parameter triggers note-on at start, note-off at end

---

## SuperCollider

### Overview
Real-time audio synthesis language with client-server architecture. Notes created via Synth objects, often driven by patterns like Pbind for sequencing.

### Synth & Pbind Note Creation

**Direct Synth creation:**
```supercollider
Synth(\default, [\freq, 440, \amp, 0.5])
```

**Pbind (pattern-based):**
```supercollider
Pbind(
    \degree, Pseq([0, 2, 4, 7], inf),
    \dur, 0.25,
    \amp, 0.8
).play;
```

**Key insight**: Pbind generates **Events** that are `.play`-ed. The Event prototype handles synth creation.

### Note Release Mechanisms

| Method | Description |
|--------|-------------|
| **Gated envelopes** | `Env.adsr` with `gate` argument — most common |
| **Fixed duration** | `Env.perc`, `Env.linen` — self-terminating |
| **Explicit release** | `synth.set(\gate, 0)` or `synth.release` |
| **Linen** | Shortcut for gated envelope with doneAction |

The `gate` argument must be named `\gate` (convention), default > 0, and use `doneAction: 2` to free node.

### Voice Allocation & Polyphony

**No built-in voice allocator** for MIDI-style polyphony. Common pattern:

```supercollider
// Track active notes in a Dictionary
~activeNotes = Dictionary.new;

// Note on
~activeNotes[noteNum] = Synth(\mySynth, [\freq, noteNum.midicps]);

// Note off
~activeNotes[noteNum].set(\gate, 0);
~activeNotes.removeAt(noteNum);
```

**Pmono**: Reuses a single synth for monophonic lines with legato.

Each event spawns a new Synth node. Voice stealing must be implemented manually.

### Parameter Modulation During Note Lifetime

| Approach | Use Case |
|----------|----------|
| **synth.set(\param, value)** | Update running Synth |
| **Pseg** | Envelope-like parameter changes over time |
| **Pkey** | Cross-parameter dependencies |
| **Pmono/PmonoArtic** | Monophonic with articulation |

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

## Timing Mechanisms

### Strudel Timing

- **Cycle-based**: Time divided into cycles (e.g., 1 cycle = 1 bar)
- **Subdivisions are implicit**: `"c d e f"` = 4 equal parts of cycle
- **Elongation**: `@` multiplier for relative duration
- **Tempo**: Controlled by `cps` (cycles per second) or `bpm`

**Quarter/Eighth notes etc.** are expressed through pattern structure:
```javascript
// Quarter notes in 4/4 at 120bpm (0.5 cycles/sec)
"c d e f"  // Each note is 1/4 of cycle

// Eighth notes
"c d e f g a b c"  // Each note is 1/8 of cycle

// Mixed (dotted, etc.)
"c@3 d"  // c gets 3/4, d gets 1/4
```

**Rests**: Use `~` for silence
```javascript
"c ~ e ~"  // Notes on 1 and 3, rests on 2 and 4
```

### SuperCollider Timing

- **Clock-based**: TempoClock schedules events
- **\dur key**: Duration until next event (in beats)
- **Quantization**: `.quant` for grid alignment

```supercollider
// Quarter notes
Pbind(\dur, 1)  // 1 beat per event

// Eighth notes
Pbind(\dur, 0.5)

// Mixed rhythms
Pbind(\dur, Pseq([1, 0.5, 0.5, 2], inf))

// Rests
Pbind(\dur, Pseq([1, Rest(1), 1, 1], inf))
```

**Tempo**: Set via `TempoClock.default.tempo = 120/60;` (beats per second)

---

## Key Insights for TrapCode

### What Translates Well to Tick-Based

1. **Object model with stored references** (SuperCollider Synth pattern)
2. **Duration-based auto-release** (both systems)
3. **Live parameter modulation** via `.set()` on active notes
4. **Explicit voice tracking** in a dictionary/pool

### What Doesn't Translate Directly

1. **Query-based patterns** (Strudel) — tick-based is push, not pull
2. **Clock-scheduled events** — need tick-counting instead
3. **Implicit cycle subdivision** — must be explicit in ticks

### Timing Translation

VFX Script has:
- `vfx.context.PPQ` — pulses per quarter note (typically 96 or 480)
- `vfx.context.ticks` — current position in PPQ ticks

**Duration mapping:**
- Quarter note = `PPQ` ticks
- Eighth note = `PPQ / 2` ticks
- 16th note = `PPQ / 4` ticks
- Whole note = `PPQ * 4` ticks

**Offsets from current position:**
- Schedule event at `current_tick + offset_ticks`

---

## Anti-Patterns to Avoid

| Anti-Pattern | Why | Better Alternative |
|--------------|-----|------------------|
| Global state for notes | Conflicts in multi-script | Instance-based contexts |
| Creating objects every tick | GC pressure | Object pooling |
| Busy-waiting in onTick | Blocks processing | State checks only |
| Assuming uniform tick timing | FL ticks vary with CPU | Use cumulative counts |
| Auto-poly without limits | Resource leaks | Expose voice caps + stealing |
| MIDI numbers only | Less readable | Accept note names too |
| Magic implicit behavior | Hard to debug | Explicit duration/release |

---

## Appendix: Source Documents

- `grok_response.md` — Initial Strudel/SuperCollider research
- `kimi_response.md` — Detailed API patterns and code examples
