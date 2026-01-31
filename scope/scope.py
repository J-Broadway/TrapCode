import flvfx as vfx
import trapcode as tc

# Create Note once outside onTick (persists across ticks)
myNote = tc.Note(m=60, v=30, l=1)

def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    midi.trigger()

def onTick():
    btn = tc.surface('mybtn')
    
    # Button press triggers note, auto-releases after 4 beats
    if btn.pulse():
        myNote.trigger()
    
    if tc.par.ChangeMe.changed(threshold=1):
        myNote.m = int(tc.par.ChangeMe.val)
        myNote.trigger()
    
    # Process triggers and releases
    tc.update()

def onReleaseVoice(incomingVoice):
    for v in vfx.context.voices:
        if v.parentVoice == incomingVoice:
            v.release()

def createDialog():
    ui = tc.UI()
    ui.Knob(name='ChangeMe', d=0, min=36, max=96, export='bind')
    ui.Surface()
    return ui.form