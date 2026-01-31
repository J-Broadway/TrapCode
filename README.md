# TrapCode.py Documentation

TrapCode is a Python library designed to streamline scripting in FL Studio's VFX Script environment. It provides abstractions for MIDI voice handling, UI control creation, parameter management, output controllers, and export proxies. The library aims to reduce boilerplate code while offering intuitive, TouchDesigner-inspired APIs for creative coding in audio/MIDI effects.

## Installation
Place `TrapCode.py` in FL Studio's Python Lib directory (e.g., `C:\Program Files (x86)\Image-Line\FL Studio 2025\Shared\Python\Lib\`).
Import it in your VFX Script with
```python
import TrapCode as tc
```

## Key Concepts
- **Singleton UI**: Only one UI instance per script, created in `createDialog()`.
- **Parameter Namespace (`par`)**: Controls are automatically added as attributes to `tc.par` for global access (e.g., `tc.par.MyKnob.val`).
- **Export Modes**: Controls can bind to output controllers for parameter automation.
- **Coercion and Arithmetic**: UI wrappers support numeric operations (e.g., `par.knob * 2`) and coercion to float/int/bool.
- **Read-Only Properties**: Attributes like `name`, `min`, `max`, `hint` cannot be changed after creation.
- **Grouping Support**: Controls in groups use qualified internal keys (e.g., `"Group: Control"`) for value access, ensuring correct handling in hierarchical UIs.
- **Parameter Filtering**: Use `tc.pars()` to retrieve lists or dicts of parameters with flexible filters for type and group.

## Features

### 1. MIDI Voice Helper
Simplifies voice modification by subclassing `vfx.Voice` and preserving the parent voice.

**Code Example**:
```python
def onTriggerVoice(incomingVoice):
    midi = tc.MIDI(incomingVoice)
    midi.trigger()  # Trigger the modified voice
```

### 2. Helpers
Utility functions for clamping, normalization, and warnings.

- `_clamp(x, lo, hi)`: Clamps `x` between `lo` and `hi`.
- `_norm_from_range(value, lo, hi)`: Normalizes `value` to [0, 1] based on range [lo, hi].
- `_warn_clamp(name, value, lo, hi)`: Prints a notice if `value` is outside [lo, hi], with line number.

**Code Example**:
```python
value = tc._clamp(1.5, 0, 1)  # Returns 1
norm = tc._norm_from_range(50, 0, 100)  # Returns 0.5
tc._warn_clamp('MyParam', 150, 0, 100)  # Prints notice
```

**Edge Case**:
```python
tc._norm_from_range(5, 10, 10)  # Returns 0.0 (handles lo == hi)
tc._warn_clamp('Edge', -1, 0, 1)  # Warns and clamps to 0
```

### 3. Parameter Namespace (`par`)
Dynamic object for accessing UI controls globally via attributes. Controls are added as attributes to `tc.par` during creation in `createDialog()`, using `par_name` (if provided) or a sanitized version of `name` as the attribute name. Default behavior: If `par_name` is None (not set), it defaults to a sanitized `name` where non-word characters (e.g., spaces, punctuation) are replaced with '_' and leading/trailing '_' are stripped. Attribute names must be valid Python identifiers (start with letter/underscore, no spaces/special chars except '_'); invalid ones raise ValueError.

**Defaults**:
- `par_name`: None (falls back to sanitized `name`).

**Edge Cases**:
- If `name` has spaces/special chars (e.g., 'My Knob!'), sanitized to 'My_Knob' (if `par_name` not set).
- If `par_name` is invalid (e.g., 'my knob' with space or '123knob' starting with number), raises ValueError.
- Duplicate names/par_names raise ValueError (unique required).
- If name is empty or sanitizes to invalid (e.g., all special chars sanitizing to ''), raises ValueError.

**Code Example**:
```python
def createDialog():
    ui = tc.UI()
    ui.Knob(name='My Knob', d=0.5)  # Added as tc.par.My_Knob (sanitized)
    ui.Knob(name='Custom', par_name='my_knob', d=0.5)  # Explicit par_name
    return ui.form

def onTick():
    print(tc.par.My_Knob.val)  # Access value
```

**Edge Case**:
```python
ui.Knob(name='Invalid@Name')  # Sanitized to 'Invalid_Name' as par.Invalid_Name
ui.Knob(par_name='123invalid')  # Raises ValueError (invalid identifier)
ui.Knob(par_name='my_knob')     # Raises ValueError if 'my_knob' already exists
```

### 4. Output Controllers
Manage output controllers with `tc.output`.

- `add(name, default=0.0)`: Adds a controller if not declared.
- `set(name, value)`: Sets the controller value.

Note that `tc.output.add()` will not work inside `def onTick()`, `def onTriggerVoice()`, or `def onReleaseVoice()`. This is because output controllers must be declared during the script's initialization phase (e.g., inside `createDialog()` or at the module level outside any functions), as the host environment (FL Studio) sets up the parameter interface once at load time. Adding controllers dynamically during runtime callbacks may fail silently or cause errors, since the parameter interface is fixed after the script is loaded. Controllers are only added if `export` mode is 'bind' or 'custom' during UI creation (see Section 6). Manual `tc.output.add()` is for custom scenarios outside UI bindings.

**Code Example**:
```python
import TrapCode as tc
tc.output.add('MyOut', default=0.5)
tc.output.set('MyOut', 1.0)
```

**Edge Case**:
```python
tc.output.add('MyOut', default='invalid')  # Defaults to 0.0 (coerces to float)
tc.output.set('NonExistent', 1.0)  # May fail silently if not added
```

### 5. Exports (Batch Update and Proxies)
Bind UI controls to output controllers for automation. `tc.exports` handles batch updates and introspection, while proxies are per-control sinks.

- Modes: `None` (no export), `'bind'` (follows UI value), `'custom'` (manual set via `.export.val`).
- Updated automatically in `onTick()` via `tc.exports.update()`.

Call `tc.exports.update()` each tick to push values based on mode ('bind' pulls from UI, 'custom' from `.export.val`). Skips unchanged values to optimize.

In 'bind' mode, values are resolved by control type: Knobs as float, KnobInts as int (floated), Combos as index (floated), Checkboxes as 1.0/0.0, Texts as float(str(val).strip()) if numeric (uses .export_default, default 0.0, if conversion fails). Transient errors (e.g., non-numeric Text in 'bind') use fallback for Text or skip silently for others. If a wrapper is missing (e.g., due to rename), skips silently. Modes can be strings like 'Bind' (case-insensitive, stripped), or equivalents like 'off'/''/False for None. Invalid modes raise ValueError during creation.

**Introspecting Exports**: `exports_dict = tc.exports()` returns a dict keyed by `par_name` (or controller name if no `par_name`), with values like {'name': ..., 'mode': ..., 'val': ...}. Useful for debugging or dynamic logic.

**Code Example**:
```python
def createDialog():
    ui = tc.UI()
    ui.Knob(name='BoundKnob', export='bind')  # Binds to output controller
    ui.Knob(name='CustomKnob', export='custom')
    return ui.form

def onTick():
    tc.par.CustomKnob.export.val = 0.75  # Manual set for 'custom'
    # Alternatively: tc.par.CustomKnob.export = 0.75 (auto-coerces to float; raises if non-numeric)
    tc.exports.update()  # Call this in onTick() to push values
```

**Edge Case**:
```python
ui.Text(export='bind')  # In bind, non-numeric text skips push or uses export_default
tc.par.CustomKnob.export = 'invalid'  # Raises TypeError (must be numeric)
tc.exports.update()  # If exception in custom mode, skips silently (robustness fix)
```

### 6. UI Controls
Create and manage UI elements with factory methods. All support `name` (UI label), `par_name` (optional custom attribute name on `tc.par`, defaults to sanitized `name`), `export` (mode: None/'bind'/'custom', defaults to None), and `export_name` (optional custom output controller name, defaults to `par_name`). If mode is set, adds a controller via `tc.output.add()`.

For grouped controls, values are accessed internally using qualified keys like `"Group: Control"` to handle hierarchy correctly, but users interact via plain `par.par_name.val`.

#### Knob (Float Slider)
**Code Example**:
```python
ui.Knob(name='MyKnob', d=0.5, min=0, max=1, hint='Adjust me')
print(tc.par.MyKnob.val)  # Access value
```
Setting `.val` warns (with line number) if outside [min, max] and clamps; no warning on export pushes.

**Edge Case**:
```python
tc.par.MyKnob.val = 1.5  # Warns and clamps to 1
```

#### KnobInt (Integer Slider)
**Code Example**:
```python
ui.KnobInt(name='MyIntKnob', d=5, min=1, max=10)
tc.par.MyIntKnob.val = 7  # Sets value (checks int, warns on bounds)
```
Setting `.val` warns (with line number) if outside [min, max] and clamps; no warning on export pushes.

**Edge Case**:
```python
tc.par.MyIntKnob.val = 11  # Warns and clamps to 10
tc.par.MyIntKnob.val = 5.5 # Raises ValueError (must be int)
```

#### Checkbox (Toggle)
**Code Example**:
```python
ui.Checkbox(name='MyCheck', d=True, hint='Enable feature')
if tc.par.MyCheck.val:  # Boolean coercion
    print("Enabled")
```
Coerces to bool naturally; setting accepts any truthy/falsy value.

**Edge Case**:
```python
tc.par.MyCheck.val = 42  # Sets to True (truthy)
```

#### Combo (Dropdown Menu)
**Code Example**:
```python
ui.Combo(name='MyMenu', options=['A', 'B', 'C'], d=1)  # Default index 1 ('B')
tc.par.MyMenu.val = 0  # Set to index 0 ('A')
# Or set by label: tc.par.MyMenu.val = 'A' (raises if not in options)
print(tc.par.MyMenu.options[1])  # 'B'
```
Options is list of strings. Default `d` can be int (index, clamped to 0..len-1) or str (matching label, raises if not found). If options empty, defaults to 0; setting requires 0.

**Edge Case**:
```python
ui.Combo(options=[], d=0)  # Empty options, val always 0
tc.par.MyMenu.val = 'D'   # Raises ValueError (not in options)
tc.par.MyMenu.val = 3     # Raises ValueError (out of range)
```

#### Text (Input Field)
**Code Example**:
```python
ui.Text(name='MyText', d='Hello', export='bind', export_default=1.0)
tc.par.MyText.val = 'World'  # Set text
print(tc.par.MyText.val)  # 'World'
# Or change fallback: tc.par.MyText.export_default = 0.5
```
`.val` is always str. Coercion to float/int may raise if non-numeric (e.g., in arithmetic). In 'bind' mode, attempts float(str(val).strip()), falls back to .export_default (float, default 0.0) if fails. No min/max clamping; setting accepts any str. Unique property: `export_default` (settable float) - fallback for 'bind' on non-numeric input (after stripping spaces).

**Edge Case**:
```python
tc.par.MyText.val = '123'  # In bind, pushes 123.0
tc.par.MyText.val = 'abc'  # In bind, pushes export_default (e.g., 1.0)
tc.par.MyText.export_default = 'invalid'  # Raises ValueError (must float)
```

#### Surface (Embedded Control Surface)
Embed a Control Surface preset for custom UI elements like buttons, XY pads, and graphics.

**Setup**:
1. In VFX Script, click **Options arrow → Embed Surface Preset**
2. Select your Control Surface preset
3. Add `ui.Surface()` in `createDialog()`

**Code Example**:
```python
def createDialog():
    ui = tc.UI()
    ui.Knob(name='Speed', d=0.5)
    ui.Surface()  # embeds the Control Surface preset
    return ui.form

def onTick():
    # Access surface elements by name
    btn = tc.surface('mybtn')
    knob = tc.surface('myknob')
    
    print(btn.val)    # read value
    knob.val = 0.5    # set value (normalized 0-1)
```

**Pulse Helper** (available on Surface buttons and Checkboxes):
```python
def handleClick():
    print("Clicked!")

# Detect button press (Control Surface)
btn = tc.surface('mybtn')
btn.pulse(on_click=handleClick)

# Detect checkbox click (native UI)
tc.par.MyCheckbox.pulse(on_click=handleClick)
```

Pulse arguments:
- `on_click`: Optional callback, called once per click

**Change Detection** (available on all controls):
```python
def onTick():
    btn = tc.surface('mybtn')
    
    # Detect value changes (fires once per transition)
    if btn.changed():
        if btn.val:
            print("Turned on")
        else:
            print("Turned off")
    
    # Works on any control type
    if tc.par.MyKnob.changed():
        print(f"Knob moved to {tc.par.MyKnob.val}")
    
    if tc.par.MyCombo.changed():
        print(f"Selected option {tc.par.MyCombo.val}")
    
    # Optional callback receives (new_val, old_val)
    tc.par.MyCheck.changed(lambda new, old: print(f"{old} -> {new}"))
```

Change detection compares the current value to the previous check. Works regardless of FL Studio playback state.

**Note**: Surface presets are saved to `~/Documents/Image-Line/Presets/Plugin presets/Effects/Control Surface/`

### 7. Arithmetic and Coercion
Wrappers support math operations and coercion.

**Code Example**:
```python
print(tc.par.MyKnob + 0.5)  # Adds to value
if tc.par.MyCheck:  # Bool coercion
    value = int(tc.par.MyIntKnob) * 2  # Int coercion and mul
```
Works for numeric wrappers (Knob, KnobInt, Combo index, Checkbox 1.0/0.0). For Text, attempts float(str(val)) but raises on non-numeric (e.g., 'abc' + 1 fails). Comparisons (e.g., par.a == par.b) coerce both sides to float if possible.

**Edge Case**:
```python
tc.par.MyText + 1  # Raises if val non-numeric
tc.par.MyKnob == tc.par.MyIntKnob  # Coerces both to float for comparison
```

### 8. Grouping
Context manager for UI groups. Grouped controls use internal qualified keys (e.g., `"Settings: InnerKnob"`) for value get/set, but accessed via plain `par.par_name`.

**Code Example**:
```python
with ui.group('Settings'):
    ui.Knob('InnerKnob')
print(tc.par.InnerKnob.val)  # Works despite internal qualification
```

**Edge Case**:
```python
with ui.group('Nested'):
    with ui.group('Inner'):  # Nested groups not fully supported; uses innermost ('Inner')
        ui.Knob('Deep')
print(tc.par.Deep._form_key())  # 'Inner: Deep' (only innermost group used)
```

### 9. Parameter Filtering (`pars`)
Retrieve filtered lists or dicts of parameter wrappers. Defaults to list; use `as_dict=True` for dict (keyed by `par_name`).

Filters:
- `type`: str or list[str] (e.g., 'knob' or ['knob', 'checkbox']) to filter by control type (case-insensitive).
- `group`: Controls group filtering:
  - `'all'` (default, or omitted): Include all parameters, regardless of group.
  - `None`: Include only ungrouped parameters (no group assigned).
  - str: Include only parameters in that exact group (e.g., 'test').
  - list[str]: Include parameters in any of the listed groups (e.g., ['test', 'effects']).

Invalid `group` types raise ValueError. Type mapping: 'knob' -> Knob, etc.

**Code Example**:
```python
all_params = tc.pars()  # All parameters (group='all' implicitly)
ungrouped = tc.pars(group=None)  # Only ungrouped
grouped_test = tc.pars(group='test')  # Only in 'test'
multi_group = tc.pars(group=['a', 'b'])  # In 'a' or 'b'
knobs = tc.pars('knob')  # All knobs, any group
dict_view = tc.pars(as_dict=True)  # Dict {par_name: wrapper}
for p in tc.pars(group=None):
    print(p.val)  # Iterate ungrouped
```

**Edge Case**:
```python
tc.pars(group=[])  # Returns empty list (no matching groups)
tc.pars(group=123) # Raises ValueError (invalid type)
tc.pars(type='invalid')  # Returns empty (no matching type)
tc.pars(as_dict=True, group=None)  # Dict of ungrouped only
```

### 10. Groups Utility
`tc.groups()`: Returns sorted list of unique group names (excludes None).

**Code Example**:
```python
print(tc.groups())  # e.g., ['Settings', 'test']
```

**Edge Case**:
```python
# If no groups: [] (empty list)
```

Call `tc.exports.update()` in `onTick()` to push export values. Use unique `par_name` for attribute access. For full code, see TrapCode.py.
