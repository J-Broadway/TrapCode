"""
2. Voice Modification Script - Takes incoming voices and modifies them, providing
controls to change the pitch, pan and velocity of the voice.
"""
import flvfx as vfx # VFX Script API, for FL <-> Python communication

# In this case, we want to add some extra properties to the modified note class.
# We want to keep track of the pitch offset, the modified pan, and the modified
# velocity values. We need to keep track of them so that they can be applied both
# at trigger time, and also during onTick() updates.
class ModifiedVoice(vfx.Voice):
  parentVoice = None  # Original incoming voice
  noteOffset = 0  # Pitch offset, in semitones
  modifiedPan = 0  # Midified pan: [-1, 1]
  modifiedVelocity = 0.8  # Modified velocity: [-1, 1]

# When an incoming voice is triggered, we need to make a new voice that is based
# on the incoming one, and then set the values of
def onTriggerVoice(incomingVoice):
  v = ModifiedVoice(incomingVoice)
  # Get pitch offset, pan, and velocity from the UI inputs:
  v.noteOffset = vfx.context.form.getInputValue('Pitch Offset')
  v.modifiedPan = vfx.context.form.getInputValue('Pan')
  v.modifiedVelocity = vfx.context.form.getInputValue('Velocity')
  # Apply the pitch offset, pan, and velocity to the voice:
  v.note += v.noteOffset
  v.pan = v.modifiedPan
  v.velocity = v.modifiedVelocity
  v.parentVoice = incomingVoice # Keep track of the parent voice that spawned new voice
  v.trigger() # Trigger the new voice

# We need to copy the values from the parent voice every tick, in order for note
# slides to work. And once the voice properties have been copied from the parent
# voice, we need to re-apply the pitch offset, pan, and velocity, using the values
# that were stored in the modified voice class.
def onTick():
  for v in vfx.context.voices:  # For all active voices:
    v.copyFrom(v.parentVoice)  # Copy properties of original voice
    v.note += v.noteOffset  # Re-apply pitch offset
    v.pan = v.modifiedPan  # Re-apply pan
    v.velocity = v.modifiedVelocity  # Re-apply velocity

# Release voices when their corresponding parent voice gets released.
def onReleaseVoice(incomingVoice):
  for v in vfx.context.voices:  # For all active voices...
    if v.parentVoice == incomingVoice:  # If its parent is the incoming voice...
      v.release()  # End the voice/note

# In this case there will be controls on the UI for controlling the pitch offset,
# the pan, and the velocity. UI controls are created in the createDialog() call,
# and the controls are then accessed using vfx.context.form.getInputValue().
def createDialog():
  form = vfx.ScriptDialog('', 'Add note offset, set pan and velocity values.')
  form.addInputKnobInt('Pitch Offset',0,-12,12,hint='Pitch offset in semitones')
  form.addInputKnob('Pan',0,-1,1,hint='Voice Pan')
  form.addInputKnob('Velocity',0.8,0,1,hint='Voice Velocity')
  # UI types that are available:
  # form.addInputKnob(name, default, min, max, hint)
  # form.addInputKnobInt(name, default, min, max, hint)
  # form.addInputCheckbox(name, default, hint)
  # form.addInputCombo(name, option_list, default_index, hint)
  # form.addInputText(name, default)
  return form