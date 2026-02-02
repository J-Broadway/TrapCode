import flvfx as vfx
import trapcode as tc

tc.debug(True, level=1  )

def createDialog():
    ui = tc.UI()
    # Cycle beats: 0.1 = very fast (riser peak), 4 = normal quarter notes
    ui.Knob(name='Cycle', d=2, min=0.1, max=4, export='bind')
    return ui.form

def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)

    # Pass the wrapper directly (not .val) for dynamic updates
    midi.n("0 3 5 7", c=tc.par.Cycle)
    #midi.trigger()

def onReleaseVoice(incomingVoice):
    tc.stop_patterns_for_voice(incomingVoice)
    for v in vfx.context.voices:
        if tc.get_parent(v) == incomingVoice:
            v.release()

def onTick():
    tc.update()

#############


import flvfx as vfx
import trapcode as tc

tc.debug(True, level=1)

_pattern = None

def createDialog():
    ui = tc.UI()
    ui.Checkbox("Start", par_name="start")
    ui.Knob("Cycle", min=0.1, max=4, d=4)
    return ui.form

def onTriggerVoice(incomingVoice):
    pass

def onReleaseVoice(incomingVoice):
    pass

def onTick():
    global _pattern
    
    # Detect checkbox state change
    if tc.par.start.changed():
        if tc.par.start.val:
            # Just turned ON - create and start pattern
            _pattern = tc.n("60 64 67 72", c=tc.par.Cycle, root=0)
            _pattern.start()
        else:
            # Just turned OFF - stop pattern
            if _pattern:
                _pattern.stop()
    
    tc.update()