"""
1. Bypass Script - Passes notes unaffected. This is done by creating a new voice
(i.e. a note) for each incoming voice, and copying the properties of the
incoming voice to the new one.
"""
import flvfx as vfx # VFX Script API, for FL <-> Python communication

# Create a modified voice class, which inherits from the vfx.Voice class, and
# add any needed properties. In this example we create a parentVoice property
# so that the new voice can keep tabs on the incoming voice that spawned it.
class ModifiedVoice(vfx.Voice):
  parentVoice = None

# onTriggerVoice(incomingVoice) is called whenever there is a note event
# happens, with incomingVoice (a vfx.Voice) being that event. In this example
# we create a new voice based on the incoming voice and trigger it. Note that
# incoming voices can't be triggred in the script.
def onTriggerVoice(incomingVoice):
  v = ModifiedVoice(incomingVoice) # Create voice, copy values from incomingVoice
  # v.note = frequency as MIDI note number
  # v.finePitch = note offset (fractional note number)
  # v.pan = stereo pan [-1,1]
  # v.velocity = note velocity/loudness [0,1]
  v.parentVoice = incomingVoice # Keep track of the parent voice that spawned new voice
  v.trigger() # Trigger the new voice

# onTick is called for every tick of the clock. In this example, we go through
# the active voices and for each, copy the properties of the parent voice. This
# done so that any variation in pitch (e.g. from slide notes) is properly conveyed
# to the new voice.
def onTick():
  # vfx.context.tick = current clock time, in ticks
  # vfx.context.PPQ = ticks per quarter note
  for v in vfx.context.voices: # For all active voices...
    v.copyFrom(v.parentVoice) # Copy properties of parent voice

# onReleaseVoice(incomingVoice) is called whenever an incoming voice gets
# released (i.e. ends). In this example, we go through the active voices, and
# if any have a the incoming voice as a parent, we release that voice.
def onReleaseVoice(incomingVoice):
  for v in vfx.context.voices: # For all active voices...
    if v.parentVoice == incomingVoice: # If its parent is the incoming voice...
      v.release() # End the voice/note

# The createDialog() call is for creating the UI for controlling the script.
# In this example there is only some text displayed, but this would be where
# controls would be defined.
def createDialog():
  form = vfx.ScriptDialog('', 'Bypass script - passes notes unaffected.')
  return form