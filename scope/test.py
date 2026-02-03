# TrapCode Phase 1.2: Note Representations Test
import flvfx as vfx
import trapcode as tc

tc.debug(True, level=1)

def createDialog():
    ui = tc.UI()
    ui.Knob(name='Cycle', d=2, min=0.5, max=4, export='bind')
    return ui.form

def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    
    # === TEST CASES FOR NOTE REPRESENTATIONS ===
    
    # 1. Basic note names (absolute MIDI values)
    # midi.n("c4 d4 e4 f4", c=tc.par.Cycle)  # C major scale: 60, 62, 64, 65
    
    # 2. Accidentals (sharps and flats)
    # midi.n("c4 c#4 d4 eb4", c=tc.par.Cycle)  # Chromatic: 60, 61, 62, 63
    
    # 3. Default octave (3 when not specified)
    # midi.n("c d e f", c=tc.par.Cycle)  # Octave 3: 48, 50, 52, 53
    
    # 4. Different octaves
    # midi.n("c3 c4 c5 c6", c=tc.par.Cycle)  # 48, 60, 72, 84
    
    # 5. Chords with note names (polyphony)
    # midi.n("[c4, e4, g4]", c=tc.par.Cycle)  # C major chord
    
    # 6. Chord progression
    # midi.n("<[c4,e4,g4] [d4,f4,a4] [e4,g4,b4] [f4,a4,c5]>", c=tc.par.Cycle)
    
    # 7. Mixed absolute (notes) and relative (numbers)
    # midi.n("c4 0 4 7", c=tc.par.Cycle)  # c4=60, then root+0, root+4, root+7
    
    # 8. Note names with modifiers
    # midi.n("c4*2 e4 g4", c=tc.par.Cycle)  # c4 fast, then e4, g4
    # midi.n("c4@2 e4 g4", c=tc.par.Cycle)  # c4 weighted (2/4 time)
    # midi.n("c4 e4? g4", c=tc.par.Cycle)   # e4 50% chance
    
    # 9. Stacked accidentals (double sharp/flat)
    # midi.n("c4 c##4 d4 dbb4", c=tc.par.Cycle)  # 60, 62, 62, 60
    
    # 10. Arpeggio with note names
    # midi.n("[c4 e4 g4 c5]", c=tc.par.Cycle)  # C major arpeggio
    
    # === ACTIVE TEST (uncomment one above or use this) ===
    # Em - Am - Bm - Em/G chord progression
    midi.n("<[g3,b3,e4] [a3,c4,e4] [b3,d4,f#4] [b3,e4,g4]>", c=tc.par.Cycle)

def onReleaseVoice(incomingVoice):
    tc.stop_patterns_for_voice(incomingVoice)
    for v in vfx.context.voices:
        if tc.get_parent(v) == incomingVoice:
            v.release()

def onTick():
    tc.update()
