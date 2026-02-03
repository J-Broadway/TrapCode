# Phase 1.1: Tier 2 Operators

Implementation plan for additional mini-notation operators: `@` (weighting), `!` (replicate), `?` (degrade), and `,` (polyphony).

---

## Prerequisites

These operators build on Phase 1 Tier 1 (complete):
- Pattern engine with `query(arc)` 
- Tokenizer and parser
- `sequence()` / `fastcat()` for subdivision
- `slowcat()` for alternation
- `fast()` / `slow()` for time scaling

---

## Operator Specifications

### 1. `@n` — Weighting / Elongation

**Strudel Behavior:**
Within a subdivision, `@n` gives an element `n` times its normal share of time.

```
"a@2 b"     →  a gets 2/3, b gets 1/3
"a@2 b@1"   →  same (explicit weights)
"a b@3 c"   →  a=1/5, b=3/5, c=1/5
"a b c@0"   →  a=1/2, b=1/2, c=0 (effectively removes c)
```

**Key Insight:** `@` affects **subdivision weighting**, not speed. It's different from `*`:
- `a*2` = `a` plays twice (repeats)
- `a@2` = `a` takes 2x the time slot (stretches)

**Default Weight:** Elements without `@` have implicit weight of 1.

**Implementation Strategy:**

1. **Tokenizer:** Add `AT` token type (already in spec, needs implementation)
2. **Parser:** Track weight per element in `parse_element()`
3. **Weighted Sequence:** Modify `sequence()` to accept weights

**Data Flow:**
```python
# Parser returns (pattern, weight) tuples
elements = [(pat_a, 2), (pat_b, 1)]  # "a@2 b"

# Calculate proportional time slots
total_weight = sum(w for _, w in elements)  # 3
# a: 0 to 2/3
# b: 2/3 to 1
```

**Implementation:**

```python
def weighted_sequence(elements: List[Tuple[Pattern, int]]) -> Pattern:
    """
    Like sequence(), but with weighted time allocation.
    
    Args:
        elements: List of (pattern, weight) tuples
    """
    if not elements:
        return Pattern.silence()
    
    total_weight = sum(w for _, w in elements)
    if total_weight == 0:
        return Pattern.silence()
    
    # Pre-calculate cumulative positions
    positions = []
    cumulative = Fraction(0)
    for pat, weight in elements:
        start = cumulative
        end = cumulative + Fraction(weight, total_weight)
        positions.append((pat, start, end))
        cumulative = end
    
    def query(arc: Arc) -> List[Event]:
        results = []
        cycle_start = int(arc[0])
        cycle_end = int(arc[1]) if arc[1] == int(arc[1]) else int(arc[1]) + 1
        
        for pat, child_start, child_end in positions:
            child_duration = child_end - child_start
            if child_duration == 0:
                continue  # Skip zero-weight elements
            
            for c in range(cycle_start, cycle_end):
                slot_start = Fraction(c) + child_start
                slot_end = Fraction(c) + child_end
                
                query_start = max(arc[0], slot_start)
                query_end = min(arc[1], slot_end)
                
                if query_start < query_end:
                    # Transform to child's local time (0-1 within its slot)
                    # Inverse of the slot mapping
                    scale = Fraction(1) / child_duration
                    local_start = (query_start - slot_start) * scale + Fraction(c)
                    local_end = (query_end - slot_start) * scale + Fraction(c)
                    
                    child_events = pat.query((local_start, local_end))
                    
                    for e in child_events:
                        new_whole = None
                        if e.whole:
                            w_start = slot_start + (e.whole[0] - Fraction(c)) * child_duration
                            w_end = slot_start + (e.whole[1] - Fraction(c)) * child_duration
                            new_whole = (w_start, w_end)
                        p_start = slot_start + (e.part[0] - Fraction(c)) * child_duration
                        p_end = slot_start + (e.part[1] - Fraction(c)) * child_duration
                        new_part = (p_start, p_end)
                        results.append(Event(e.value, new_whole, new_part))
        
        return results
    
    return Pattern(query)
```

**Parser Changes:**

```python
def parse_element(self) -> Tuple[Pattern, int]:
    """Parse atom with modifiers, return (pattern, weight)."""
    pat = self.parse_atom()
    weight = 1  # Default weight
    
    while self.peek() and self.peek().type in ('STAR', 'SLASH', 'AT'):
        tok = self.consume()
        num_tok = self.consume('NUMBER')
        num = int(num_tok.value)
        
        if tok.type == 'STAR':
            pat = pat.fast(num)
        elif tok.type == 'SLASH':
            pat = pat.slow(num)
        elif tok.type == 'AT':
            weight = num
    
    return (pat, weight)

def parse_layer(self) -> Pattern:
    """Parse sequence of weighted elements."""
    elements = []
    while self.peek() and self.peek().type not in ('RBRACK', 'RANGLE', 'COMMA'):
        elements.append(self.parse_element())
    
    if not elements:
        return Pattern.silence()
    
    # Check if any element has non-default weight
    has_weights = any(w != 1 for _, w in elements)
    
    if has_weights:
        return weighted_sequence(elements)
    else:
        # Use original sequence for efficiency
        return _sequence(*[p for p, _ in elements])
```

**Test Cases:**

```python
# Test: "a@2 b" — a gets 2/3, b gets 1/3
p = parse("0@2 1")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 2
assert events[0].whole == (Fraction(0), Fraction(2, 3))
assert events[1].whole == (Fraction(2, 3), Fraction(1))

# Test: "a b@3 c" — 1:3:1 ratio
p = parse("0 1@3 2")
events = p.query((Fraction(0), Fraction(1)))
assert events[0].whole == (Fraction(0), Fraction(1, 5))      # 1/5
assert events[1].whole == (Fraction(1, 5), Fraction(4, 5))   # 3/5
assert events[2].whole == (Fraction(4, 5), Fraction(1))      # 1/5

# Test: "@0 removes element"
p = parse("0 1@0 2")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 2  # 1 is removed
assert [e.value for e in events] == [0, 2]
```

---

### 2. `!n` — Replicate

**Strudel Behavior:**
`!n` repeats the element `n` times, squeezed into its original time slot.

```
"a!3"       →  equivalent to "[a a a]"
"a!3 b"     →  3 a's in first half, 1 b in second half
"[a b]!2"   →  pattern [a b] plays twice
```

**Key Insight:** `!n` is syntactic sugar for `[element element ...]` (n times).

**Difference from `*n`:**
- `a*2` = time compression, pattern runs 2x faster
- `a!2` = duplication within slot, like `[a a]`

For simple atoms, `a!2` and `a*2` produce the same result. The difference matters for complex patterns:
- `[a b]*2` = `[a b a b]` (interleaved)
- `[a b]!2` = `[[a b] [a b]]` (nested subdivision)

**Implementation Strategy:**

Since `!n` is equivalent to `[element]*n` or `sequence(*[element]*n)`, we can implement it as:

```python
# In parse_element(), after consuming '!' and number:
elif tok.type == 'BANG':
    # Replicate: create sequence of n copies
    copies = [pat] * num
    pat = _sequence(*copies)
```

**Full Implementation:**

```python
def parse_element(self) -> Tuple[Pattern, int]:
    """Parse atom with modifiers, return (pattern, weight)."""
    pat = self.parse_atom()
    weight = 1
    
    while self.peek() and self.peek().type in ('STAR', 'SLASH', 'AT', 'BANG'):
        tok = self.consume()
        num_tok = self.consume('NUMBER')
        num = int(num_tok.value)
        
        if tok.type == 'STAR':
            pat = pat.fast(num)
        elif tok.type == 'SLASH':
            pat = pat.slow(num)
        elif tok.type == 'AT':
            weight = num
        elif tok.type == 'BANG':
            if num > 0:
                pat = _sequence(*[pat] * num)
            else:
                pat = Pattern.silence()
    
    return (pat, weight)
```

**Tokenizer:** Add `BANG` token (already in spec):

```python
('BANG', r'!'),
```

**Test Cases:**

```python
# Test: "a!3" — 3 copies squeezed into one slot
p = parse("0!3")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 3
assert all(e.value == 0 for e in events)
assert events[0].whole == (Fraction(0), Fraction(1, 3))
assert events[1].whole == (Fraction(1, 3), Fraction(2, 3))
assert events[2].whole == (Fraction(2, 3), Fraction(1))

# Test: "a!3 b" — 3 a's then 1 b
p = parse("0!3 1")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 4
# a's occupy 0-0.5 (subdivided into 3)
# b occupies 0.5-1

# Test: "[a b]!2" — pattern repeated twice
p = parse("[0 1]!2")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 4
assert [e.value for e in events] == [0, 1, 0, 1]
```

---

### 3. `?` / `?p` — Degrade (Probability)

**Strudel Behavior:**
`?` randomly drops the element with probability 0.5. `?p` drops with probability `1-p`.

```
"a?"        →  a plays 50% of the time
"a?0.75"    →  a plays 75% of the time
"a?0"       →  a never plays
"a?1"       →  a always plays
```

**Determinism Requirement:**
For timeline scrubbing and reproducibility, randomness must be **seeded by cycle number**. The same pattern at the same cycle should always produce the same result.

**Implementation Strategy:**

```python
def Pattern.degrade(self, probability: float = 0.5) -> Pattern:
    """
    Randomly drop events with given probability of keeping them.
    
    Args:
        probability: Chance of keeping the event (0.0 to 1.0)
    """
    def query(arc: Arc) -> List[Event]:
        events = self.query(arc)
        result = []
        for e in events:
            # Seed based on event's whole start time for determinism
            if e.whole:
                seed = hash((float(e.whole[0]), e.value))
            else:
                seed = hash((float(e.part[0]), e.value))
            
            # Deterministic random check
            rand_val = ((seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff
            if rand_val < probability:
                result.append(e)
        return result
    
    return Pattern(query)
```

**Parser Changes:**

```python
# Tokenizer
('QUESTION', r'\?'),

# In parse_element():
elif tok.type == 'QUESTION':
    # Check if followed by a number
    if self.peek() and self.peek().type == 'NUMBER':
        prob_tok = self.consume('NUMBER')
        prob = float(prob_tok.value)
    else:
        prob = 0.5  # Default probability
    pat = pat.degrade(prob)
```

**Test Cases:**

```python
# Test: determinism — same query gives same result
p = parse("0?")
events1 = p.query((Fraction(0), Fraction(1)))
events2 = p.query((Fraction(0), Fraction(1)))
assert events1 == events2  # Deterministic

# Test: different cycles may differ
p = parse("0?")
events_c0 = p.query((Fraction(0), Fraction(1)))
events_c1 = p.query((Fraction(1), Fraction(2)))
# May or may not be equal, but each is deterministic

# Test: "?0" never plays
p = parse("0?0")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 0

# Test: "?1" always plays
p = parse("0?1")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 1
```

---

### 4. `,` — Polyphony / Stack

**Strudel Behavior:**
`,` layers patterns to play simultaneously (polyphony).

```
"a, b"          →  a and b play at the same time
"0 1, 2 3"      →  [0 1] and [2 3] play together
"[0 1], [2 3]"  →  explicit grouping, same result
"a, b, c"       →  three-voice polyphony
```

**Key Insight:** Each comma-separated layer is queried with the **same arc**, and results are concatenated.

**Implementation Strategy:**

```python
def stack(*patterns) -> Pattern:
    """
    Layer patterns for simultaneous playback (polyphony).
    
    All patterns are queried with the same arc, results merged.
    """
    if not patterns:
        return Pattern.silence()
    if len(patterns) == 1:
        return patterns[0]
    
    def query(arc: Arc) -> List[Event]:
        results = []
        for pat in patterns:
            results.extend(pat.query(arc))
        return results
    
    return Pattern(query)
```

**Parser Changes:**

The parser already handles `,` at the top level in `parse()`. We need to ensure it's properly tokenized and handled:

```python
# Tokenizer
('COMMA', r','),

# In parse():
def parse(self) -> Pattern:
    """pattern ::= layer (',' layer)*"""
    layers = [self.parse_layer()]
    
    while self.peek() and self.peek().type == 'COMMA':
        self.consume('COMMA')
        layers.append(self.parse_layer())
    
    if len(layers) == 1:
        return layers[0]
    
    return stack(*layers)
```

**Test Cases:**

```python
# Test: "0, 1" — both notes at same time
p = parse("0, 1")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 2
assert set(e.value for e in events) == {0, 1}
assert events[0].whole == events[1].whole  # Same timing

# Test: "0 1, 2 3" — two sequences in parallel
p = parse("0 1, 2 3")
events = p.query((Fraction(0), Fraction(1)))
assert len(events) == 4
# First half: 0 and 2 together
# Second half: 1 and 3 together

# Test: nested with brackets
p = parse("[0 1]*2, 2")
events = p.query((Fraction(0), Fraction(1)))
# [0 1]*2 gives 4 events (0,1,0,1)
# 2 gives 1 event
assert len(events) == 5
```

---

## Implementation Order

Recommended order based on dependencies and complexity:

### Step 1: Tokenizer Updates
Add all new token types:

```python
_TOKEN_SPEC = [
    ('NUMBER',  r'-?\d+(\.\d+)?'),
    ('REST',    r'[~\-]'),
    ('LBRACK',  r'\['),
    ('RBRACK',  r'\]'),
    ('LANGLE',  r'<'),
    ('RANGLE',  r'>'),
    ('STAR',    r'\*'),
    ('SLASH',   r'/'),
    ('AT',      r'@'),      # NEW
    ('BANG',    r'!'),      # NEW
    ('QUESTION', r'\?'),    # NEW
    ('COMMA',   r','),      # NEW
    ('WS',      r'\s+'),
]
```

### Step 2: Polyphony `,` (Simplest)
- Add `stack()` combinator
- Update `parse()` to handle comma-separated layers
- Test with simple patterns

### Step 3: Replicate `!n` (Simple)
- Modify `parse_element()` to handle `!n`
- Reuses existing `_sequence()` function
- Test with atoms and grouped patterns

### Step 4: Degrade `?` (Medium)
- Add `Pattern.degrade()` method
- Update parser for optional probability argument
- Test determinism

### Step 5: Weighting `@n` (Complex)
- Add `weighted_sequence()` combinator
- Modify `parse_element()` to return (pattern, weight)
- Update `parse_layer()` to handle weighted elements
- Test various weight combinations

---

## Success Criteria

- [ ] `"0@2 1"` gives 0 twice the duration of 1
- [ ] `"0!3"` plays note 0 three times in one cycle
- [ ] `"0?"` plays note 0 approximately 50% of the time (deterministically)
- [ ] `"0, 1"` plays both notes simultaneously
- [ ] `"[0 1]!2, 2@2 3"` combines all operators correctly
- [ ] All operators work with `midi.n()` voice-bound patterns
- [ ] Dynamic `c` parameter still works with new operators

---

## Edge Cases to Handle

1. **`@0` removes element** — zero-weight elements should be skipped
2. **`!0` silences element** — replicate zero times = silence
3. **`?0` never plays** — 0% probability = always filtered
4. **`?1` always plays** — 100% probability = no filtering
5. **Nested operators** — `[0@2 1]!3` should work correctly
6. **Empty layers** — `0, , 1` should handle gracefully
7. **Whitespace** — `0 , 1` vs `0,1` should be equivalent

---

## Code Size Estimate

| Component | Lines |
|-----------|-------|
| Tokenizer updates | ~5 |
| `stack()` combinator | ~15 |
| Replicate in parser | ~10 |
| `Pattern.degrade()` | ~20 |
| `weighted_sequence()` | ~50 |
| Parser weight handling | ~30 |
| **Total** | **~130** |

---

## Next Steps After Phase 1.1

1. Object syntax `{v=100, p=0.5}` — per-note property overrides
2. Chained methods `.v()`, `.pan()` — polyrhythmic modulation
3. Euclidean rhythms `(k,n)`
4. Random choice `a|b`
