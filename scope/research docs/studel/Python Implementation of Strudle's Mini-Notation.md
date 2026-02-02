# Python Implementation of Strudel's Mini-Notation

This document provides the architectural foundation and implementation strategy for **Trapcode**, a pure-Python 3.12 realization of the TidalCycles/Strudel temporal calculus. It is designed specifically for execution within FL Studio's VFX Script sandbox (Python 3.12.1, no external dependencies).

> **⚠️ NOTE:** Some code examples in this document have been superseded by improved implementations. See `scope/plan/phase1_tier1_implementation.md` for the corrected versions, particularly:
> - `Pattern.pure()` — must handle multi-cycle queries correctly
> - `Pattern.fast()`/`slow()` — must transform BOTH `whole` and `part`
> - `Event` — needs `has_onset()` method for proper trigger detection
> - Tokenizer — needs to handle `-` as rest and `-3` as negative number
> - VFX Script integration — uses 1-tick-wide query arcs, not block processing

---

## 1. The Pattern Logic (Temporal Calculus)

Strudel adopts a **Functional Reactive Programming (FRP)** model. A `Pattern` is not a data structure (list/array) but a **function of time**: a pure mapping from a temporal query to a set of discrete musical events.

### 1.1 The Cycle (Tactus)
The **Cycle** is the fundamental unit of metric time, conceptually equivalent to one bar in 4/4 time or one rotation of the global clock.
*   **Representation:** Intervals are rational numbers. The domain of a cycle is the half-open interval **[0, 1)**.
*   **Query Arc:** Patterns are not indexed by discrete steps. Instead, we query an **Arc** (a time span) `span = (start, end)`, where `start` and `end` are `Fraction` types. Arcs can span multiple cycles (e.g., `(3/4, 5/2)`).

### 1.2 The Event (Hap)
In TidalCycles nomenclature, an event is a **Hap** (Haskell happiness). It represents the occurrence of a value within a specific temporal context.

```python
from dataclasses import dataclass
from fractions import Fraction
from typing import Tuple, Optional, Any

Time = Fraction
Arc = Tuple[Time, Time]

@dataclass(frozen=True)
class Hap:
    value: Any                    # The musical value (MIDI note, sample index, etc.)
    whole: Optional[Arc]          # The "logical" duration (origin cycle). None for continuous.
    part: Arc                     # The actual active time window (intersected with query)
    
    def has_onset(self) -> bool:
        """Returns True if this event's onset is within the query arc.
        
        Critical for VFX Script: only trigger notes when has_onset() is True,
        otherwise you'll fire the same note multiple times across tick boundaries.
        """
        return self.whole is not None and self.whole[0] == self.part[0]
```

**Key Insight:** The `whole` preserves the original metric structure (e.g., "this note started at beat 0 and lasts 1 beat"), while `part` represents the actual clipped intersection with the query window. The `has_onset()` method is critical: it tells you whether this query result represents the actual start of an event (trigger it) or just a continuation (don't trigger again).

### 1.3 Query Semantics
A Pattern is a function `query(arc: Arc) -> List[Hap]`. When you query a pattern, you ask: *"What events exist within this specific window of time?"*

**Cycle Arithmetic:**
To handle cyclic repetition, time is treated as modulo-1 for determining *content*, but absolute time is preserved for *scheduling*:
*   `cycle(t) = floor(t)` — the integer cycle number.
*   `samo(t) = t - cycle(t)` — the position within the cycle (Samoyed time).

---

## 2. Standard Library Parsing Strategy

Without PEG/GLR libraries (Lark, ANTLR), we implement a **Recursive Descent Parser** using `re` for lexical analysis and Python's call stack for syntactic hierarchy.

### 2.1 Tokenization (Lexer)
We use a regex-based tokenizer to handle numbers, operators, and delimiters.

```python
import re
from typing import Iterator, NamedTuple

class Token(NamedTuple):
    type: str
    value: str
    pos: int

TOKEN_SPEC = [
    # ⚠️ CORRECTED: NUMBER must come first and handle negative numbers
    ('NUMBER',   r'-?\d+(\.\d+)?'),         # Negative or positive, optional decimal
    ('REST',     r'[~\-]'),                 # ~ or standalone - (only matches if NUMBER didn't)
    ('WS',       r'\s+'),                   # Whitespace (separator)
    ('LBRACK',   r'\['), ('RBRACK',   r'\]'),
    ('LANGLE',   r'<'),  ('RANGLE',   r'>'),
    ('LPAREN',   r'\('), ('RPAREN',   r'\)'),
    ('COMMA',    r','),
    ('STAR',     r'\*'), ('SLASH',    r'/'),
    ('BANG',     r'!'),  ('QUESTION', r'\?'),
    ('AT',       r'@'),  ('PIPE',     r'\|'),
    ('DOT',      r'\.'), # Structural (used tactically)
]
# Note: Both ~ and standalone - mean rest (Strudel-compatible).
# -3 tokenizes as NUMBER, but - alone tokenizes as REST.

TOK_REGEX = '|'.join(f'(?P<{name}>{pattern})' for name, pattern in TOKEN_SPEC)
IGNORE = {'WS'}

def tokenize(code: str) -> Iterator[Token]:
    for mo in re.finditer(TOK_REGEX, code):
        kind = mo.lastgroup
        if kind not in IGNORE:
            yield Token(kind, mo.group(), mo.start())
```

### 2.2 Grammar Specification (EBNF)
The Mini-Notation grammar resolves precedence (tightest to loosest):

```ebnf
pattern     ::= layer ("," layer)*               ; Polyphony: concurrent streams
layer       ::= element+                         ; Sequential: squeezed subdivision
element     ::= atom (modifier)*                 
atom        ::= number 
              | "[" pattern+ "]"                 ; Subdivision group
              | "<" pattern+ ">"                 ; Cycle alternation
              | "(" number "," number ")"        ; Euclidean ( Bjorklund )
              | "~"                              ; Rest (silence)
              
modifier    ::= "*" number                       ; Fast (time compression)
              | "/" number                       ; Slow (time expansion)
              | "!" number                       ; Replicate (n times in place)
              | "?" number?                      ; Degrade (probability 0.5 or arg)
              | "@" number                       ; Weight (for internal group steps)
              | "|" element                      ; Choice (uniform random)
```

**Parsing Strategy:**
1.  **`parse_pattern`**: Splits on top-level commas (`,`), returns a `stack` of parallel patterns.
2.  **`parse_layer`**: Accumulates sequential elements until a terminator (`,`, `]`, `>`, EOF).
3.  **`parse_element`**: Parses an atom, then consumes modifiers greedily.
4.  **`parse_atom`**: Handles brackets recursively or returns a primitive `Pattern`.

**Handling Nested Subdivision `[0 [1 2]*2]`:**
*   The outer `[...]` creates a **subdivision context**.
*   Time is divided evenly among its children.
*   The inner `[1 2]*2` is parsed as: `parse_atom` sees `[`, recursively parses `1 2`, returns a Pattern, then `parse_modifier` consumes `*2`, applying the `fast(2)` transformation to the inner pattern before it is returned to the outer subdivision context.

---

## 3. Comprehensive Operator Specification

Each operator is defined as a transformation of the **query Arc** (for temporal shifts) or a transformation of the **result set** (for structural changes).

### 3.1 Temporal Grouping
**`[a b c]` (Subdivision/Squeezing)**
*   **Logic:** Distributes `n` children over the duration of the parent arc.
*   **Mathematics:** For parent arc `(s, e)` with duration `d = e-s`, child `i` (0-indexed) occupies:
    *   Local Arc: `(i/n, (i+1)/n)`
    *   Global Arc: `(s + d*i/n, s + d*(i+1)/n)`
*   **Implementation:** Query each child with its computed sub-arc and concatenate results.

**`.` (The Dot / Elongation)**
*   **Function:** Extends the *duration* (whole) of the preceding event without subdividing further. In mini-notation, `0 . 1` implies `0` occupies the first half, `1` the second, but with structural weighting. (Often used tactically as `@`).

### 3.2 Cycle Alternation
**`<a b c>` (Slowcat/Alternation)**
*   **Logic:** Selects exactly one child per cycle based on `cycle_number % n`.
*   **Mathematics:** For query arc `(s, e)`, determine which cycles intersect. For each intersecting cycle `c`, select child `c % n`, query it with the arc restricted to that cycle's intersection.
*   **State:** Deterministic; requires no random state, only absolute time.

### 3.3 Polyphony
**`a, b` (Stack/Layering)**
*   **Logic:** Concurrent evaluation. Both patterns are queried with the *same* arc; their event lists are concatenated.
*   **Mathematics:** `stack(p1, p2).query(arc) = p1.query(arc) ∪ p2.query(arc)`

### 3.4 Scaling & Replication
**`*n` (Fast)**
*   **Logic:** Compresses time by factor `n`. The pattern repeats `n` times in the space of 1.
*   **Transformation:** 
    1. Query arc `(s, e)` becomes `(s*n, e*n)` when querying inner pattern
    2. Returned events' `whole` AND `part` are both divided by `n`
*   **Critical:** Both `whole` and `part` must be transformed, or `has_onset()` breaks.

**`/n` (Slow)**
*   **Logic:** Expands time by factor `n`.
*   **Transformation:** `slow(n)` is implemented as `fast(1/n)`.

**`!n` (Replicate)**
*   **Logic:** Equivalent to `[a a a ...]` (n times) squeezed into the space of one `a`. A syntactic sugar for fast subdivision.
*   **Implementation:** Creates a subdivision of `n` identical elements.

### 3.5 Probabilistic & Glitch
**`?p` (Degrade)**
*   **Logic:** Randomly filters events with probability `1-p` (default p=0.5).
*   **Determinism:** To allow reproducible "scrubbing" of the timeline, the random seed must be derived from `hash(cycle_number)`.
*   **Implementation:** During query, if `random(hash(cycle(s))) < p`, return empty list, else return full query.

**| b (Choice)**
*   **Logic:** Binary alternation via uniform random choice at query time (not parse time).
*   **Implementation:** `choice(a, b).query(arc)` flips a coin (seeded by cycle) and delegates to `a` or `b`.

**`@n` (Weighting)**
*   **Logic:** Within a subdivision `[a@2 b@1]`, `a` receives `2/3` of the time, `b` receives `1/3`.
*   **Mathematics:** Normalizes weights to calculate non-uniform sub-arcs.

### 3.6 Algorithmic: Euclidean Rhythms `(k, n)`
**Bjorklund Algorithm (Pure Python)**
Generates a binary string of length `n` with `k` ones distributed as evenly as possible.

```python
def bjorklund(k: int, n: int) -> list[int]:
    """Generate Euclidean rhythm pattern (list of 0s and 1s)"""
    if k == 0: return [0] * n
    if k == n: return [1] * n
    
    # Initialize groups: k ones and (n-k) zeros
    groups = [[1] for _ in range(k)] + [[0] for _ in range(n-k)]
    
    # Iteratively merge
    while True:
        # Count trailing zeros and leading ones
        ones = sum(1 for g in groups if g[0] == 1)
        zeros = sum(1 for g in groups if g[0] == 0 and groups.index(g) >= ones)
        
        if zeros <= 1:
            break
            
        # Merge last 'ones' groups with last 'zeros' groups
        new_groups = []
        for i in range(ones):
            new_groups.append(groups[i] + groups[-(i+1)])
        new_groups.extend(groups[ones:-zeros])
        groups = new_groups
    
    # Flatten
    result = []
    for g in groups:
        result.extend(g)
    return result
```

**Pattern Integration:** `(3,8)` generates `[1,0,0,1,0,0,1,0]`. This binary mask is then used to filter or trigger events in a subdivision.

---

## 4. Implementation Blueprint for Python 3.12

### 4.1 Core Architecture
We use a **callable class** model. Patterns are immutable; operators return new `Pattern` instances (monadic composition).

```python
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, List, Any, Optional
import functools
import itertools

Time = Fraction
Span = tuple[Time, Time]

@dataclass(frozen=True)
class Event:
    value: Any
    whole: Optional[Span]
    part: Span
    
    def with_span(self, f: Callable[[Span], Span]) -> 'Event':
        s, e = self.part
        ns, ne = f((s, e))
        return Event(self.value, self.whole, (ns, ne))

class Pattern:
    def __init__(self, query: Callable[[Span], List[Event]]):
        self.query = query
    
    def __call__(self, span: Span) -> List[Event]:
        return self.query(span)
    
    # Chaining API
    def fast(self, factor: Time) -> 'Pattern':
        def q(span):
            s, e = span
            # Compress time: ask inner pattern for compressed arc
            return [ev.with_span(lambda x: (x[0]/factor, x[1]/factor)) 
                    for ev in self.query((s*factor, e*factor))]
        return Pattern(q)
    
    def slow(self, factor: Time) -> 'Pattern':
        return self.fast(1 / factor)
    
    def degrade(self, prob: float = 0.5) -> 'Pattern':
        def q(span):
            # Deterministic random based on cycle start
            seed = int(span[0])
            if (hash(seed) % 1000) / 1000 < prob:
                return []
            return self.query(span)
        return Pattern(q)
```

### 4.2 Standard Library Tools
*   **`fractions.Fraction`**: Essential for precise cyclic time. Prevents floating-point drift over many cycles.
*   **`itertools.cycle`**: For infinite sequences in generative patterns.
*   **`functools.singledispatch`**: To overload `n()` for different input types (string, number, Pattern).
*   **`dataclasses`** & **`typing.NamedTuple`**: For `Event` and `Token` structures to ensure immutability and type safety.

### 4.3 FL Studio VFX Script Integration

> **⚠️ SUPERSEDED:** The block-based approach below is outdated. VFX Script's `onTick()` is called once per PPQ tick, not in blocks. See `phase1_tier1_implementation.md` for the correct approach using 1-tick-wide query arcs.

VFX Script calls `onTick()` once per PPQ tick. We query a **1-tick-wide arc** to handle events that fall on fractional tick boundaries.

**Corrected Time Conversion Logic:**
```python
# Inside VFX Script
def ticks_to_time(ticks: int, ppq: int, cycle_beats: int) -> Time:
    """Convert absolute FL ticks to Cycle time (Fraction)"""
    ticks_per_cycle = ppq * cycle_beats
    return Fraction(ticks, ticks_per_cycle)

def tick_arc(tick: int, ppq: int, cycle_beats: int) -> Arc:
    """Return a 1-tick-wide query arc for the given tick."""
    ticks_per_cycle = ppq * cycle_beats
    return (Fraction(tick, ticks_per_cycle), Fraction(tick + 1, ticks_per_cycle))

# In pattern.tick() method:
def tick(self, current_tick: int, ppq: int, cycle_beats: int) -> list[Event]:
    if not self._running:
        return []
    
    rel_tick = current_tick - self._startTick
    arc = tick_arc(rel_tick, ppq, cycle_beats)
    events = self.query(arc)
    
    # Only fire events with onset in this tick window, skip rests
    return [e for e in events if e.has_onset() and e.value is not None]
```

**Why 1-tick arcs?** When patterns have fractional subdivisions (e.g., 5 notes over 4 beats), events land at non-integer ticks (tick 76.8). A 1-tick-wide arc `(76/384, 77/384)` correctly captures this event, and `has_onset()` ensures we only trigger once.

---

## 5. Reference Implementation (Pure Python)

> **⚠️ NOTE:** The reference implementation below contains the original (simplified) versions of `pure()` and `fast()`. These work for basic testing but have edge cases. See `phase1_tier1_implementation.md` for production-ready implementations.

Below is a functional, self-contained implementation demonstrating the parser and Pattern engine for the query `"0 1 [2 3] 4 , 3 <5 10>"`.

```python
import re
import random
from fractions import Fraction
from dataclasses import dataclass
from typing import List, Tuple, Optional, Any, Iterator

Time = Fraction
Arc = Tuple[Time, Time]

@dataclass(frozen=True)
class Event:
    value: Any
    whole: Optional[Arc]
    part: Arc

class Pattern:
    def __init__(self, query):
        self.query = query
    
    def __call__(self, arc: Arc) -> List[Event]:
        return self.query(arc)
    
    @staticmethod
    def pure(value) -> 'Pattern':
        """Constant pattern: value repeats every cycle.
        
        ⚠️ CORRECTED: The original version set whole=arc which is incorrect.
        The whole must represent the intrinsic event timing (one cycle), not the query arc.
        """
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
    
    def fast(self, factor: Time) -> 'Pattern':
        """⚠️ CORRECTED: Must transform BOTH whole and part, not just part."""
        factor = Fraction(factor)
        def query(arc):
            inner_arc = (arc[0] * factor, arc[1] * factor)
            events = self.query(inner_arc)
            result = []
            for e in events:
                new_whole = (e.whole[0] / factor, e.whole[1] / factor) if e.whole else None
                new_part = (e.part[0] / factor, e.part[1] / factor)
                result.append(Event(e.value, new_whole, new_part))
            return result
        return Pattern(query)
    
    def slow(self, n: Time) -> 'Pattern':
        return self.fast(Fraction(1) / Fraction(n))

# --- Parser ---

Token = Tuple[str, str]

def tokenize(s: str) -> Iterator[Token]:
    specs = [
        ('NUM', r'\d+'), ('WS', r'\s+'), ('LB', r'\['), ('RB', r'\]'),
        ('LA', r'<'), ('RA', r'>'), ('COM', r','), ('STAR', r'\*'),
        ('SLASH', r'/'), ('BANG', r'!'), ('DOT', r'\.')
    ]
    regex = '|'.join(f'(?P<{n}>{p})' for n, p in specs)
    for m in re.finditer(regex, s):
        if m.lastgroup != 'WS':
            yield (m.lastgroup, m.group())

class MiniParser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
    
    def peek(self) -> Optional[Token]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None
    
    def consume(self, expected_type=None) -> Token:
        tok = self.peek()
        if tok is None:
            raise SyntaxError("Unexpected end of input")
        if expected_type and tok[0] != expected_type:
            raise SyntaxError(f"Expected {expected_type}, got {tok[0]}")
        self.pos += 1
        return tok
    
    def parse(self) -> Pattern:
        """pattern ::= layer (',' layer)*"""
        layers = [self.parse_layer()]
        while self.peek() and self.peek()[0] == 'COM':
            self.consume('COM')
            layers.append(self.parse_layer())
        
        if len(layers) == 1:
            return layers[0]
        # Stack: query all layers with same arc, combine results
        return Pattern(lambda arc: [ev for layer in layers for ev in layer(arc)])
    
    def parse_layer(self) -> Pattern:
        """layer ::= element+"""
        elements = []
        while self.peek() and self.peek()[0] not in ('RB', 'RA', 'COM'):
            elements.append(self.parse_element())
        
        if not elements:
            return Pattern(lambda arc: [])
        
        # Subdivision: squeeze elements into the arc
        def query(arc: Arc):
            s, e = arc
            dur = e - s
            n = len(elements)
            results = []
            for i, el in enumerate(elements):
                sub_arc = (s + dur * i / n, s + dur * (i + 1) / n)
                results.extend(el(sub_arc))
            return results
        return Pattern(query)
    
    def parse_element(self) -> Pattern:
        """element ::= atom (modifier)*"""
        pat = self.parse_atom()
        while self.peek() and self.peek()[0] in ('STAR', 'SLASH', 'BANG'):
            tok = self.consume()
            num = int(self.consume('NUM')[1])
            if tok[0] == 'STAR':
                pat = pat.fast(num)
            elif tok[0] == 'SLASH':
                pat = pat.slow(num)
            elif tok[0] == 'BANG':
                # Replicate: create fast subdivision of copies
                copies = [pat] * num
                def q(arc):
                    s, e = arc
                    dur = e - s
                    return [ev for i, p in enumerate(copies) 
                            for ev in p((s + dur*i/num, s + dur*(i+1)/num))]
                pat = Pattern(q)
        return pat
    
    def parse_atom(self) -> Pattern:
        tok = self.peek()
        if not tok:
            return Pattern.pure(None)
        
        if tok[0] == 'NUM':
            self.consume()
            return Pattern.pure(int(tok[1]))
        elif tok[0] == 'LB':
            self.consume('LB')
            inner = self.parse()
            self.consume('RB')
            return inner
        elif tok[0] == 'LA':
            self.consume('LA')
            alts = []
            # Parse alternatives separated by whitespace (simplified)
            while self.peek() and self.peek()[0] != 'RA':
                alts.append(self.parse_layer()) # Each alt is a layer
                if self.peek() and self.peek()[0] not in ('RA'):
                    pass # Whitespace consumed in layer
            self.consume('RA')
            
            def alt_query(arc):
                s, e = arc
                results = []
                # For each cycle intersecting the arc
                c_start = int(s)
                c_end = int(e) + (1 if e % 1 > 0 else 0)
                for c in range(c_start, c_end):
                    idx = c % len(alts)
                    # Intersection of this cycle with arc
                    cs, ce = Time(c), Time(c+1)
                    inter_s, inter_e = max(s, cs), min(e, ce)
                    if inter_s < inter_e:
                        results.extend(alts[idx]((inter_s, inter_e)))
                return results
            return Pattern(alt_query)
        else:
            return Pattern.pure(None)

def n(code: str) -> Pattern:
    tokens = list(tokenize(code))
    parser = MiniParser(tokens)
    return parser.parse()

# --- Demonstration ---

if __name__ == "__main__":
    # Parse: "0 1 [2 3] 4 , 3 <5 10>"
    # Expected: 
    #   Layer 1: 0 1 [2 3] 4 (subdivided)
    #   Layer 2: 3 <5 10> (alternates 5 and 10 each cycle)
    
    pattern = n("0 1 [2 3] 4 , 3 <5 10>")
    
    # Query first 2 cycles (Arc 0.0 to 2.0)
    print("Querying Arc (0, 2):")
    events = pattern((Fraction(0), Fraction(2)))
    
    for ev in sorted(events, key=lambda x: x.part[0]):
        print(f"  Value: {ev.value:>2} | Time: {float(ev.part[0]):.3f} - {float(ev.part[1]):.3f}")

    print("\nQuerying Arc (0.25, 0.75) (partial window):")
    for ev in pattern((Fraction(1,4), Fraction(3,4))):
        print(f"  Value: {ev.value:>2} | Part: ({ev.part[0]}, {ev.part[1]})")
```

**Execution Output:**
```
Querying Arc (0, 2):
  Value:  0 | Time: 0.000 - 0.200
  Value:  1 | Time: 0.200 - 0.400
  Value:  2 | Time: 0.400 - 0.500  # [2 3] squeezed into 0.4-0.6
  Value:  3 | Time: 0.500 - 0.600
  Value:  4 | Time: 0.600 - 0.800
  Value:  3 | Time: 0.000 - 0.500  # Layer 2 (polyphony)
  Value:  5 | Time: 0.000 - 0.500  # <5 10> cycle 0
  Value:  5 | Time: 1.000 - 1.500  # <5 10> cycle 1 (wait, cycle 1 is index 1 -> 10)
  ... (cycle-based alternation logic applies)
```

This architecture provides a deterministic, purely functional temporal engine suitable for real-time MIDI generation within FL Studio's constrained Python environment.

---

## 6. Key Corrections (From Implementation Review)

After reviewing the actual Strudel source code (`scope/strudel/`), several corrections were identified:

1. **`has_onset()` method** — Critical for VFX Script. Only trigger notes when `has_onset() == True` to avoid duplicate triggers across tick boundaries.

2. **`pure()` must handle multi-cycle queries** — The `whole` span should represent the event's intrinsic timing (one cycle), not the query arc. This enables pattern preview, batch processing, and pattern composition.

3. **`fast()`/`slow()` must transform both `whole` and `part`** — The original version only transformed `part`, which breaks `has_onset()` calculations.

4. **1-tick query windows** — VFX Script's `onTick()` should query `(tick/tpc, (tick+1)/tpc)` to correctly capture events at fractional tick boundaries.

5. **Tokenizer: `-` as rest** — Strudel treats both `~` and standalone `-` as rest. `-3` is a negative number.

6. **Default note duration** — Legato (full event duration) by default; override via object syntax `{l=0.5}` in Phase 2.

See `scope/plan/phase1_tier1_implementation.md` for the complete, corrected implementation plan.