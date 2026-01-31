# Voice Triggering — Open Questions

Active questions for the voice triggering API design. Move to `voice_triggering.md` once resolved.

---

## Q1: API Style — Factory vs Chaining vs Context

**Option A: Simple Factory (current proposal)**
```python
note = tc.Note(72, v=100).trigger()
note.release()
```

**Option B: Context-Aware Factory**
```python
with tc.voices() as v:
    v.note(72).trigger()
    v.note(76).trigger()
# Auto-release all on exit
```

**Option C: Direct Functions**
```python
handle = tc.trigger(72, v=100)
tc.release(handle)
```

**Initial leaning**: Option A with Option B available for complex patterns.

**Status**: Open

---

## Q2: Timing — How to Express Duration

VFX Script provides:
- `vfx.context.PPQ` — pulses per quarter note
- `vfx.context.ticks` — current tick position

**Option A: Raw ticks**
```python
tc.Note(72).duration(480).trigger()  # 480 ticks
```

**Option B: Beat fractions**
```python
tc.Note(72).duration(1/4).trigger()  # Quarter note
tc.Note(72).duration(1/8).trigger()  # Eighth note
```

**Option C: Named durations**
```python
tc.Note(72).quarter().trigger()
tc.Note(72).eighth().trigger()
```

**Option D: PPQ-relative constants**
```python
tc.Note(72).duration(tc.Q).trigger()      # Quarter
tc.Note(72).duration(tc.Q * 1.5).trigger() # Dotted quarter
tc.Note(72).duration(tc.Q / 3).trigger()   # Triplet eighth
# Where tc.Q reads PPQ at runtime
```

**Sub-questions:**
- How do we handle dotted notes (1.5x duration)?
- How do we handle triplets (2/3x duration)?
- How do we handle ties across bars?
- How do we handle tempo changes mid-song?

**Status**: Open

---

## Q3: Timing — How to Express Offsets/Scheduling

Sometimes you want to trigger a note in the future, not immediately.

**Option A: Delay parameter**
```python
tc.Note(72).delay(tc.Q).trigger()  # Trigger 1 beat from now
```

**Option B: Schedule at absolute tick**
```python
tc.Note(72).at(1920).trigger()  # Trigger at tick 1920
```

**Option C: Quantized triggering**
```python
tc.Note(72).quantize(tc.bar).trigger()  # Trigger at next bar
```

**Sub-question**: Do we need a central scheduler/queue that processes pending events in `onTick()`?

**Status**: Open

---

## Q4: Rests and Silence

How to express "do nothing for X duration"?

**Option A: Explicit rest function**
```python
tc.rest(tc.Q)  # Wait a quarter note before next event
```

**Option B: Pattern-based (Strudel-inspired)**
```python
tc.pattern("C4 ~ E4 ~")  # ~ is rest
```

**Option C: Just use delays**
```python
# No explicit rest — just schedule notes with appropriate offsets
```

**Status**: Open

---

## Q5: Polyphony Management

**Option A: Unlimited (current)**
```python
# Every trigger creates a new voice, no limits
```

**Option B: Voice pool with stealing**
```python
pool = tc.VoicePool(max=8, steal='oldest')
note = pool.note(72).trigger()
```

**Option C: Automatic tracking by note number**
```python
# tc.Note(72) always refers to "the C5 voice"
# Re-triggering same note retriggers the existing voice
tc.Note(72).trigger()  # C5 on
tc.Note(72).release()  # C5 off
tc.Note(72).trigger()  # C5 on again (same voice reused)
```

**Status**: Open

---

## Q6: Separation of Concerns

**Current thinking:**
- `tc.MIDI(incomingVoice)` — for passthrough/modification of incoming notes
- `tc.Note(...)` — for programmatic note creation

Should these share any base class or API? Or stay completely separate?

**Status**: Open

---

## Q7: Duration Location — Builder vs Trigger

Should duration be set on the builder or passed to trigger?

**Option A: Builder method**
```python
tc.Note(72).duration(tc.Q).trigger()
```

**Option B: Trigger parameter**
```python
tc.Note(72).trigger(duration=tc.Q)
```

**Option C: Both (builder sets default, trigger can override)**
```python
note_template = tc.Note(72).duration(tc.Q)
note_template.trigger()  # Uses Q
note_template.trigger(duration=tc.E)  # Overrides to eighth
```

**Status**: Open

---
