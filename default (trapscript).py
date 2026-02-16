# TrapScript boilerplate
import flvfx as vfx
import trapscript as ts

def createDialog():
    ui = ts.UI()
    # Add controls here
    # ui.Knob(name='MyKnob', d=0.5, min=0, max=1)
    return ui.form

def onTriggerVoice(incomingVoice):
    midi = ts.MIDI(incomingVoice)
    # midi.trigger()

def onReleaseVoice(incomingVoice):
    ts.stop_patterns_for_voice(incomingVoice)
    for v in vfx.context.voices:
        if ts.get_parent(v) == incomingVoice:
            v.release()

def onTick():
    ts.update()