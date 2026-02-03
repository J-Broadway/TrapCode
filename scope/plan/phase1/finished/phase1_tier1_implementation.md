# Phase 1 Tier 1: Core Pattern Engine + Basic Operators

Implementation plan for the foundational mini-notation system in TrapCode.

---

## Code Organization

All Strudel-related pattern code should be placed in a distinct section of `trapcode.py`, marked with a clear separator for organization:

```python
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                         PATTERN ENGINE (Strudel)                          ║
# ║  Mini-notation parser and temporal pattern system inspired by Strudel/    ║
# ║  TidalCycles. See: https://strudel.cc                                     ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
```

This keeps the pattern system visually separate from TrapCode's existing voice/MIDI infrastructure.

---

## Goal

Implement a working pattern engine with these operators:
- `[a b c]` — subdivision
- `<a b c>` — cycle alternation
- `*n` — fast (time compression)
- `/n` — slow (time expansion)
- `~` — rest/silence

---

## Implementation Steps

### Step 1: Core Data Structures

**Files:** `trapcode.py` (or prototype in `scope/scope.py` first)

**Deliverables:**
- [x] `Time` type alias (`Fraction`)
- [x] `Arc` type alias (`tuple[Time, Time]`)
- [x] `Event` dataclass with fields:
  - `value: Any` — MIDI note number (or None for rest)
  - `whole: Optional[Arc]` — original metric span (the "logical" event duration)
  - `part: Arc` — actual active time window (intersection with query arc)
- [x] `Event.has_onset()` method — returns `True` if `whole.begin == part.begin`
- [x] Basic `Pattern` class with `query(arc: Arc) -> list[Event]`

**Key Concept: `whole` vs `part`**

When you query a pattern with an arc, you get back events where:
- `whole` = the original, complete time span of the event (e.g., "this note occupies beat 2")
- `part` = the intersection of `whole` with your query arc

An event `has_onset()` when your query arc contains the actual start of the event. This is how we know when to trigger a note vs when we're just seeing a fragment of an ongoing event.

**`Pattern.pure()` Implementation (future-proof):**

The `pure(value)` function creates a constant pattern where the value repeats every cycle. The implementation correctly handles multi-cycle query arcs by returning one event per cycle:

```python
@staticmethod
def pure(value):
    """Constant pattern: value repeats every cycle"""
    def query(arc):
        events = []
        cycle_start = int(arc[0])
        cycle_end = int(arc[1]) if arc[1] == int(arc[1]) else int(arc[1]) + 1
        
        for c in range(cycle_start, cycle_end):
            whole = (Fraction(c), Fraction(c + 1))
            part_start = max(arc[0], whole[0])
            part_end = min(arc[1], whole[1])
            if part_start < part_end:
                events.append(Event(value, whole, (part_start, part_end)))
        return events
    return Pattern(query)
```

**Why future-proof:** The `whole` span represents the event's intrinsic timing (one cycle), not the query arc. This enables:
- Pattern preview/visualization (query multiple cycles at once)
- Batch processing for performance (cache events ahead)
- Pattern composition (operations that depend on accurate event timing)

**Test:** Create a simple pattern manually and verify `query()` returns expected events.

```python
# Test: constant pattern — single cycle query
p = Pattern.pure(60)
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 1
assert events[0].value == 60
assert events[0].whole == (Fraction(0), Fraction(1))  # intrinsic span
assert events[0].part == (Fraction(0), Fraction(1))   # same as query
assert events[0].has_onset()  # whole.begin == part.begin == 0

# Test: constant pattern — multi-cycle query (future use case)
events = p.query((Fraction(0), Fraction(3)))
assert len(events) == 3  # one event per cycle
assert events[0].whole == (Fraction(0), Fraction(1))
assert events[1].whole == (Fraction(1), Fraction(2))
assert events[2].whole == (Fraction(2), Fraction(3))

# Test: partial cycle query
events = p.query((Fraction(1, 2), Fraction(3, 2)))
assert len(events) == 2  # spans parts of cycle 0 and cycle 1
assert events[0].whole == (Fraction(0), Fraction(1))
assert events[0].part == (Fraction(1, 2), Fraction(1))  # clipped to query
assert events[0].has_onset() == False  # onset was at 0, not in query
assert events[1].whole == (Fraction(1), Fraction(2))
assert events[1].part == (Fraction(1), Fraction(3, 2))  # clipped to query
assert events[1].has_onset() == True  # onset at 1 is in query
```

---

### Step 2: Time Conversion Layer

**Deliverables:**
- [x] `ticks_to_time(ticks: int, ppq: int, cycle_beats: int) -> Time`
- [x] `time_to_ticks(t: Time, ppq: int, cycle_beats: int) -> int`
- [x] `tick_arc(tick: int, ppq: int, cycle_beats: int) -> Arc` — returns 1-tick-wide query window
- [x] Module-level `_internal_tick` that advances every `update()` call

**Key Concept: 1-Tick Query Windows**

VFX Script calls `onTick()` once per PPQ tick. To handle events that fall on fractional tick boundaries (e.g., 5 notes over 4 beats = events at tick 76.8), we query a 1-tick-wide arc:

```
tick 76: query arc (76/384, 77/384)
tick 77: query arc (77/384, 78/384)
```

An event starting at cycle time 1/5 (= tick 76.8) will appear in the tick 76 query with `has_onset() = True`, so we fire it then.

**Test:** Verify conversions are reversible and handle edge cases.

```python
# Test: round-trip conversion
ppq = 96
cycle_beats = 4
ticks = 192  # 2 beats
t = ticks_to_time(ticks, ppq, cycle_beats)
assert t == Fraction(1, 2)  # Half a cycle (2 beats / 4 beats per cycle)
assert time_to_ticks(t, ppq, cycle_beats) == ticks

# Test: 1-tick arc
arc = tick_arc(76, ppq, cycle_beats)
assert arc == (Fraction(76, 384), Fraction(77, 384))
```

---

### Step 3: Tokenizer

**Deliverables:**
- [x] `Token` namedtuple with `type`, `value`, `pos`
- [x] `tokenize(code: str) -> Iterator[Token]`
- [x] Token types: `NUMBER`, `LBRACK`, `RBRACK`, `LANGLE`, `RANGLE`, `STAR`, `SLASH`, `REST`, `WS`
- [x] Lookahead for `-`: `-\d` → NUMBER (negative), `-` alone → REST

**Tokenizer regex (order matters):**
```python
TOKEN_SPEC = [
    ('NUMBER',  r'-?\d+(\.\d+)?'),  # Negative or positive, optional decimal
    ('REST',    r'[~\-]'),          # ~ or standalone - (only matches if NUMBER didn't)
    ('LBRACK',  r'\['),
    ('RBRACK',  r'\]'),
    ('LANGLE',  r'<'),
    ('RANGLE',  r'>'),
    ('STAR',    r'\*'),
    ('SLASH',   r'/'),
    ('WS',      r'\s+'),
]
```

**Note:** NUMBER is checked first, so `-3` matches as NUMBER. A standalone `-` (not followed by digit) falls through to REST.

**Test:** Tokenize sample patterns and verify token streams.

```python
# Test: tokenize basic pattern
tokens = list(tokenize("60 [61 62] ~ *2"))
assert [t.type for t in tokens] == ['NUMBER', 'LBRACK', 'NUMBER', 'NUMBER', 'RBRACK', 'REST', 'STAR', 'NUMBER']

# Test: negative numbers
tokens = list(tokenize("-3 -12 0"))
assert [t.type for t in tokens] == ['NUMBER', 'NUMBER', 'NUMBER']
assert [t.value for t in tokens] == ['-3', '-12', '0']

# Test: standalone dash as rest
tokens = list(tokenize("60 - 62"))
assert [t.type for t in tokens] == ['NUMBER', 'REST', 'NUMBER']
```

---

### Step 4: Parser — Atoms Only

**Deliverables:**
- [x] `MiniParser` class with `tokens`, `pos`, `peek()`, `consume()`
- [x] `parse_atom()` — handles:
  - Numbers → `Pattern.pure(int(value))`
  - `~` → `Pattern.pure(None)` (rest)
- [x] `parse_layer()` — sequence of atoms, subdivided evenly

**Test:** Parse simple sequences without brackets/modifiers.

```python
# Test: parse "60 61 62"
p = parse("60 61 62")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 3
assert [e.value for e in events] == [60, 61, 62]
# Each note spans 1/3 of the cycle
```

---

### Step 5: Parser — Subdivision `[a b c]`

**Deliverables:**
- [x] `parse_atom()` handles `[` → recursive `parse()` → `]`
- [x] `sequence(*patterns)` / `fastcat(*patterns)` function — squeezes children evenly into one cycle

**How Subdivision Works:**

When you write `"a b c"` or `"[a b c]"`, each element gets an equal fraction of the parent's time. This is Strudel's `fastcat`/`sequence` operation.

**Implementation:**

```python
def sequence(*patterns):
    """Concatenate patterns, each taking equal time within one cycle.
    
    This is the core subdivision operation. "a b c" means:
    - a occupies 0 - 1/3
    - b occupies 1/3 - 2/3  
    - c occupies 2/3 - 1
    """
    n = len(patterns)
    if n == 0:
        return Pattern(lambda arc: [])
    if n == 1:
        return patterns[0]
    
    def query(arc):
        results = []
        for i, pat in enumerate(patterns):
            # This child occupies [i/n, (i+1)/n] of each cycle
            child_start = Fraction(i, n)
            child_end = Fraction(i + 1, n)
            
            # For each cycle the arc touches, check if it overlaps this child's slot
            cycle_start = int(arc[0])
            cycle_end = int(arc[1]) if arc[1] == int(arc[1]) else int(arc[1]) + 1
            
            for c in range(cycle_start, cycle_end):
                # This child's absolute time slot in cycle c
                slot_start = Fraction(c) + child_start
                slot_end = Fraction(c) + child_end
                
                # Intersect with query arc
                query_start = max(arc[0], slot_start)
                query_end = min(arc[1], slot_end)
                
                if query_start < query_end:
                    # Transform query to child's local time (0-1 within its slot)
                    # slot_start..slot_end maps to 0..1
                    local_start = (query_start - slot_start) * n + Fraction(c)
                    local_end = (query_end - slot_start) * n + Fraction(c)
                    
                    # Query child pattern
                    child_events = pat.query((local_start, local_end))
                    
                    # Transform results back to parent time
                    for e in child_events:
                        new_whole = None
                        if e.whole:
                            w_start = slot_start + (e.whole[0] - Fraction(c)) / n
                            w_end = slot_start + (e.whole[1] - Fraction(c)) / n
                            new_whole = (w_start, w_end)
                        p_start = slot_start + (e.part[0] - Fraction(c)) / n
                        p_end = slot_start + (e.part[1] - Fraction(c)) / n
                        new_part = (p_start, p_end)
                        results.append(Event(e.value, new_whole, new_part))
        
        return results
    
    return Pattern(query)

# Aliases
fastcat = sequence
```

**Note:** This is more complex than `fast()` because each child occupies a *different* time slot, not just a compressed version of the same pattern. The time transformation is per-child.

**Test:** Parse nested subdivisions.

```python
# Test: "60 [61 62] 63" — 3 top-level elements, middle one subdivided
p = parse("60 [61 62] 63")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 4
# 60: whole=(0, 1/3), part=(0, 1/3)
# 61: whole=(1/3, 1/2), part=(1/3, 1/2) — first half of middle slot
# 62: whole=(1/2, 2/3), part=(1/2, 2/3) — second half of middle slot
# 63: whole=(2/3, 1), part=(2/3, 1)
assert events[0].whole == (Fraction(0), Fraction(1, 3))
assert events[1].whole == (Fraction(1, 3), Fraction(1, 2))
assert events[2].whole == (Fraction(1, 2), Fraction(2, 3))
assert events[3].whole == (Fraction(2, 3), Fraction(1))
```

---

### Step 6: Parser — Alternation `<a b c>`

**Deliverables:**
- [x] `parse_atom()` handles `<` → parse alternatives → `>`
- [x] Alternation selects one child per cycle based on `floor(arc.start) % n`

**Simplification (Option A):** Since VFX Script uses 1-tick query windows that never span cycle boundaries, we can use a simple implementation:

```python
def slowcat(*patterns):
    def query(arc):
        cycle_num = int(arc[0])  # floor of start time
        pat_index = cycle_num % len(patterns)
        return patterns[pat_index].query(arc)
    return Pattern(query)
```

**Future Extension:** If features like batch querying or visualization require arcs spanning multiple cycles, implement `spanCycles` splitting to handle cross-boundary queries. Not needed for Phase 1.

**Test:** Query across multiple cycles.

```python
# Test: "<60 61 62>" — different note each cycle
p = parse("<60 61 62>")
# Cycle 0
events = p.query((Fraction(0), Fraction(1)))
assert events[0].value == 60
# Cycle 1
events = p.query((Fraction(1), Fraction(2)))
assert events[0].value == 61
# Cycle 2
events = p.query((Fraction(2), Fraction(3)))
assert events[0].value == 62
# Cycle 3 (wraps)
events = p.query((Fraction(3), Fraction(4)))
assert events[0].value == 60
```

---

### Step 7: Parser — Modifiers `*n` and `/n`

**Deliverables:**
- [x] `parse_element()` — parses atom then consumes modifiers
- [x] `*n` → `pattern.fast(n)` — compress time by factor n
- [x] `/n` → `pattern.slow(n)` — expand time by factor n
- [x] `Pattern.fast(n)` and `Pattern.slow(n)` methods

**How `fast` and `slow` work:**

- `fast(n)` compresses time: the pattern repeats `n` times per cycle
- `slow(n)` expands time: the pattern spans `n` cycles
- Internally, `slow(n)` is just `fast(1/n)`

Both work by:
1. **Query transformation:** Multiply/divide the query arc times
2. **Result transformation:** Divide/multiply the returned event times (both `whole` AND `part`)

**Critical:** Both `whole` and `part` must be transformed, or `has_onset()` breaks.

**Implementation:**

```python
def fast(self, factor: Fraction) -> Pattern:
    """Speed up pattern by factor. Used by * in mini notation."""
    factor = Fraction(factor)
    if factor == 0:
        return Pattern(lambda arc: [])  # silence
    
    def query(arc):
        # Query inner pattern with compressed arc
        inner_arc = (arc[0] * factor, arc[1] * factor)
        events = self.query(inner_arc)
        
        # Transform both whole and part back to outer time
        result = []
        for e in events:
            new_whole = (e.whole[0] / factor, e.whole[1] / factor) if e.whole else None
            new_part = (e.part[0] / factor, e.part[1] / factor)
            result.append(Event(e.value, new_whole, new_part))
        return result
    
    return Pattern(query)

def slow(self, factor: Fraction) -> Pattern:
    """Slow down pattern by factor. Used by / in mini notation."""
    return self.fast(Fraction(1) / Fraction(factor))
```

**Example trace for `"60".fast(2)` queried at `(0, 1)`:**

1. Inner query: `(0*2, 1*2)` = `(0, 2)` — asks for 2 cycles
2. Inner pattern returns:
   - Event(60, whole=(0,1), part=(0,1)) from cycle 0
   - Event(60, whole=(1,2), part=(1,2)) from cycle 1
3. Transform results (divide by 2):
   - Event(60, whole=(0, 0.5), part=(0, 0.5)) — first half of outer cycle
   - Event(60, whole=(0.5, 1), part=(0.5, 1)) — second half of outer cycle
4. Both events have `has_onset() == True` (whole.begin == part.begin)

**Test:** Verify time scaling.

```python
# Test: "60*2" — note 60 repeats twice per cycle
p = parse("60*2")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 2
assert all(e.value == 60 for e in events)
# First instance: whole=(0, 1/2), second: whole=(1/2, 1)

# Test: "60/2" — note 60 spans 2 cycles
p = parse("60/2")

# Cycle 0: event present WITH onset
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 1
assert events[0].whole == (Fraction(0), Fraction(2))  # spans 2 cycles
assert events[0].part == (Fraction(0), Fraction(1))   # clipped to query
assert events[0].has_onset() == True  # whole.begin == part.begin

# Cycle 1: event present WITHOUT onset (already started)
events = p.query((Fraction(1), Fraction(2)))
assert len(events) == 1
assert events[0].whole == (Fraction(0), Fraction(2))  # same whole
assert events[0].part == (Fraction(1), Fraction(2))   # clipped to this query
assert events[0].has_onset() == False  # whole.begin (0) != part.begin (1)

# Only fires once because tick() filters by has_onset()
```

---

### Step 8: Pattern.tick() Integration

**Deliverables:**
- [x] `Pattern.tick(current_tick, ppq, cycle_beats)` method — queries 1-tick arc, returns onset events
- [x] `Pattern.start()`, `Pattern.stop()`, `Pattern.reset()` methods
- [x] `_running` and `_start_tick` state per pattern
- [x] Events with `value=None` (rests) are skipped, not triggered
- [x] Only events where `has_onset() == True` are returned (avoids duplicate triggers)
- [x] **Bonus:** Cycle-latched parameter updates for smooth dynamic `cycle_beats` changes

**Implementation:**

```python
def tick(self, current_tick: int, ppq: int, cycle_beats: int) -> list[Event]:
    """Query events that should fire on this tick."""
    if not self._running:
        return []
    
    # Relative tick since pattern started
    rel_tick = current_tick - self._startTick
    
    # Convert to 1-tick-wide arc in cycle time
    ticks_per_cycle = ppq * cycle_beats
    arc_start = Fraction(rel_tick, ticks_per_cycle)
    arc_end = Fraction(rel_tick + 1, ticks_per_cycle)
    
    events = self.query((arc_start, arc_end))
    
    # Only fire events where onset falls in this window, skip rests
    return [e for e in events if e.has_onset() and e.value is not None]
```

**Why `has_onset()` matters:**

When an event spans multiple ticks (or crosses query boundaries), `query()` returns it for each overlapping tick — but with different `part` values. Only one tick will have `part.begin == whole.begin` (the onset). We only trigger on that tick.

**Test:** Simulate tick loop and verify events fire at correct times.

```python
# Test: pattern fires events on correct ticks
pattern = parse("60 ~ 62 ~")  # Note, rest, note, rest
pattern.start()

# Simulate 4 beats (PPQ=96, cycle=4 beats)
fired = []
for tick in range(96 * 4):
    _tickCount = tick
    events = pattern.tick(tick, 96, 4)
    fired.extend(events)

assert len(fired) == 2  # Only 60 and 62, rests skipped

# Test: fractional boundaries (5 notes over 4 beats)
pattern = parse("60 61 62 63 64")
pattern.start()
fired = []
for tick in range(96 * 4):
    events = pattern.tick(tick, 96, 4)
    fired.extend(events)

assert len(fired) == 5  # All 5 notes fire exactly once
# Note 61 fires on tick 76 (not 77), because 76.8 falls in arc (76/384, 77/384)
```

---

### Step 9: tc.n() Entry Point

**Deliverables:**
- [x] `tc.note(pattern_str, c=4, root=60)` function
- [x] `tc.n` as alias for `tc.note`
- [x] `c` / `cycle` parameter for cycle duration in beats (supports dynamic UI wrappers)
- [x] `root` parameter for origin note (default 60 for standalone, supports dynamic UI wrappers)
- [x] Values in pattern are offsets from `root`

**Test:** Full integration test.

```python
# Test: tc.n() creates working pattern
pattern = tc.n("0 3 5 7", c=4)  # C major 7 arpeggio from C5
pattern.start()

def onTick():
    pattern.tick()
    tc.update()
```

---

### Step 10: midi.n() Method

**Deliverables:**
- [x] `MIDI.n(pattern_str, c=4)` method
- [x] Uses `self.note` as root (incoming MIDI note)
- [x] Pattern lifecycle tied to parent voice (via `tc.stop_patterns_for_voice()`)
- [x] `c` parameter supports dynamic UI wrappers for real-time control
- [x] First event fires immediately (pattern starts at current tick, processed same frame)

**Test:** Voice-bound pattern in `onTriggerVoice`.

```python
def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    midi.n("0 3 5 7", c=4)  # Arpeggio from incoming note
    midi.trigger()
    # First note fires immediately
    # Pattern stops when parent releases
```

---

## Testing Strategy

1. **Unit tests in scope.py** — Test each step in isolation before integration
2. **Manual FL Studio test** — Copy to VFX Script, play notes, verify timing
3. **Edge cases:**
   - Empty patterns
   - Single-note patterns
   - Deeply nested subdivisions `[0 [1 [2 3]]]`
   - Alternation with different lengths `<0 [1 2]>`
   - Fractional modifiers `*3` on 4-element subdivision

---

## Success Criteria

- [x] `tc.n("60 62 64 65", c=4)` plays 4 quarter notes over 1 bar
- [x] `tc.n("60 [61 62] 63")` correctly subdivides middle element
- [x] `tc.n("<60 62 64>")` alternates notes each cycle
- [x] `tc.n("60*4")` plays note 4 times per cycle
- [x] `tc.n("60/2")` stretches note across 2 cycles
- [x] `tc.n("60 ~ 62 ~")` plays notes 60 and 62, skips rests
- [x] `midi.n("0 3 5 7")` creates arpeggio from incoming note
- [x] Patterns work when FL transport is stopped (internal tick counter)
- [x] **Bonus:** Dynamic `c` parameter with cycle-latched updates for smooth risers

---

## Open Questions (Resolve During Implementation)

1. **Negative numbers and rest:** ✅ RESOLVED
   - `-` alone = rest (Strudel-compatible, same as `~`)
   - `-` followed by digit = negative number (e.g., `-3`)
   - Tokenizer uses lookahead: `-\d` → NUMBER token, `-` alone → REST token
   - Both `~` and `-` are valid rest syntax
   
2. **Decimal numbers:** Support `60.5` for microtonal? Or defer?
   - Proposal: Defer to later phase
   
3. **Whitespace handling:** Is `[60 61]` same as `[ 60 61 ]`?
   - Proposal: Yes, whitespace inside brackets is ignored

4. **String atoms (note names):** ✅ RESOLVED — Defer to later phase
   - Phase 1: Only numeric values (MIDI note numbers as integers)
   - Future: Support note names like `c4`, `eb5`, `c:minor` (Strudel-style)
   - Parser can be extended to accept string atoms that get looked up in a note/scale table

5. **Event duration / note length:** ✅ RESOLVED
   - **Phase 1 default:** Legato — `voice.length` = full event duration (`whole.end - whole.begin`)
   - Duration in ticks = `(whole.end - whole.begin) * ppq * cycle_beats`
   - Example: `"60 61 62 63"` over 4 beats → each note lasts 1 beat (96 ticks at PPQ=96)
   - **Phase 2+:** Override via object syntax `{l=0.5}` or chained methods `.l("0.5 0.25")`

---

## Estimated Complexity

| Step | Lines of Code | Difficulty |
|------|---------------|------------|
| 1. Data structures | ~30 | Easy |
| 2. Time conversion | ~20 | Easy |
| 3. Tokenizer | ~25 | Easy |
| 4. Parser (atoms) | ~40 | Medium |
| 5. Subdivision | ~20 | Medium |
| 6. Alternation | ~30 | Medium |
| 7. Modifiers | ~25 | Medium |
| 8. tick() integration | ~40 | Medium |
| 9. tc.n() entry | ~20 | Easy |
| 10. midi.n() method | ~30 | Medium |
| **Total** | **~280** | |

---

## Next Steps After Phase 1 Tier 1

1. Add object syntax `{v=100, p=0.5}` (Phase 2)
2. Add chained methods `.v()`, `.pan()` (Phase 3)
3. Add polyphony `,` operator (Phase 5)
