# This is the default script that is loaded when VFX Script is launched.
import flvfx as vfx

class ModifiedVoice(vfx.Voice):
  parentVoice = None

def onTriggerVoice(incomingVoice):
  v = ModifiedVoice(incomingVoice)
  v.parentVoice = incomingVoice
  v.trigger()
  
def onTick():
  for v in vfx.context.voices:
    v.copyFrom(v.parentVoice)
    
def onReleaseVoice(incomingVoice):
  for v in vfx.context.voices:
    if v.parentVoice == incomingVoice:
      v.release()
  
def createDialog():  
  form = vfx.ScriptDialog('', 'Default: passes notes unaffected. Try some presets!')
  return form