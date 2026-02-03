# Phase 1.2: Note Representations

Implementation plan for note name parsing and chord/polyphony notation in TrapCode's mini-notation system.

---

## Goal

Enable patterns like:

```python
# Chord progression with note names
tc.note("<[g3,b3,e4] [a3,c3,e4] [b3,d3,f#4] [b3,e4,g4]>")

# Simple note names
tc.n("c4 d4 e4 f4")

# Mixed with offsets
midi.n("c4 eb4 g4")  # Absolute notes
midi.n("0 3 7")       # Relative offsets (existing)
```

---

## Prerequisites

This phase builds on Phase 1.1 (Tier 2 Operators), which added:
- `,` polyphony/stack operator (patterns can return multiple simultaneous events)
- `@` weighting
- `!` replicate  
- `?` degrade

---

## Key Concepts from Strudel

### Note Name Format

Strudel follows standard music notation:

| Component | Description | Examples |
|-----------|-------------|----------|
| Letter | Note letter (case-insensitive) | `c`, `C`, `d`, `D` |
| Accidentals | `#` = sharp, `b` = flat (can stack) | `c#`, `eb`, `f##`, `ebb` |
| Octave | Optional, defaults to 3 | `c4`, `eb5`, `c` (= c3) |

**Examples:**
- `c4` = MIDI 60 (middle C)
- `c#4` = MIDI 61
- `db4` = MIDI 61 (enharmonic)
- `c5` = MIDI 72
- `c` = MIDI 48 (octave 3 default)

### Note to MIDI Conversion

From Strudel's `util.mjs`:

```javascript
const chromas = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 };
const accs = { '#': 1, b: -1, s: 1, f: -1 };  // s = sharp, f = flat (alt syntax)

function noteToMidi(note, defaultOctave = 3) {
  const [pc, acc, oct = defaultOctave] = tokenizeNote(note);
  const chroma = chromas[pc.toLowerCase()];
  const offset = accidentals.split('').reduce((o, char) => o + accs[char], 0);
  return (Number(oct) + 1) * 12 + chroma + offset;
}
```

**Key formula:** `midi = (octave + 1) * 12 + chroma + accidental_offset`

### Polyphony with `,`

In Strudel (from `krill.pegjs`):
- `,` creates a **stack** — all patterns play simultaneously
- `[a, b]` = both `a` and `b` at the same time
- `[a b, c d]` = sequence `[a b]` stacked with sequence `[c d]`

This is already implemented in Phase 1.1 via `_stack(*patterns)`.

---

## Implementation Plan

### Step 1: Note Name Tokenizer

**Deliverables:**
- [ ] Add `NOTE` token type to `_TOKEN_SPEC`
- [ ] Note regex: letter + optional accidentals + optional octave
- [ ] Must not conflict with existing NUMBER token

**Token Spec Update:**

```python
_TOKEN_SPEC = [
    ('NUMBER',  r'-?\d+(\.\d+)?'),  # Negative or positive, optional decimal
    ('NOTE',    r'[a-gA-G][#bsf]*-?\d*'),  # Note name: c, c#, eb4, f##5
    ('REST',    r'[~\-]'),          # ~ or standalone - 
    # ... rest unchanged
]
```

**Regex breakdown:**
- `[a-gA-G]` — note letter (case-insensitive)
- `[#bsf]*` — zero or more accidentals (`#`=sharp, `b`=flat, `s`=sharp alt, `f`=flat alt)
- `-?\d*` — optional octave (can be negative for very low notes, e.g., `c-1`)

**Order matters:** NUMBER must come before NOTE to ensure `-3` matches as NUMBER, not as an incomplete note.

**Test cases:**

```python
# Basic notes
list(_tokenize("c4 d4 e4"))
# [Token('NOTE', 'c4', 0), Token('NOTE', 'd4', 3), Token('NOTE', 'e4', 6)]

# Accidentals
list(_tokenize("c# eb f## gbb"))
# All as NOTE tokens

# Octaves
list(_tokenize("c c3 c4 c-1"))
# All as NOTE tokens

# Mixed with numbers
list(_tokenize("c4 3 eb5 -2"))
# [NOTE 'c4', NUMBER '3', NOTE 'eb5', NUMBER '-2']
```

---

### Step 2: Note Parsing Helper

**Deliverables:**
- [ ] `_tokenize_note(note_str)` — extract (letter, accidentals, octave) from note string
- [ ] `_note_to_midi(note_str, default_octave=3)` — convert note name to MIDI number
- [ ] Handle edge cases: missing octave, stacked accidentals

**Implementation:**

```python
# Chroma values for each note letter (C = 0)
_CHROMAS = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}

# Accidental semitone offsets
_ACCIDENTALS = {'#': 1, 'b': -1, 's': 1, 'f': -1}


def _tokenize_note(note: str) -> tuple:
    """
    Parse note string into (letter, accidentals, octave).
    
    Returns:
        (letter: str, accidentals: str, octave: int or None)
    
    Examples:
        'c4' -> ('c', '', 4)
        'eb5' -> ('e', 'b', 5)
        'f##3' -> ('f', '##', 3)
        'c' -> ('c', '', None)
    """
    if not note or not isinstance(note, str):
        return (None, '', None)
    
    # Match: letter + accidentals + optional octave
    match = re.match(r'^([a-gA-G])([#bsf]*)(-?\d*)$', note)
    if not match:
        return (None, '', None)
    
    letter = match.group(1).lower()
    accidentals = match.group(2)
    octave_str = match.group(3)
    octave = int(octave_str) if octave_str else None
    
    return (letter, accidentals, octave)


def _get_accidental_offset(accidentals: str) -> int:
    """Sum of semitone offsets for accidentals string."""
    return sum(_ACCIDENTALS.get(c, 0) for c in accidentals)


def _note_to_midi(note: str, default_octave: int = 3) -> int:
    """
    Convert note name to MIDI number.
    
    Args:
        note: Note string like 'c4', 'eb5', 'f##'
        default_octave: Octave to use if not specified (default 3)
    
    Returns:
        MIDI note number (0-127)
    
    Examples:
        'c4' -> 60
        'c#4' -> 61
        'db4' -> 61
        'c5' -> 72
        'c' -> 48 (octave 3 default)
    
    Raises:
        ValueError if note format is invalid
    """
    letter, accidentals, octave = _tokenize_note(note)
    
    if letter is None:
        raise ValueError(f"Invalid note format: '{note}'")
    
    if octave is None:
        octave = default_octave
    
    chroma = _CHROMAS[letter]
    offset = _get_accidental_offset(accidentals)
    
    return (octave + 1) * 12 + chroma + offset


def _is_note(value: str) -> bool:
    """Check if string is a valid note name."""
    if not isinstance(value, str):
        return False
    letter, _, _ = _tokenize_note(value)
    return letter is not None
```

**Test cases:**

```python
# Basic conversions
assert _note_to_midi('c4') == 60
assert _note_to_midi('c#4') == 61
assert _note_to_midi('db4') == 61
assert _note_to_midi('c5') == 72
assert _note_to_midi('c3') == 48

# Default octave
assert _note_to_midi('c') == 48  # Octave 3 default
assert _note_to_midi('c', default_octave=4) == 60

# Stacked accidentals
assert _note_to_midi('c##4') == 62  # C double-sharp = D
assert _note_to_midi('dbb4') == 60  # D double-flat = C

# Edge cases
assert _note_to_midi('c-1') == 0   # Lowest MIDI note
assert _note_to_midi('g9') == 127  # Near highest MIDI note

# Validation
assert _is_note('c4') == True
assert _is_note('eb5') == True
assert _is_note('123') == False
assert _is_note('~') == False
```

---

### Step 3: Parser Updates for NOTE Token

**Deliverables:**
- [ ] Update `parse_atom()` to handle NOTE tokens
- [ ] Convert note name to MIDI value when creating Pattern.pure()

**Implementation:**

```python
def parse_atom(self) -> Pattern:
    """
    Parse a primitive value or grouped pattern.
    atom ::= NUMBER | NOTE | REST | '[' pattern ']' | '<' pattern+ '>'
    """
    tok = self.peek()
    if tok is None:
        return Pattern.silence()
    
    if tok.type == 'NUMBER':
        self.consume()
        if '.' in tok.value:
            return Pattern.pure(float(tok.value))
        else:
            return Pattern.pure(int(tok.value))
    
    elif tok.type == 'NOTE':
        self.consume()
        # Convert note name to MIDI number
        midi = _note_to_midi(tok.value)
        return Pattern.pure(midi)
    
    elif tok.type == 'REST':
        self.consume()
        return Pattern.pure(None)
    
    # ... rest unchanged (LBRACK, LANGLE cases)
```

**Note on representation:**

The parser converts note names to MIDI numbers at parse time. This keeps the pattern engine simple (everything is numeric) while allowing note name syntax in the input.

**Future consideration:** If we want to preserve note names for transposition-aware operations (e.g., transpose C to D maintains major/minor quality), we would store a `NoteValue` object instead of raw int. Defer to a future phase.

---

### Step 4: Polyphony Syntax Verification

The `,` polyphony operator was added in Phase 1.1. Verify it works correctly with note names:

```python
# Chord: three notes stacked
tc.n("[c4, e4, g4]")  # C major chord

# Chord progression with alternation
tc.n("<[g3,b3,e4] [a3,c3,e4] [b3,d3,f#4] [b3,e4,g4]>")
```

**How it parses:**

1. `<...>` = alternation (slowcat) — cycles through alternatives
2. `[g3,b3,e4]` = subdivision with polyphony
   - `g3` is first element
   - `,` switches to stack mode
   - Result: all three notes stacked (play simultaneously)

**Existing implementation should handle this** via:
- `parse_layer()` calls `parse()` which handles commas via `_stack()`
- Each comma-separated layer is stacked

**Test cases:**

```python
# Single chord
p = _parse_mini("[c4, e4, g4]")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 3  # Three simultaneous notes
assert set(e.value for e in events) == {60, 64, 67}  # C, E, G

# Chord with sequence
p = _parse_mini("[c4 d4, e4 f4]")
events = p.query((Fraction(0), Fraction(1)))
# First half: c4 and e4 together
# Second half: d4 and f4 together
assert len(events) == 4

# Alternating chords
p = _parse_mini("<[c4,e4,g4] [d4,f4,a4]>")
# Cycle 0: C major chord
events = p.query((Fraction(0), Fraction(1)))
assert set(e.value for e in events) == {60, 64, 67}
# Cycle 1: D minor chord
events = p.query((Fraction(1), Fraction(2)))
assert set(e.value for e in events) == {62, 65, 69}
```

---

### Step 5: Integration with midi.n() and tc.n()

**Behavior clarification:**

| API | Input `"c4 e4 g4"` | Input `"0 4 7"` |
|-----|-------------------|-----------------|
| `tc.n()` | Notes as-is (MIDI 60, 64, 67) | Offsets from root=60 (MIDI 60, 64, 67) |
| `midi.n()` | Notes as-is (ignores root) | Offsets from incoming note |

**Decision:** Note names are **absolute** — they represent specific MIDI pitches, not offsets. Numbers remain relative to root.

**Implementation update in tc.n():**

```python
def note(pattern_str: str, c=4, root=60) -> Pattern:
    """
    Create a pattern from mini-notation string.
    
    Values in pattern:
    - Numbers: offsets from root (e.g., '0 4 7' with root=60 -> 60, 64, 67)
    - Note names: absolute MIDI values (e.g., 'c4 e4 g4' -> 60, 64, 67)
    - Rests: ~ or -
    
    Args:
        pattern_str: Mini-notation pattern
        c: Cycle duration in beats (default 4)
        root: Root note for numeric offsets (default 60 = C4)
    """
    pattern = _parse_mini(pattern_str)
    # ... existing registration code
```

The root offset is applied at trigger time:

```python
def _update_patterns():
    # ... for each pattern event ...
    if e.value is not None:
        # Check if value is already absolute (from note name) or relative (number)
        # Since parser converted notes to MIDI, we need to mark them somehow
        # OR: always treat as absolute in the pattern, apply root offset at pattern creation
```

**Simplification:** At parse time, if the original token was a NOTE, store the absolute MIDI value. If it was a NUMBER, store it as-is. At trigger time:
- If value >= some threshold (e.g., 12) or was marked as absolute → use as-is
- Otherwise → add root offset

**Better approach:** Use a wrapper to distinguish:

```python
@dataclass
class AbsoluteNote:
    """Marker for absolute MIDI values (from note names)."""
    midi: int

# In parse_atom():
elif tok.type == 'NOTE':
    self.consume()
    midi = _note_to_midi(tok.value)
    return Pattern.pure(AbsoluteNote(midi))

# In _update_patterns(), when triggering:
if isinstance(e.value, AbsoluteNote):
    midi = e.value.midi
elif isinstance(e.value, (int, float)):
    midi = int(root + e.value)  # Relative offset
```

---

### Step 6: Comprehensive Testing

**Test file additions:**

```python
# === Note Name Parsing ===

def test_basic_note_names():
    """Basic note name to MIDI conversion."""
    p = _parse_mini("c4 d4 e4 f4 g4 a4 b4")
    events = p.query((Fraction(0), Fraction(1)))
    assert [e.value for e in events] == [60, 62, 64, 65, 67, 69, 71]

def test_accidentals():
    """Sharp and flat handling."""
    p = _parse_mini("c4 c#4 db4 d4")
    events = p.query((Fraction(0), Fraction(1)))
    values = [e.value.midi if hasattr(e.value, 'midi') else e.value for e in events]
    assert values == [60, 61, 61, 62]

def test_octaves():
    """Different octaves."""
    p = _parse_mini("c3 c4 c5 c6")
    events = p.query((Fraction(0), Fraction(1)))
    assert [e.value for e in events] == [48, 60, 72, 84]

def test_default_octave():
    """Notes without octave default to 3."""
    p = _parse_mini("c d e")
    events = p.query((Fraction(0), Fraction(1)))
    assert [e.value for e in events] == [48, 50, 52]


# === Chord/Polyphony ===

def test_simple_chord():
    """Three-note chord."""
    p = _parse_mini("[c4, e4, g4]")
    events = p.query((Fraction(0), Fraction(1)))
    assert len(events) == 3
    values = sorted([e.value for e in events])
    assert values == [60, 64, 67]

def test_chord_progression():
    """Alternating chord progression."""
    p = _parse_mini("<[g3,b3,e4] [a3,c4,e4] [b3,d4,f#4] [b3,e4,g4]>")
    
    # Cycle 0: Em (G3, B3, E4)
    events = p.query((Fraction(0), Fraction(1)))
    assert sorted([e.value for e in events]) == [55, 59, 64]
    
    # Cycle 1: Am (A3, C4, E4)
    events = p.query((Fraction(1), Fraction(2)))
    assert sorted([e.value for e in events]) == [57, 60, 64]
    
    # Cycle 2: Bm (B3, D4, F#4)
    events = p.query((Fraction(2), Fraction(3)))
    assert sorted([e.value for e in events]) == [59, 62, 66]
    
    # Cycle 3: Em/G (B3, E4, G4)
    events = p.query((Fraction(3), Fraction(4)))
    assert sorted([e.value for e in events]) == [59, 64, 67]

def test_mixed_numbers_and_notes():
    """Mixing numeric offsets with note names."""
    p = _parse_mini("c4 0 e4 4")  # c4, root+0, e4, root+4
    events = p.query((Fraction(0), Fraction(1)))
    # Values should preserve type info for offset application
    # c4 -> 60 (absolute)
    # 0 -> 0 (relative)
    # e4 -> 64 (absolute)
    # 4 -> 4 (relative)


# === FL Studio Integration ===

def test_chord_triggering():
    """Chords trigger multiple voices."""
    # In FL Studio, each note in a chord should trigger a separate voice
    pattern = tc.n("[c4, e4, g4]", c=4)
    pattern.start()
    
    # Simulate tick — should fire 3 notes at tick 0
    ppq = 96
    events = pattern.tick(0, ppq, 4)
    assert len(events) == 3
```

---

## Implementation Order

1. **Tokenizer** — Add NOTE token type
2. **Note helpers** — `_tokenize_note()`, `_note_to_midi()`, `_is_note()`
3. **Parser** — Update `parse_atom()` for NOTE tokens
4. **AbsoluteNote wrapper** — Distinguish absolute vs relative values
5. **Integration** — Update `_update_patterns()` to handle AbsoluteNote
6. **Testing** — Comprehensive test suite

---

## Success Criteria

- [ ] `tc.n("c4 d4 e4 f4")` plays C major scale starting at C4
- [ ] `tc.n("c#4 eb4 f##4")` handles all accidental types
- [ ] `tc.n("[c4, e4, g4]")` plays C major chord (3 simultaneous notes)
- [ ] `tc.n("<[g3,b3,e4] [a3,c3,e4]>")` alternates between Em and Am chords
- [ ] `tc.n("c4 0 2 4")` mixes absolute notes with relative offsets
- [ ] `midi.n("c4 e4 g4")` plays absolute notes regardless of incoming pitch
- [ ] Existing numeric patterns continue to work unchanged

---

## Edge Cases

1. **Case sensitivity** — `C4` and `c4` should be equivalent
2. **Alt accidental syntax** — `s` = sharp, `f` = flat (Strudel compatibility)
3. **Stacked accidentals** — `c##4` = D4, `dbb4` = C4
4. **Negative octaves** — `c-1` = MIDI 0 (lowest note)
5. **Out of range** — Clamp MIDI values to 0-127, warn on overflow
6. **Empty chord** — `[,]` should produce silence
7. **Single-note "chord"** — `[c4]` should work same as `c4`

---

## Code Size Estimate

| Component | Lines |
|-----------|-------|
| Tokenizer (NOTE pattern) | ~5 |
| `_tokenize_note()` | ~20 |
| `_note_to_midi()` | ~15 |
| `_is_note()` | ~5 |
| Parser updates | ~10 |
| AbsoluteNote class | ~5 |
| Integration updates | ~15 |
| **Total** | **~75** |

---

## Future Enhancements (Not in Phase 1.2)

1. **Scale-aware transposition** — Transpose while preserving scale degree
2. **Chord symbols** — `"Cmaj7 Dm7 G7 Cmaj7"` chord symbol notation
3. **Voicing algorithms** — Automatic voice leading for smooth chord transitions
4. **Note preservation** — Keep note names through pattern transformations
5. **Microtonal** — Support for quarter-tones, arbitrary pitch bends

---

## Strudel Reference

Key source files for reference:
- `packages/core/util.mjs` — `noteToMidi()`, `tokenizeNote()`, `isNote()`
- `packages/mini/krill.pegjs` — PEG grammar for mini-notation (`,` = stack)
- `packages/mini/mini.mjs` — Pattern construction from AST
- `packages/tonal/tonal.mjs` — Scale and transposition operations
- `packages/tonal/tonleiter.mjs` — Chord parsing and voicing

---

## Next Steps After Phase 1.2

1. Implement strudles chord system
