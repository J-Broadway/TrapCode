"""
3. Voice Creation Script - Generates voices at a steady rate. The time between
generations, the note number used, the pan and velocity, and the duration of the
voice can be controlled.
"""
import flvfx as vfx # VFX Script API, for FL <-> Python communication

# Since we are generating voices in this case (rather than modifying voices), we
# don't need onTriggerVoice() and onReleaseVoice() calls. Most of the work is
# done during the onTick() call, where we'll use vfx.context.ticks and
# vfx.context.PPQ to see what the clock time is, and if a voice should be
# generated on that tick.
def onTick():
  # Get parameters from UI controls:
  note_number = vfx.context.form.getInputValue('Note Number')
  note_period = pow(2,vfx.context.form.getInputValue('Period')-1)
  note_length = vfx.context.form.getInputValue('Length')
  note_pan = vfx.context.form.getInputValue('Pan')
  note_velocity = vfx.context.form.getInputValue('Velocity')
  # Set period between voice generations (PPQ = ticks/quarter note)
  stepTicks = int(note_period*vfx.context.PPQ/2) # Time between notes in ticks
  if vfx.context.isPlaying and vfx.context.ticks % stepTicks == 1:
    v = vfx.Voice()  # Create new voice
    v.note = note_number  # Set pitch via note number
    v.length = int(note_length*stepTicks) # Set note length in ticks
    v.pan = note_pan  # Set voice pan
    v.velocity = note_velocity  # Set voice velocity
    v.trigger()  # Trigger the voice

# Note that since we are generating voices and setting their length at trigger
# time, we don't need to manually release them; they will be release automatically
# at v.length ticks after triggering.

# We create the needed UI controls in the createDialog() call:
def createDialog():
  form = vfx.ScriptDialog('', 'Generate a steady pulse of notes.')
  form.addInputKnobInt('Note Number',60,0,131,hint='Note number in semitones')
  form.addInputKnobInt('Period',1,1,4,hint='Time between notes in 1/8th notes')
  form.addInputKnob('Length',0.5,0,1,hint='Note length (% of period)')
  form.addInputKnob('Pan',0,-1,1,hint='Voice Pan')
  form.addInputKnob('Velocity',0.8,0,1,hint='Voice Velocity')
  return form