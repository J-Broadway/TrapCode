# TrapCode Phase 1.2: Note Representations Test
import flvfx as vfx
import trapcode as tc

tc.debug(True, level=1)

def createDialog():
    ui = tc.UI()
    ui.Knob(name='Cycle', d=1, min=0.5, max=4, export='bind')
    return ui.form

def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    
    # === STUTTER DEBUG TESTS ===
    # Compare these patterns - both should be 4 notes in 1 cycle
    
    # A. Works fine (slowcat + fast)
    # midi.n("<0 2 4 5>*4", c=1)
    
    # B. Stutters? (plain sequence with note names)
    # midi.n("c4 c#4 d4 eb4", c=1)
    
    # C. Test with numbers (same structure as B)
    # midi.n("60 61 62 63", c=1)
    
    # D. Test subdivision with numbers
    # midi.n("0 1 2 3", c=1)
    
    # === OTHER TEST CASES ===
    
    # Chords with note names (polyphony)
    # midi.n("[c4, e4, g4]", c=tc.par.Cycle)  # C major chord
    
    # Chord progression
    # midi.n("<[c4,e4,g4] [d4,f4,a4] [e4,g4,b4] [f4,a4,c5]>", c=tc.par.Cycle)
    
    # Note names with modifiers
    # midi.n("c4 e4?0.5 g4", c=tc.par.Cycle)   # e4 50% chance
    
    # === ACTIVE TEST ===
    midi.n("c4 c#4 d4 eb4", c=1)  # Test case B

def onReleaseVoice(incomingVoice):
    tc.stop_patterns_for_voice(incomingVoice)
    for v in vfx.context.voices:
        if tc.get_parent(v) == incomingVoice:
            v.release()

def onTick():
    tc.update()
