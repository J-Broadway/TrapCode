import flvfx as vfx
import trapcode as tc
import math

# Store reference to triggered voice
_btn_voice = None

def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    midi.trigger()

def onTick():
    global _btn_voice
    btn = tc.surface('mybtn')
    knob = tc.par.ChangeMe

    if btn.changed():
        if btn.val:
            # Create and trigger C5 (note 72)
            _btn_voice = vfx.Voice()
            _btn_voice.note = 72  # C5
            _btn_voice.velocity = 100
            _btn_voice.trigger()
        else:
            # Release the voice
            if _btn_voice is not None:
                _btn_voice.release()
                _btn_voice = None
    

def onReleaseVoice(incomingVoice):
    for v in vfx.context.voices:
        if v.parentVoice == incomingVoice:
            v.release()

def createDialog():
    ui = tc.UI()
    ui.Knob(name='ChangeMe', d=0, min=0, max=1, hint='Speed', export='bind')
    ui.Surface()
    return ui.form