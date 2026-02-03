# Strudel Mini-Notation for TrapCode

Design questions and implementation plan for integrating Strudel-style mini-notation into TrapCode.

> **Note:** For detailed implementation steps, see `phase1_tier1_implementation.md`. For the original research, see `research docs/studel/Python Implementation of Strudle's Mini-Notation.md` (some code examples there are outdated — the Phase 1 plan has the corrected versions).

---

## Current TrapCode Infrastructure (Already Solved)

These concerns from the research doc are already handled:

| Concern | TrapCode Solution |
|---------|------------------|
| Tick-based processing | `update()` runs per-tick, uses `vfx.context.ticks` |
| Beat/tick conversion | `beats_to_ticks()` exists, uses `vfx.context.PPQ` |
| Note triggering | `Single` class with `.trigger()` method |
| Duration handling | `Single.l` (beats) → `voice.length` (ticks) |
| Voice lifecycle | `_active_voices` tracking, auto-release via `v.length` |
| Polyphony | `cut=True/False` on trigger, voice tracking per Single |

---

## Naming Conventions ✅ RESOLVED

**Decision:** Rename existing `tc.Note` to `tc.Single` and use `tc.note()` for patterns (Strudel convention).

| TrapCode | Alias | Type | Description |
|----------|-------|------|-------------|
| `tc.Single(m=60)` | `tc.s(m=60)` | Class | One-shot note (renamed from `tc.Note`) |
| `tc.note("0 1 2")` | `tc.n("0 1 2")` | Function | Pattern of notes (new, Strudel-style) |

**Rationale:**
- Follows [Strudel convention](https://strudel.cc/workshop/first-notes/) where `note()` / `n()` creates patterns
- `tc.s()` doesn't conflict with Strudel's `s()` (sound) since FL Studio can't synthesize sounds
- Clear distinction: `Single` = one-shot, `note()` = pattern

**Examples:**

```python
# One-shot (imperative)
tc.Single(m=60, v=100).trigger()
tc.s(m=60).trigger()  # alias

# Pattern (declarative, Strudel-style)
tc.note("60 62 64 65", c=4)
tc.n("0 3 5 7", c=4)  # alias

# Voice-bound pattern
def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    midi.n("0 3 5 7", c=4)  # origin = incoming note
    midi.trigger()
```

**Migration:** Existing `tc.Note` code will need to change to `tc.Single` or `tc.s`.

---

## Open Design Questions

### 1. Cycle Duration ✅ RESOLVED

**Decision:** Configurable via `cycle` parameter (alias: `c`), default = 4 beats (1 bar in 4/4).

**Rationale:**
- Consistent with TrapCode's existing convention: 1 beat = 1 quarter note
- `c=4` means cycle spans 4 beats (1 bar), matching how `Single(l=4)` is a whole note
- Most rhythmic patterns are naturally "per bar"

**API:**

```python
# Default: 1 cycle = 4 beats (1 bar in 4/4)
tc.n("0 1 2 3")           # 4 quarter notes across 1 bar
tc.n("0 1")               # 2 half notes across 1 bar

# Override with cycle/c parameter
tc.n("0 1 2 3", cycle=1)  # 4 sixteenth notes in 1 beat
tc.n("0 1 2 3", c=1)      # same, using alias

tc.n("0 1 2 3", c=8)      # 4 half notes across 2 bars
```

**Aliases:**
| Alias | Full Name |
|-------|-----------|
| `c` | `cycle` |

**Note:** `c` is reserved. If `channel` is added to `Single` later, use `ch` as its alias.

---

### 2. Value Semantics ✅ RESOLVED

**Decision:** Two APIs with different origins, unified Pattern engine.

| API | Context | `0` means | Use case |
|-----|---------|-----------|----------|
| `midi.n("0 1 2 3")` | `onTriggerVoice` | Incoming note + offset | Arpeggios, harmonization |
| `tc.n("0 1 2 3")` | `onTick` / module scope | MIDI 60 (C5) + offset | Programmatic sequences |

**Rationale:**
- `midi.n()` uses incoming voice as origin — natural for piano roll workflows
- `tc.n()` follows Strudel convention (0 = C5 / MIDI 60)
- Negative values go below origin: `-3 -2 -1 0 1 2 3`
- `~` for rests (Strudel convention)

**API Examples:**

```python
# In onTriggerVoice — origin is incoming note
def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    midi.n("0 3 5 7")  # Arpeggio: root, +3, +5, +7 semitones
    midi.trigger()

# Conditional patterns based on incoming note
def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    if midi.note < 60:
        midi.n("0 1 2 3")
    else:
        midi.n("0 1 2 3").reverse()
    midi.trigger()

# In onTick — origin is MIDI 60 (C5)
kick_pattern = tc.n("36 ~ 36 ~", c=4)  # Kick drum pattern

def onTick():
    kick_pattern.tick()
    tc.update()
```

**Internal Tick System:**
- Patterns use internal tick counter (like `midi retrigger.py`)
- Advances every `onTick()` call, even when FL transport is stopped
- Each pattern tracks its start tick for relative timing
- `midi.n()` patterns are tied to parent voice lifecycle (release when parent releases)

**Unified Engine:**
Both APIs share the same `Pattern` class. The only differences:
- Origin note (incoming vs MIDI 60)
- Lifecycle (tied to voice vs standalone)

---

### 3. Trigger Behavior ✅ RESOLVED

**Decision:** Option A — First pattern note fires immediately on `midi.trigger()`.

```python
def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    midi.n("0 3 5 7", c=4)  # 4 notes over 4 beats
    midi.trigger()          # First note (0) fires NOW
                            # +3 fires at beat 1
                            # +5 fires at beat 2
                            # +7 fires at beat 3
```

**Rationale:**
- User pressed a key → they expect to hear something immediately
- Position 0 in the pattern = "now" (the trigger moment)
- Matches `midi retrigger.py` behavior

**Future Feature:** `.quantize()` to snap pattern start to beat grid.

```python
# Future API (not Phase 1)
midi.n("0 3 5 7").quantize()  # Snaps to next beat boundary
```

---

### 4. Note Properties Beyond Pitch ✅ RESOLVED

**Decision:** Both object syntax AND chained methods, with object syntax taking priority.

**Object Syntax** — per-note explicit overrides:
```python
"60{v=100, p=0.25, x=0.5} 62{v=80}"
```

**Chained Methods** — polyrhythmic modulation:
```python
tc.n("0 2").v("25 50 75 100")  # 2-note pitch cycle, 4-note velocity cycle
```

**Precedence:** Object syntax wins. Explicit `{v=100}` is not overridden by `.v()` chain.

**Available Attributes (using TrapCode aliases):**

| Key | Alias for | Range | Description |
|-----|-----------|-------|-------------|
| `v` | velocity | 0-127 | Note velocity |
| `l` | length | beats | Note duration |
| `p` | pan | -1 to 1 | Stereo pan |
| `o` | output | 0+ | Output port |
| `x` | fcut | -1 to 1 | Mod X / filter cutoff |
| `y` | fres | -1 to 1 | Mod Y / filter resonance |
| `fp` | finePitch | any | Microtonal offset |

Full names also accepted: `{velocity=100, pan=0.25}`

**Polyrhythmic Example:**
```python
tc.n("0 2").v("25 50 75 100")
# Pitch cycles: [0, 2] (2 events)
# Velocity cycles: [25, 50, 75, 100] (4 events)
# Creates evolving combinations over multiple cycles
```

**Combined Example:**
```python
tc.n("60{v=127} 62 64").v("80 100")
# Note 60 always v=127 (object wins)
# Notes 62, 64 cycle through v=80, v=100
```

---

### 5. Pattern State Management ✅ RESOLVED

**Decision:** Explicit `.start()` / `.stop()` control with internal tick counter.

**Behavior:**
- Patterns use an **internal tick counter** (advances every `onTick()`, works when FL stopped)
- Standalone patterns (`tc.n()`) require explicit `.start()` to begin
- Voice-bound patterns (`midi.n()`) start on `.trigger()` and stop when parent releases
- `.reset()` available for manual sync

**API:**

```python
# Standalone pattern — explicit control
pattern = tc.n("0 1 2 3", c=4)

def onTick():
    pattern.tick()  # Advances internal counter, fires events if started
    tc.update()

# Start/stop control
pattern.start()   # Begin pattern playback
pattern.stop()    # Stop pattern playback
pattern.reset()   # Reset to beginning (doesn't start)

# Voice-bound pattern — lifecycle tied to parent
def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    midi.n("0 3 5 7", c=4)  # Pattern created
    midi.trigger()          # Pattern starts, first note fires immediately
    # Pattern auto-stops when parent voice releases
```

**Internal Tick Counter:**
- Like `midi retrigger.py`, uses module-level `_tickCount`
- Advances every `onTick()` call regardless of FL transport state
- Each pattern tracks its `_startTick` for relative positioning

**Tick Query Strategy (Approach A):**
- Each `tick()` call queries a **1-tick-wide arc** in cycle time
- Events are returned only if `has_onset() == True` (their `whole.begin` falls within the query arc)
- This handles fractional tick boundaries correctly (e.g., 5 notes over 4 beats = events at tick 76.8)
- No mutable "already fired" state needed — purely functional query model

---

### 6. Operator Priority ✅ RESOLVED

**Decision:** Start with Tier 1 operators only. See `phase1_tier1_implementation.md` for detailed plan.

**Tier 1 (Phase 1 — implement first):**
- `[a b c]` — subdivision
- `<a b c>` — cycle alternation
- `*n` — fast (time compression)
- `/n` — slow (time expansion)
- `~` — rest/silence

**Tier 2 (Phase 5 — after MVP works):**
- `a, b` — polyphony (stack)
- `!n` — replicate
- `@n` — weighting

**Tier 3 (Phase 5 — advanced):**
- `?p` — degrade (probabilistic)
- `a|b` — random choice
- `(k,n)` — Euclidean rhythms

---

### 7. Parser Location

**Question:** Where does the parser code live?

**Options:**
- A) Inline in `trapcode.py` (single file, simple deployment)
- B) Separate module `trapcode_strudel.py` (cleaner separation)
- C) Lazy import inside `trapcode.py` (optional feature)

**Recommendation:** Option A. TrapCode is already a single-file library for easy copy-paste into FL Studio. Keep it that way.

---

### 8. Error Handling

**Question:** What happens on parse errors?

**Recommendation:** Fail loudly at parse time (in `createDialog()`), not silently at runtime.

```python
# Bad pattern should raise immediately
pattern = tc.n("0 1 [ 2")  # SyntaxError: Unclosed bracket

# Runtime errors (e.g., invalid MIDI note) should warn but continue
pattern = tc.n("200")  # Warning: MIDI note 200 clamped to 127
```

---

### 9. UI Text Input Integration

**Question:** Should patterns be editable via `ui.Text()`?

This would allow live pattern editing without reloading the script.

```python
# In createDialog()
ui.Text("Pattern", par_name="pattern_str", default="60 62 64 65")

# In onTick()
if par.pattern_str.changed():
    try:
        pattern = tc.n(par.pattern_str.val)
    except SyntaxError as e:
        print(f"[Pattern] {e}")
```

**Recommendation:** Support this use case but don't require it. Patterns can be defined statically or dynamically.

---

## Implementation Phases

### Phase 1: Core Engine ✅ COMPLETE
- [x] `Event` dataclass (value, whole, part arcs)
- [x] `Event.has_onset()` method — returns True when `whole.begin == part.begin`
- [x] `Pattern` class with `query(arc)` method
- [x] `Pattern.pure(value)` — constant pattern (future-proofed for multi-cycle queries)
- [x] `Pattern.fast(n)` / `Pattern.slow(n)` — must transform both `whole` AND `part`
- [x] `sequence(*patterns)` — subdivision with proper time transformation
- [x] Time conversion: ticks ↔ Fraction-based cycle time
- [x] `tick_arc()` — 1-tick-wide query windows for fractional boundary handling
- [x] Internal tick counter (works when FL transport stopped)
- [x] `pattern.tick()` — query current tick arc, fire events where `has_onset() == True`
- [x] **Bonus:** Cycle-latched parameter updates for smooth dynamic `c` changes (risers)
- [x] **Bonus:** Custom `Fraction` class to avoid FL Studio crash from stdlib fractions module

### Phase 2: Parser (Tier 1 Operators) ✅ COMPLETE
- [x] Tokenizer (regex-based, handles `-` as rest and `-3` as negative number)
- [x] Recursive descent parser
- [x] `[a b c]` subdivision
- [x] `<a b c>` alternation (simplified: 1-tick arcs never cross cycle boundaries)
- [x] `*n` and `/n` time scaling
- [x] `~` and `-` as rest (Strudel-compatible)
- [ ] Object syntax: `60{v=100, p=0.5}` with TrapCode aliases

### Phase 3: Integration + Chained Methods (Partial)
- [x] `tc.n()` entry point (standalone, origin = MIDI 60)
- [x] `midi.n()` method (origin = incoming note)
- [x] Connect events to `tc.Note.trigger()` (Note, not Single — rename not done)
- [x] Parent voice lifecycle (release pattern when parent releases via `tc.stop_patterns_for_voice()`)
- [x] Dynamic `c` and `root` parameters accept UI wrappers
- [ ] Respect `cut` behavior
- [ ] Chained methods: `.v()`, `.pan()`, `.x()`, `.y()` for polyrhythmic modulation
- [ ] Precedence: object syntax wins over chained methods

### Phase 4: Polish
- [ ] Error messages with position info
- [x] `pattern.reset()` for manual sync
- [ ] UI Text input hot-reload pattern

### Phase 5: Advanced Operators (Tier 2-3)
- [ ] `@n` — weighting/elongation
- [ ] Polyphony `,`
- [ ] `!n` — replicate
- [ ] Euclidean `(k,n)`
- [ ] Probabilistic `?`
- [ ] `.quantize()` — snap pattern start to beat grid

---

## Code Size Estimate

Based on the Phase 1 implementation plan (with corrected implementations):
- Core data structures (Event, Arc, Time): ~30 lines
- Pattern class + pure/fast/slow/sequence: ~120 lines
- Tokenizer: ~30 lines
- Parser: ~100 lines
- FL Studio integration (tick, time conversion): ~50 lines

**Total: ~330 lines** added to trapcode.py

All pattern code should be placed in a distinct section marked with a separator (see `phase1_tier1_implementation.md` for details).

---

## Next Steps

1. ~~Confirm answers to design questions above~~ ✅
2. ~~Prototype Phase 1 (core engine) in `scope.py`~~ ✅
3. ~~Test with simple patterns in FL Studio~~ ✅
4. ~~Add parser (Phase 2)~~ ✅
5. ~~Integrate fully (Phase 3)~~ ✅ (core integration done)

### Remaining Work
1. Object syntax: `60{v=100, p=0.5}` — per-note property overrides
2. Chained methods: `.v()`, `.pan()`, `.x()`, `.y()` — polyrhythmic modulation
3. `@n` weighting/elongation operator
4. `cut` behavior integration
5. Polish: error messages, UI Text hot-reload
