"""
Note Repeat - Retriggers held notes once per beat.
Each retrigger cuts off the previous note.
Works whether FL is playing or stopped.
"""
import flvfx as vfx

# Internal tick counter (advances every onTick call, even when stopped)
_tickCount = 0

class ModifiedVoice(vfx.Voice):
    parentVoice = None
    isHeld = False
    triggerTick = 0  # When this voice was triggered

def onTriggerVoice(incomingVoice):
    global _tickCount
    v = ModifiedVoice(incomingVoice)
    v.parentVoice = incomingVoice
    v.isHeld = True
    v.triggerTick = _tickCount
    v.trigger()

def onTick():
    global _tickCount
    _tickCount += 1
    
    stepTicks = vfx.context.PPQ  # 1 beat = PPQ ticks
    
    # Always sync voices with parent (for slides, pitch bend, etc)
    for v in vfx.context.voices:
        if hasattr(v, 'parentVoice') and v.parentVoice is not None:
            v.copyFrom(v.parentVoice)
    
    # Check each held voice for retrigger based on elapsed time since trigger
    toRetrigger = []
    for v in vfx.context.voices:
        if hasattr(v, 'isHeld') and v.isHeld:
            elapsed = _tickCount - v.triggerTick
            if elapsed >= stepTicks:
                toRetrigger.append(v)
    
    # Release old voices and create new ones
    for oldVoice in toRetrigger:
        parent = oldVoice.parentVoice
        oldVoice.release()
        
        # Create fresh voice
        newVoice = ModifiedVoice(parent)
        newVoice.parentVoice = parent
        newVoice.isHeld = True
        newVoice.triggerTick = _tickCount
        newVoice.trigger()

def onReleaseVoice(incomingVoice):
    for v in vfx.context.voices:
        if hasattr(v, 'parentVoice') and v.parentVoice == incomingVoice:
            v.isHeld = False
            v.release()

def createDialog():
    form = vfx.ScriptDialog('', 'Note Repeat - retriggers held notes once per beat')
    return form
