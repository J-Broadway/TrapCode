We need to unify ts.comp and ts.MIDI via a composite design pattern that passes inheretence down to its children.
ts.MIDI is different than ts.comp in that .trigger() and .stop() is triggered via parent voice.

The _CompContext object has the following kwarg attributes.
When these attributes are set a the comp level PatternChain .note() / .n() should inherit it be default.

| kwarg | default | where used | notes |
|---|---|---|---|
| octave | 4 | `Comp.__init__` | Default octave for note-name root parsing |
| scale | None | `Comp.__init__` + `_configure_context` | Scale string, e.g. `"c:minor"` |
| root | None | `Comp.__init__` | Optional root override for implicit scales |
| cycle | 4 | `Comp.__init__` + `_configure_context` | Default pattern cycle (beats) |
| velocity | 80 | `_configure_context` | Stored as default voice velocity |
| length | None | `_configure_context` | Default note length override |
| pan | 0.0 | `_configure_context` | Default pan -1..1 |
| output | 0 | `_configure_context` | Default output port |
| fcut | 0.0 | `_configure_context` | Default mod X / cutoff |
| fres | 0.0 | `_configure_context` | Default mod Y / resonance |
| finePitch | 0.0 | `_configure_context` | Default microtuning offset |
| color | 0 | `_configure_context` | Default note color/channel |
| releaseVelocity | 0 | `_configure_context` | Stored default release velocity |
| parent | None | `Comp.__init__` |  |

Current Pattern Chain *kwargs

kwarg	default	notes
cycle	None	Per-pattern override; falls back to context cycle
scale	None	Per-pattern scale override; falls back to context scale
mute	False	Creates ghost/silent pattern
bus	None	Optional bus name for cross-scope state
c	alias	Alias for cycle (via **kwargs alias resolution)
**kwargs	—	Currently used for aliases (not arbitrary free-form options)



## Example

```python
comp = ts.comp(scale="c:minor")
pattern = comp.n("[0 1 2 3 4]").trigger() # Scale is c:minor
pattern2 = comp.n("[3 2 1 0]", scale="d:minor").trigger() # Scale can be overwritten at child level
```

## Polyrythmic chaining with mini-notation
I would like to make use of strudel's mini notation parsing in order to effectively set PatternChain attributes.
This would allow for intricate polyrythms with  verry little code form user.

I believe it should be available for these attributes (with examples), however, we need a design pattern that would allow us to add more or exclude others in the future if needed.

- ocative # "[4 5 6]"
- scale # "c:minor e:minor g:major"
- root # 
- cycle
- velocity
- length
- pan
- output
- fcut
- fres
- finePitch
- color
- releaesVelocity

I'm uncertain if in order for the above to work if we'd need to create a separate mini-notation parsers for _CompContext? Perhaps there is a design pattern that would gracefully allow us to split the parsers while mainting the temporal aspect so if we make temporal changes to the parser it propogates to both parsers without having to write code twice. Looking for feedback on this

Furthermore for the available attributes above, we'd need to gracefully handle scenarios where root is specified like 'g5' and also a octave '3'


Example:
```python
comp = ts.comp(scale="c:minor").velocity("50 80").output("0 1?") # Using mini notation parsing engine to flip between velocity 50 <--> 80 for the comp and a 50% chance to output to 1.
pat = comp.n("0 1 2 3").trigger() # Output --> 0: 50 velocity, 1: 80 velocity, 2: 50 velocity, 3: 80 velocity
pat2 = comp.n("0 1 2 3").velocity("20 [30 40] 100").trigger() # can override parent at child level, comp .output() still in effect.
```

Currently, if my understanding is correct, PatternChain is not composable with _CompContext and lacks the proper Composite Design pattern to make the above possible.

I am also unsure on what the best syntax should be if something like
comp = ts.comp(scale="c:minor").velocity("50 80").output("0 1?")
is best or something like this
comp = ts.comp(scale="c:minor", velocity="50 80", output="0 1?")
Maybe both? I think I prefer the former as it more follows Strudel's syntax but interested to hear your thoughts

Pleaes I'm looking for feedback. It is critical we get this right, for the sustained future scaleability of Trapscript.