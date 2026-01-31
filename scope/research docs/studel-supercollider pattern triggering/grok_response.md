### Strudel Research

Strudel is a JavaScript-based live coding environment inspired by TidalCycles, using a mini-notation for patterning sounds and MIDI events. It operates on repeating cycles (typically tied to beats per second), where patterns define events over time. For MIDI, it sends note-on and note-off messages via WebMIDI or similar outputs.

1. **Mini-notation for notes, velocity, and duration**:
   - Notes are represented as pitch names (e.g., "c3 d3 e3") or MIDI numbers (e.g., "60 62 64"). Sequences are space-separated, dividing the cycle evenly (e.g., "c3 d3 e3 f3" gives each note 1/4 of the cycle).
   - Velocity is added as a modifier, such as .velocity("<0.5 0.7 0.9>") or # velocity "0.8", patterning values between 0 and 1 (scaled to 0-127 for MIDI).
   - Duration is implicit in the pattern structure (e.g., more notes shorten each) or explicit with @ for elongation (e.g., "c3@2 d3" makes the first note span 2 cycles). For finer control, .sustain("<0.5 0.75>") sets the hold time relative to the event step, or dur can be patterned separately.

2. **Pattern triggering/scheduling**:
   - Patterns run in fixed cycles (e.g., 1 cycle = 1 second at 1 BPS). The scheduler queries the pattern for active events within the upcoming cycle's time arc and schedules them precisely.
   - Triggering happens at event onsets; the system evaluates the pattern declaratively, allowing real-time changes without restarting. For MIDI, events are queued and sent at exact timestamps, with options like noteOffsetMs (default 10ms) to delay note-off for glitch prevention.

3. **Polyphony (multiple simultaneous notes)**:
   - Handled via layering: Use [] for chords (e.g., note("[c3 e3 g3]")) or stack() for combining patterns (e.g., stack(note("c3"), note("e3"))).
   - The system supports unlimited polyphony in theory (limited by hardware/MIDI bus), sending multiple note-ons at the same timestamp. No built-in voice limits or stealing; overlapping events simply play concurrently.

4. **Elegant patterns for note-on/note-off semantics**:
   - Note-on is sent at event start with velocity; note-off at event end based on sustain/dur. For gated behavior, input MIDI note-on/off can control gain (e.g., note-on sets gain >0, off sets 0).
   - Patterns like .midi({isController: true}) allow mapping external inputs to parameters. Anti-glitch offsets ensure clean transitions. For sequences, events with zero velocity can act as implicit offs, but explicit dur-based offs are standard.

### SuperCollider Research

SuperCollider is a real-time audio synthesis language with a client-server architecture. Notes are created via Synth objects (server-side nodes), often driven by patterns like Pbind for sequencing.

1. **Synth and Pbind/patterns for note creation**:
   - Synth: Created with Synth.new(\defname, [args]), where \defname references a SynthDef (a UGen graph). Args set initial parameters like \freq or \amp.
   - Pbind: Binds keys (e.g., \midinote, \dur) to patterns (e.g., Pseq([60, 62, 64], inf)). Calling .play spawns a new Synth per event via an EventStreamPlayer, mapping keys to SynthDef controls. For example, Pbind(\instrument, \default, \midinote, Pseq([60, 62], inf), \dur, 0.25).play schedules events on a clock.

2. **Notes released (gate, sustain, explicit release)**:
   - Gate: Common in SynthDef envelopes (e.g., EnvGen.kr(Env.adsr, \gate.kr(1), doneAction:2)). Set \gate to 1 for on, 0 for release via synth.set(\gate, 0).
   - Sustain: Controlled by envelope stages (e.g., sustain level in ADSR) or \sustain key in events (duration before release). Legato overlaps via \legato >1.
   - Explicit: synth.release (triggers release phase) or synth.free (immediate termination). Patterns can automate this with \type, \noteOff for MIDI-like offs.

3. **Voice allocation and polyphony**:
   - Each event spawns a new Synth node, enabling polyphony limited by CPU/memory. Nodes are dynamically allocated with auto-IDs.
   - No built-in voice stealing; implement manually by tracking Synths in an array and freeing oldest/lowest-priority on overflow (e.g., round-robin or priority-based). Groups organize nodes for batch control. Ppar combines patterns for parallel voices.

4. **Patterns for parameter modulation during note lifetime**:
   - Use synth.set(\param, value) to update running Synths (e.g., modulate \freq over time).
   - Pmono(\instrument, ...) creates/modulates a single Synth (monophonic). For poly, PmonoArtic adds articulation. Pbind with \type, \set modulates existing nodes (e.g., ID-based). Function patterns like Pfunc or Prout allow custom logic for modulation sequences.

### API Patterns for Tick-Based Python Environment

Your setup is tick-based (onTick() loop), so APIs must be non-blocking, stateful, and tick-aware. Strudel/Tidal's declarative patterns and SuperCollider's object/node model translate well, emphasizing stored references for control.

**Translatable Patterns**:
- **Note Object Model (from SuperCollider Synth)**: Aligns with your tc.Note(72, v=100).trigger() then note.release(). Store active notes in a list/dict for polyphony. Add methods like note.modulate('velocity', 80) or note.sustain(ticks) for runtime changes, mirroring synth.set.
- **Duration-Based Auto-Release (from Strudel dur/sustain)**: For minimal boilerplate, add a .play(dur_ticks) method that triggers note-on and schedules release after dur_ticks (track via note.end_tick = current_tick + dur_ticks). In onTick(), check and release expired notes automatically.
- **Pattern Scheduling (from Strudel cycles + SuperCollider Pbind)**: Create a Pattern class that evaluates sequences on each tick. Define patterns declaratively (e.g., pattern = Pattern/notes=[72, 74, 76], durs=[4, 4, 8])) and advance via pattern.tick(), triggering notes at offsets. Use a queue for future events (e.g., heapq for tick-stamped triggers). This handles sequencing without event loops.
- **Polyphony Handling (from both)**: Maintain a voices list; spawn new Note instances per simultaneous event. For modulation, attach tick-based interpolators (e.g., note.add_mod('pitch', start=72, end=84, over_ticks=10)) and update in onTick().
- **MIDI-Specific Semantics (from Strudel note-off offset)**: Add configurable offset_ticks for note-off to avoid glitches in FL Studio.

**Anti-Patterns to Avoid**:
- Global state for notes/patterns—use instance-based (e.g., per-channel or per-script) to prevent conflicts in multi-script environments.
- Busy-waiting or sleeps in onTick()—keep it lightweight; offload to state checks (e.g., don't iterate all history each tick).
- Assuming uniform tick timing—FL Studio ticks may vary with CPU load, so use cumulative tick counts over real-time assumptions.
- Overly implicit magic (e.g., auto-poly without limits)—expose voice caps with stealing (free oldest note, like manual SC implementations) to prevent resource leaks.
- Verbose event creation—default common params (vel=100, channel=1) to reduce boilerplate, but avoid hiding errors like un-released notes.