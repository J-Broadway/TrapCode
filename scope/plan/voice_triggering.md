# Voice Triggering Architecture

## Status: In Design

**Related docs:**
- [Research](../research/strudel_supercollider_research.md) — Strudel/SuperCollider patterns
- [Archived Questions](archive/voice_triggering_questions.md) — Initial design questions (resolved)

---

## Overview

Design a note/voice API for TrapCode that enables programmatic MIDI note creation with minimal boilerplate while maintaining full control. This is the core creative coding feature of TrapCode.

---

## Design Goals

1. **Minimal boilerplate** for common cases
2. **Full control** when needed
3. **Intuitive timing** (quarter notes, rests, offsets)
4. **Safe polyphony** with optional voice limits
5. **Live parameter modulation** on active notes
6. **Works in tick-based environment** (not event-driven)

---

## Decisions Made

### D1: Beat-Relative Timing

**Decision**: Use beat-relative values, not raw ticks.

| Value | Duration |
|-------|----------|
| `4` | Whole note |
| `2` | Half note |
| `1` | Quarter note (one beat) |
| `0.5` | Eighth note |
| `0.25` | Sixteenth note |

Syncs automatically to project BPM via PPQ.

**Rationale**: Intuitive, musical, portable across tempos.

---

### D2: Note Constructor

**Decision**: 
```python
myNote = tc.Note(m=72, v=100, l=1)
# m = MIDI note number (0-127)
# n = note string alternative, e.g., "C5" (mutually exclusive with m)
# v = velocity (0-127), default 100
# l = length in beats, default 1
```

- `l` is the **default duration** for this note
- Can be overridden at trigger time

---

### D3: Trigger Semantics

**Decision**: Trigger is **looping by default**.

```python
myNote.trigger(b=1)           # Loop: trigger every 1 beat
myNote.trigger(b=1).once()    # One-shot: trigger once with 1 beat duration
myNote.trigger(b=1, d=4)      # Duration-limited: loop for 4 beats then stop
myNote.stop()                 # Stop looping
```

**Parameters:**
- `b` (beat): Trigger period — how often to trigger (default: 1)
- `l` (length): Note duration — overrides Note's built-in `l` (default: Note's `l`)
- `d` (duration): Total loop duration — how long to keep looping

**Example:**
```python
myNote = tc.Note(m=72, v=100, l=1)
myNote.trigger(b=1, l=0.5)
# Triggers every 1 beat
# Note held for 0.5 beats (50% duty cycle)
# 0.5 beats silence
# Repeat
```

---

### D4: Sequence Modes

**Decision**: Two modes via `.mode()`:

#### Mode: 'fit' (default)
Sequence has fixed length. Notes are compressed/stretched to fit.

```python
mySeq = tc.Sequence().mode('fit').length(1.5)
with mySeq:
    N(72)      # Calculated: 0.5 beats (1.5 / 3)
    N(73)      # Calculated: 0.5 beats
    N(74)      # Calculated: 0.5 beats
```

User can override individual note weights. Total length stays fixed; notes distribute by weight:

```python
mySeq.mode('fit').length(1.5)
with mySeq as s:
    s.N(72)          # weight 1
    s.N(73)          # weight 1  
    s.N(74, l=2)     # weight 2
# Total weight = 4
# N(72): 1/4 × 1.5 = 0.375 beats
# N(73): 1/4 × 1.5 = 0.375 beats
# N(74): 2/4 × 1.5 = 0.75 beats
# Sum = 1.5 ✓ (total is sacred)
```

In fit mode, `l` is a **weight multiplier**, not absolute duration.

#### Mode: 'grow'
Sequence grows based on note lengths. `.length()` sets default per-note length.

```python
mySeq = tc.Sequence().mode('grow').length(2) # if .length isn't set defualt is 1
with mySeq:
    N(72)         # 2 beats (default)
    N(73, l=0.5)  # 0.5 beats (override)
    N(74, l=1)    # 1 beat (override)
# Total: 3.5 beats
```

**Speed modifier** (intuitive: higher = faster):
```python
mySeq.speed(2)    # 2x faster (half duration)
mySeq.speed(0.5)  # Half speed (double duration)
mySeq.speed(1)    # Normal (default)
```

Internally: `actual_duration = base_duration / speed`

---

### D5: Chord

**Decision**: Chord is simultaneous notes.

```python
Chord1 = tc.Chord()
with Chord1:
    N(60)  # C4
    N(64)  # E4
    N(67)  # G4

Chord1.trigger(b=1)  # All three trigger together every beat
```

---

### D6: Transforms

**Decision**: Transforms return new Sequence/Chord.

```python
# Arp: Chord → Sequence
myArp = Chord1.arp(order='up', rate=0.25)
# [C, E, G] chord becomes [C, E, G] sequence at sixteenth notes

# Trancegate: Chord → Sequence with gate pattern
myGated = Chord1.trancegate(pattern=[1,0,1,0], rate=0.25, length=0.5)
# Chord plays on 1s, silent on 0s, at sixteenth rate
```

---

### D7: Separation of Concerns

**Decision**:
- `tc.MIDI(incomingVoice)` — Passthrough/modification of incoming notes
- `tc.Note(...)` — Programmatic note creation

These are separate classes with no shared base.

---

### D8: Context Manager Building

**Decision**: Hybrid approach — `N()` is a method on the container.

```python
mySeq = tc.Sequence().mode('grow')
with mySeq as s:
    s.N(72)
    s.N(73, l=0.5)
    s.N(74, v=80)

myChord = tc.Chord()
with myChord as c:
    c.N(60)
    c.N(64)
    c.N(67)
```

**Rationale**: Explicit, IDE-friendly, no global state, no nesting bugs.

---

### D9: Speed Modifier

**Decision**: `.speed()` is intuitive — higher values = faster playback.

```python
mySeq.speed(2)    # 2x faster (half duration)
mySeq.speed(0.5)  # Half speed (double duration)
```

Formula: `actual_duration = base_duration / speed`

**Rationale**: Matches common mental model ("speed up" = go faster).

---

### D10: Scheduler Integration

**Decision**: User calls `tc.update()` in `onTick()`. Scheduler processes all active triggers.

```python
def onTick():
    # User logic...
    tc.update()  # Process triggers, fire notes, handle releases
```

**Key behaviors:**
- `beats_to_ticks()` exposed for advanced users
- Float precision internally, int at comparison
- `quantize=True` option for beat-aligned start
- `cut=True` default for mono behavior (release previous before new)
- One-time reminder if triggers registered but update not called

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      User Code                          │
│  note = tc.Note(m=72, l=1)                              │
│  seq = tc.Sequence().mode('grow')                       │
│  chord = tc.Chord()                                     │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                    Builders                             │
│  Note: (m, n, v, l) → single note config                │
│  Sequence: ordered list of Notes + mode + timing        │
│  Chord: unordered set of Notes (simultaneous)           │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                    Trigger Engine                       │
│  .trigger(b, l, d) → creates TriggerState               │
│  - Tracks loop timing, active voices                    │
│  - Handles .once(), .stop()                             │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                    Scheduler                            │
│  - Processes all active TriggerStates each tick         │
│  - Fires triggers at correct times                      │
│  - Handles auto-release                                 │
│  - Called via tc.update() in onTick()                   │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                    vfx.Voice                            │
│  (FL Studio's native voice object)                      │
└─────────────────────────────────────────────────────────┘
```

---

## Open Questions (Critical)

### Q1: Context Manager Mechanics — RESOLVED

**Decision**: Option C (Hybrid) — `N` is a method on the container.

```python
with mySeq as s:
    s.N(72)
    s.N(73, l=2)
```

**Rationale**: Explicit, no magic globals, IDE autocomplete works, no nesting bugs.

---

### Q2: Fit Mode Override Behavior — RESOLVED

**Decision**: Weights distribute within fixed total. `l` is a weight multiplier.

```python
mySeq.mode('fit').length(1.5)
with mySeq as s:
    s.N(72)          # weight 1 → 0.375 beats
    s.N(73)          # weight 1 → 0.375 beats  
    s.N(74, l=2)     # weight 2 → 0.75 beats
# Total = 1.5 (sacred)
```

**Rationale**: "Fit" means fit—total stays fixed, notes distribute proportionally.

---

### Q3: Scheduler Integration

User must call something in `onTick()` to process triggers.

```python
def onTick():
    tc.update()  # Process all active triggers
```

#### Q3.1: TriggerState Structure — RESOLVED

```python
class TriggerState:
    # Configuration (set at trigger time)
    source          # Reference to Note/Sequence/Chord
    beat_period     # How often to trigger (1 = every beat)
    note_length     # How long to hold (0.5 = half beat)
    duration_limit  # Total duration before auto-stop (None = forever)
    is_oneshot      # True if .once() was called
    
    # For sequences only
    sequence_position   # Which note in sequence we're on
    note_offsets        # When each note starts (cumulative beats)
    
    # Runtime state
    last_trigger_tick   # When we last triggered
    start_tick          # When this trigger began (for duration limit)
    active_voices       # List of (voice, release_tick) — per-state, not global
    stopped             # True if .stop() was called
```

**Decisions:**
- `beat_period` for sequences = how often entire sequence repeats
- `active_voices` is per-TriggerState (clear ownership, simple `.stop()`)

#### Q3.2: Beat → Tick Conversion — RESOLVED

```python
def beats_to_ticks(beats):
    """Convert beats to ticks. Exposed as tc.beats_to_ticks() for advanced users."""
    return beats * vfx.context.PPQ  # Returns float

# Internal: keep float for precision
# Only int() when comparing to vfx.context.ticks
```

**Decisions:**
- Exposed as `tc.beats_to_ticks()` for advanced users
- No PPQ caching (negligible gain, added complexity)
- Keep float internally, `int()` only at comparison time (preserves precision for cumulative calculations)

#### Q3.3: Trigger Logic — RESOLVED

**Basic trigger check:**
```python
def should_trigger(self, current_tick):
    period_ticks = self.beat_period * PPQ
    
    if self.last_trigger_tick is None:
        return True  # First trigger
    
    return current_tick >= self.last_trigger_tick + period_ticks
```

**Decisions:**

1. **Mid-song start**: User chooses via `quantize` parameter
   ```python
   myNote.trigger(b=1)               # Fire immediately (default)
   myNote.trigger(b=1, quantize=True) # Wait for next beat boundary
   ```

2. **Sequence note overlap**: User controls via mode
   ```python
   mySeq.mode('overlap')  # Notes can overlap (default, polyphonic)
   mySeq.mode('cut')      # Previous note releases when next starts (monophonic)
   ```

**Sequence playback logic:**
```python
# Track cycle position
time_in_cycle = current_tick - last_cycle_start_tick
current_offset = note_offsets[sequence_position]

if time_in_cycle >= beats_to_ticks(current_offset):
    fire_note(sequence_position)
    sequence_position += 1

# Reset cycle when period elapses
if current_tick >= last_cycle_start_tick + beats_to_ticks(beat_period):
    sequence_position = 0
    last_cycle_start_tick = current_tick
```

#### Q3.4: Release Tracking — RESOLVED

**Basic release flow:**
```python
# On trigger:
voice = vfx.Voice()
voice.note = note_config.m
voice.velocity = note_config.v
voice.trigger()

release_tick = current_tick + beats_to_ticks(note_length)
self.active_voices.append((voice, release_tick))

# On each update():
for voice, release_tick in self.active_voices[:]:
    if current_tick >= int(release_tick):
        voice.release()
        self.active_voices.remove((voice, release_tick))
```

**Decisions:**

1. **Voice creation**: Always create new `vfx.Voice()` (simple). Optimize to pooling later if needed.

2. **Cut behavior on triggers**: `cut=True` by default — releases previous voice before firing new
   ```python
   myNote.trigger(b=1)             # cut=True (default), mono behavior
   myNote.trigger(b=1, cut=False)  # Allow overlapping voices (poly)
   ```

3. **Cut logic:**
   ```python
   if self.cut:
       for voice, _ in self.active_voices:
           voice.release()
       self.active_voices.clear()
   
   # Then fire new note...
   ```

**Note:** This is separate from sequence `.mode('cut')` vs `.mode('overlap')`, which controls note-to-note behavior within a sequence. Trigger `cut` controls iteration-to-iteration behavior.

#### Q3.5: Missing tc.update() — RESOLVED

**Decision**: One-time warning on first `.trigger()` call.

```python
_update_reminder_shown = False

def trigger(self, ...):
    global _update_reminder_shown
    if not _update_reminder_shown:
        print("[TrapCode] Reminder: Call tc.update() in onTick() for triggers to fire")
        _update_reminder_shown = True
    # ... rest of trigger logic
```

Not an error, just a helpful reminder shown once per session.

**Status**: RESOLVED

---

### Q4: Simultaneous Input Handling

For `arp()` and `trancegate()`, chords provide the notes. But what about:
- Live input (incoming MIDI)?
- Multiple chords combined?

**Status**: Needs exploration

---

## Research Insights

From Strudel:
- Patterns as queries (time → events) is elegant but doesn't fit tick-based
- Duration is intrinsic to events (no manual release needed)
- Mini-notation is readable: `"c4 ~ e4 g4"` expresses a lot concisely

From SuperCollider:
- Voice allocation is explicitly user's responsibility
- `synth.set(\param, value)` for live modulation is powerful
- Gate-based release vs fixed duration are both valid patterns

---

## Implementation Approach

**Iterative development with user feedback loops.**

Each phase follows this cycle:
1. **Scope dialogue** — Confirm what's being built, clarify edge cases
2. **Implement** — Build the minimal feature set
3. **User tests** — User tests in FL Studio, provides feedback
4. **Iterate** — Feedback may change scope, architecture, or priorities

This approach is critical because:
- User feedback in real FL Studio environment reveals issues design docs miss
- Early testing prevents compounding architectural mistakes
- Scope naturally evolves as features are used

---

## Implementation Phases

### Phase 1: Core Note + One-Shot Trigger
**Scope**: Simplest possible note triggering — no looping yet.

- [ ] `tc.Note(m, v, l)` builder (no `n` string notation yet)
- [ ] `.trigger()` one-shot only (fires once, releases after `l` beats)
- [ ] `tc.update()` scheduler stub
- [ ] `tc.beats_to_ticks()` helper

**User test**: Can trigger a note from a button press, note releases automatically.

**Status**: Not started

---

### Phase 1.5: Looping Triggers
**Scope**: Add looping behavior to Phase 1.

- [ ] `.trigger(b=1)` loops every beat
- [ ] `.trigger(b=1).once()` one-shot with beat timing
- [ ] `.stop()` to halt loop
- [ ] `cut=True/False` parameter

**User test**: Note loops on beat, can stop it, cut behavior works.

**Status**: Not started — depends on Phase 1 feedback

---

### Phase 2: Sequences (Grow Mode)
**Scope**: Sequential note playback, grow mode only.

- [ ] `tc.Sequence().mode('grow')`
- [ ] Context manager: `with mySeq as s: s.N(...)`
- [ ] Sequential playback with `.trigger(b=4)`
- [ ] `.speed()` modifier

**User test**: Can build and play a sequence, speed affects playback.

**Status**: Not started — depends on Phase 1.5 feedback

---

### Phase 3: Chords + Sequence Fit Mode
**Scope**: Simultaneous notes, fit mode compression.

- [ ] `tc.Chord()` with context manager
- [ ] Chord `.trigger()` fires all notes together
- [ ] Sequence `.mode('fit')` with weight distribution
- [ ] `.mode('cut')` vs `.mode('overlap')` for sequences

**User test**: Chords play together, fit mode compresses correctly.

**Status**: Not started — depends on Phase 2 feedback

---

### Phase 4: Transforms
**Scope**: Chord-to-sequence operations.

- [ ] `.arp(order, rate)` — chord to arpeggiated sequence
- [ ] `.trancegate(pattern, rate)` — rhythmic gating

**User test**: Arp creates playable sequence from chord.

**Status**: Not started — depends on Phase 3 feedback

---

### Phase 5: Note String Notation + Advanced
**Scope**: Quality-of-life and advanced features.

- [ ] `n="C5"` string notation for notes
- [ ] `quantize=True` for beat-aligned start
- [ ] `tc.Comp` base class (if still needed)
- [ ] Voice pooling optimization (if needed)

**User test**: String notation works, quantize aligns correctly.

**Status**: Not started — depends on earlier phases

---

### Backlog (Post-MVP)
- Live MIDI input handling for arp/trancegate
- Multiple chord combination
- Custom BPM/scale/boundaries in Comp
- Pattern mini-notation (Strudel-inspired)

---

## Discussion Log

### 2026-01-31: Initial Planning

Key insight from research: Timing is the crucial challenge. Decided on beat-relative values (1 = quarter) synced to BPM.

### 2026-01-31: Core Decisions

Established:
- Beat-relative timing (1=quarter, 0.5=eighth, etc.)
- Note constructor with m/n/v/l parameters
- Trigger is looping by default, use .once() for one-shot
- Sequence has two modes: 'fit' and 'grow'
- Transforms return new objects

**Critical open items:**
1. ~~Context manager mechanics for building~~ → Resolved: D8
2. ~~Fit mode override behavior~~ → Resolved: weights in D4
3. Scheduler design → Still open

### 2026-01-31: Fit Mode & Context Manager Decisions

Resolved key API questions:
- **Context manager**: Use hybrid approach `with mySeq as s: s.N(...)` — explicit, no magic
- **Fit mode weights**: Total is sacred, `l` is a weight multiplier for proportional distribution
- **Speed**: Intuitive semantics — `speed(2)` = 2x faster

~~**Remaining critical item**: Scheduler design (Q3)~~ → RESOLVED

### 2026-01-31: Scheduler Design Complete

Resolved all scheduler questions:
- **Q3.1 TriggerState**: Defined structure with per-state voice tracking
- **Q3.2 Beat→Tick**: Float internally, int at comparison, exposed as `tc.beats_to_ticks()`
- **Q3.3 Trigger Logic**: Quantize parameter for mid-song start, mode('cut'/'overlap') for sequences
- **Q3.4 Release Tracking**: Simple voice creation, `cut=True` default for mono behavior
- **Q3.5 Missing update()**: One-time warning reminder

**All critical scheduler questions resolved. Ready for implementation.**

### 2026-01-31: Implementation Approach

Established iterative development cycle:
1. Scope dialogue → Implement → User tests → Iterate

Broke phases into smaller chunks with clear "user test" criteria. Each phase depends on feedback from previous. This prevents architectural mistakes from compounding.

**Next step**: Begin Phase 1 scope dialogue.

---
