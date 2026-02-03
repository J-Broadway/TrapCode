# Phase 1.3: Chord Symbols & Voicings

Design document for implementing Strudel-style chord symbols and voicing functions in TrapCode.

---

## Goal

Enable chord-based patterns with automatic voicing selection:

```python
tc.midi.chord("<Am C D F Am E Am E>").voicing()
```

---

## Background: How Strudel's Voicing System Works

### Two-Stage Process

1. **`chord("Am7")`** — Parses the chord symbol, stores it as a control value (doesn't produce notes yet)

2. **`.voicing()`** — Takes that chord symbol and:
   - Looks up the chord type (e.g., `m7`) in a **voicing dictionary**
   - Each dictionary has multiple voicing options per chord (different inversions/arrangements)
   - Picks the voicing whose target note is closest to the **anchor**
   - Returns the actual MIDI notes as a polyphonic pattern

### Voicing Parameters

| Param | Default | Description |
|-------|---------|-------------|
| `dict` | `'default'` | Which voicing dictionary to use |
| `anchor` | `'c5'` (MIDI 72) | Reference note for positioning |
| `mode` | `'below'` | How voicing aligns to anchor |
| `offset` | `0` | Shift to next voicing in dictionary |
| `n` | - | Pick individual note from voicing (like a scale) |

### Alignment Modes

| Mode | Behavior |
|------|----------|
| `'below'` | Top note of voicing ≤ anchor (default) |
| `'above'` | Bottom note of voicing ≥ anchor |
| `'duck'` | Top note of voicing < anchor (excludes anchor note) |
| `'root'` | Bottom note is always the root, closest to anchor |

### How Voice Leading Works

The "automatic voice leading" happens because:
- The **same anchor** is used across a chord progression
- Each chord picks whichever voicing puts its target note closest to that anchor
- Result: minimal jumps between consecutive chords

Example with `anchor='c5'` and `mode='below'`:
- `Am7` picks a voicing where the top note is just below C5
- `C` picks a voicing where the top note is also just below C5
- Since both chords aim for similar top notes, transitions are smooth

---

## Chord Symbol Format

Chord symbols consist of: `[root][quality]`

- **Root**: Note name with optional accidental (`C`, `F#`, `Bb`, `A`)
- **Quality**: Chord type symbol (see dictionary below)

### Examples

| Symbol | Meaning |
|--------|---------|
| `C` | C major triad |
| `Am` | A minor triad |
| `G7` | G dominant 7th |
| `Dm7` | D minor 7th |
| `Bb^7` | Bb major 7th (^ = major) |
| `F#-7` | F# minor 7th (- = minor) |
| `Eo` | E diminished |
| `Caug` | C augmented |

### Symbol Synonyms

- `-` = `m` (minor): `C-7` = `Cm7`
- `^` = `M` (major): `C^7` = `CM7`
- `+` = `aug` (augmented)

---

## Voicing Dictionary

### Decision: Embed Full Dictionary

The complete Strudel-compatible dictionary will be embedded in `trapcode.py`. Performance impact is negligible (O(1) dict lookup), only adds ~200-300 lines of static data.

### Available Chord Symbols

```
2 5 6 7 9 11 13 69 add9
o h sus ^ - ^7 -7 7sus
h7 o7 ^9 ^13 ^7#11 ^9#11
^7#5 -6 -69 -^7 -^9 -9
-add9 -11 -7b5 h9 -b6 -#5
7b9 7#9 7#11 7b5 7#5 9#11
9b5 9#5 7b13 7#9#5 7#9b5
7#9#11 7b9#11 7b9b5 7b9#5
7b9#9 7b9b13 7alt 13#11
13b9 13#9 7b9sus 7susadd3
9sus 13sus 7b13sus
aug M m M7 m7 M9 M13
M7#11 M9#11 M7#5 m6 m69
m^7 -M7 m^9 -M9 m9 madd9
m11 m7b5 mb6 m#5 mM7 mM9
```

### Dictionary Structure

Each chord symbol maps to one or more voicings. Each voicing is a list of intervals (semitones from root):

```python
# Example structure (not final implementation)
VOICING_DICT = {
    '': [[0, 4, 7], [0, 4, 7, 12]],           # Major triad voicings
    'm': [[0, 3, 7], [0, 3, 7, 12]],          # Minor triad voicings
    '7': [[0, 4, 7, 10], [4, 7, 10, 12]],     # Dominant 7th voicings
    'm7': [[0, 3, 7, 10], [3, 7, 10, 12]],    # Minor 7th voicings
    # ... etc
}
```

Multiple voicings per chord type enables voice leading — the system picks the one closest to the anchor.

---

## Open Design Questions

### 1. Polyphony Integration

`.voicing()` needs to return multiple simultaneous notes (a chord). Two options:

**A) Implement polyphony (`,`) as part of Phase 1.3** 
- `.voicing()` returns a polyphonic pattern using the `,` stack operator
- More work but gives full Strudel-like experience
- Aligns with planned Phase 5 polyphony

**B) Defer full polyphony, use simpler mechanism**
- `.voicing()` triggers multiple `Single` notes simultaneously
- Quicker to implement but less elegant for pattern composition

**Status:** Pending decision

### 2. API Surface for Phase 1.3 vs 1.4

**Phase 1.3 (Core):**
- `tc.midi.chord()` — parse chord symbols in patterns
- `.voicing()` — basic voicing with embedded dictionary
- `anchor` parameter
- `mode` parameter

**Phase 1.4 (Extended):**
- `.dict()` — select alternative voicing dictionary
- `tc.addVoicings()` — register custom voicing dictionaries
- `offset` parameter
- `n` parameter (pick individual notes from chord)

**Status:** Pending confirmation

---

## Integration with Existing Pattern System

Chord patterns should work within the existing mini-notation:

```python
# Alternation works
tc.midi.chord("<Am C D F>").voicing()

# Subdivision works  
tc.midi.chord("[Am C] [D F]").voicing()

# Time modifiers work
tc.midi.chord("Am*2 C").voicing()
```

The `chord()` function produces a pattern of chord symbols, and `.voicing()` transforms those symbols into polyphonic note patterns.

---

## References

- [Strudel Voicings Documentation](https://strudel.cc/understand/voicings/)
- [Strudel Tonal Functions](https://strudel.cc/learn/tonal/#voicing)
- Strudel source: `packages/tonal/voicings.mjs`, `packages/tonal/tonleiter.mjs`

---

## Next Steps

1. Resolve polyphony integration question
2. Define exact API signatures
3. Extract/adapt voicing dictionary from Strudel source
4. Implement chord symbol parser (root + quality extraction)
5. Implement voicing selection algorithm (anchor distance calculation)
6. Integrate with pattern system
