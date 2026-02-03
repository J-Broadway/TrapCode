# TrapCode Tier 2 Operators Test
import flvfx as vfx
import trapcode as tc

tc.debug(True, level=1)

def createDialog():
    ui = tc.UI()
    ui.Knob(name='Cycle', d=2, min=0.5, max=4, export='bind')
    return ui.form

def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    
    # === TEST CASES FOR TIER 2 OPERATORS ===
    
    # 1. Weighting (@): a@2 b gives 'a' 2/3 of the time, 'b' 1/3
    # midi.n("0@2 7", c=tc.par.Cycle)  # Long root, short octave
    
    # 2. Replicate (!): a!3 plays 'a' three times in its slot
    # midi.n("0!3 7", c=tc.par.Cycle)  # Three root notes, then octave
    
    # 3. Degrade (?): a? plays 'a' 50% of the time (deterministic)
    # midi.n("0 3? 5 7?", c=tc.par.Cycle)  # Root always, 3rd/7th random
    
    # 4. Polyphony (,): a, b plays both simultaneously
    # midi.n("0, 4, 7", c=tc.par.Cycle)  # Major chord
    
    # 5. Combined: weighted polyphonic arpeggio
    # midi.n("0@2 3, 7@2 12", c=tc.par.Cycle)  # Two voices with weighting
    
    # 6. Nested: replicated subdivision with degrade
    # midi.n("[0 3 5]!2, 12?", c=tc.par.Cycle)  # Arp x2 + random octave
    
    # === ACTIVE TEST (uncomment one above or use this) ===
    midi.n("0@2 3 5, 7!2 12?", c=tc.par.Cycle)

def onReleaseVoice(incomingVoice):
    tc.stop_patterns_for_voice(incomingVoice)
    for v in vfx.context.voices:
        if tc.get_parent(v) == incomingVoice:
            v.release()

def onTick():
    tc.update()
