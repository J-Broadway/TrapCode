# TrapCode boilerplate
import flvfx as vfx
import trapcode as tc

def createDialog():
    ui = tc.UI()
    # Add controls here
    # ui.Knob(name='MyKnob', d=0.5, min=0, max=1)
    return ui.form

def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    midi.trigger()

def onReleaseVoice(incomingVoice):
    for v in vfx.context.voices:
        if tc.get_parent(v) == incomingVoice:
            v.release()

def onTick():
    tc.update()