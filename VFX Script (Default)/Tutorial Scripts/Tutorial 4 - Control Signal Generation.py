"""
4. Control Signal Generation Script - Creates a classic sinusoidal LFO that can
be used to modulate plugin parameters. In order to generate control signals,
"Output Controllers" must be created in the script.
"""
import flvfx as vfx # VFX Script API, for FL <-> Python communication
import math # Extra Python library for math functions

# Here we'll define some variables that will need to be accessed by multiple
# different function calls within the script. In this case, the phase of the LFO
# must persist from one onTick() call to another, and the list of options for
# how the clock is synced will be used by both onTick() and createDialog():
phase = 0  # Current phase of the LFO (updated during onTick())
clock_options = ['Free','Synced']  # Clock sync control options

# We are only dealing with a control signal in this script, so we do not need
# onTriggerVoice() or onReleaseVoice() calls. We need an onTick() call so that 
# we can update the control signal every tick and set the output value.
def onTick():
  global phase

  # Grab the current control values from the UI elements
  clock_option = clock_options[vfx.context.form.getInputValue('Speed: Clock')]
  amp_scale = vfx.context.form.getInputValue('Amplitude: Amplitude')
  amp_offset = vfx.context.form.getInputValue('Amplitude: Offset')

  # Determine the current phase of the LFO. Note that we give the user the option
  # have the phase synced to the clock, or to let it run free. If synced, then
  # we get the clock time in ticks and derive the phase from that. If free, then
  # we increment the phase from where it was last tick (which is why we need
  # phase to be a global variable that persists between calls)
  phase_increment = 2*math.pi*vfx.context.form.getInputValue('Speed: Speed')/vfx.context.PPQ
  if clock_option == 'Synced':
    phase = vfx.context.ticks*phase_increment  # Set phase based on clock
  elif clock_option == 'Free':
    phase += phase_increment  # Increment phase from its previous value

  # Create the sinusoidal LFO using math.sin() and current phase
  LFO = 0.5*math.sin(phase) + 0.5
  # Apply amplitude scaling to the LFO
  LFO = amp_scale*(LFO-0.5) + 0.5
  # Apply a prescribed offset to the LFO
  LFO += amp_offset*0.5*(1.0-amp_scale)
  # Set the output controller with the current LFO value
  vfx.setOutputController('LFO',LFO)

# In addition to the desired UI controls, we will also create an output controller
# using the vfx.addOutputController(name, default_value) call. Output controllers
# are used to output control signals for controlling/modulating parameters in other
# plugins in Patcher. Also note that we are grouping the UI controls using the
# form.addGroup() and form.endGroup() functions. Input groups are given a name, 
# and that name is then referenced when accessing the UI elements elsewhere in the
# script ('GroupName: InputName').
def createDialog():
  form = vfx.ScriptDialog('', 'Sinusoidal LFO.')
  form.addGroup('Speed') # Begin UI group, give it a name
  form.addInputKnob('Speed',0.5,0,1,hint='LFO speed: cycles / quarter note')
  form.addInputCombo('Clock',clock_options,0,hint='Sync to clock or run free')
  form.endGroup() # End current UI group
  form.addGroup('Amplitude')
  form.addInputKnob('Amplitude',1,0,1,hint='LFO amplitude')
  form.addInputKnob('Offset',0,-1,1,hint='LFO offset')
  form.endGroup()
  vfx.addOutputController('LFO', 0) # Create an output controller for the control signal
  return form