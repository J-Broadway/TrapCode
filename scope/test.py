# TrapCode Bus System Tests
import flvfx as vfx
import trapcode as tc

tc.debug(True, level=1)

def createDialog():
    ui = tc.UI()
    ui.Knob(name='Cycle', d=1, min=0.5, max=4, export='bind')
    return ui.form

def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    
    # === BUS SYSTEM TESTS ===
    # Uncomment one test at a time
    
    # --- Test 1: Basic bus registration ---
    # Register pattern to 'melody' bus, access state in onTick
    chain = midi.n("<[c4,e4,g4] [d4,f#4,a4] [e4,g#4,b4]>", c=tc.par.Cycle, bus='melody')
    
    # --- Test 2: Ghost pattern (mute=True) ---
    # Pattern ticks but produces no sound, state only
    # midi.n("<0 1 2 3>", c=1, mute=True, bus='melody')
    
    # --- Test 3: Multiple voices on same bus ---
    # Play two different notes, both register to 'melody'
    # midi.n("<0 4 7>", c=tc.par.Cycle, bus='melody')
    
    # --- Test 4: Chained access test ---
    # midi.n("<[c4,e4,g4] [d4,f#4,a4] [e4,g#4,b4]>", c=4, bus='chords')

def onReleaseVoice(incomingVoice):
    tc.stop_patterns_for_voice(incomingVoice)
    
    for v in vfx.context.voices:
        if tc.get_parent(v) == incomingVoice:
            v.release()

def onTick():
    melody = tc.bus('melody')
    pattern = melody.newest()
    if pattern and pattern['n'] == [0]:
        print(pattern.dict())
    tc.update()
