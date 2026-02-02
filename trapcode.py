import flvfx as vfx
import re
import inspect

# -----------------------------
# Helpers
# -----------------------------
def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

def _norm_from_range(value, lo, hi):
    if hi == lo:
        return 0.0
    return _clamp((value - lo) / (hi - lo), 0.0, 1.0)

def _warn_clamp(name, value, lo, hi):
    if value < lo or value > hi:
        caller = inspect.stack()[2] if len(inspect.stack()) >= 3 else None
        where = f" (line {caller.lineno})" if caller else ""
        print(f"[TrapCode]{where} '{name}' value {value} outside [{lo}, {hi}] -> clamped")

# -----------------------------
# Debug System
# -----------------------------
_debug_enabled = False
_debug_level = 1

def _log(category: str, msg: str, level: int = 1):
    """
    Internal logging helper.
    
    Args:
        category: Log category for prefix (e.g., 'patterns', 'triggers')
        msg: Message to log
        level: Required debug level (1=important, 2=verbose)
    """
    if not _debug_enabled:
        return
    if level > _debug_level:
        return
    print(f"[TrapCode:{category}] {msg}")

def debug(enable=None, *, level=None):
    """
    Toggle or query debug logging.
    
    Args:
        enable: True to enable, False to disable, None to query
        level: Debug verbosity (1=important events, 2=verbose). Keyword-only.
    
    Returns:
        dict with 'enabled' and 'level' keys when querying (enable=None)
        None when setting
    
    Examples:
        tc.debug(True)            # Enable, level 1
        tc.debug(True, level=2)   # Enable, level 2 (verbose)
        tc.debug(False)           # Disable
        tc.debug()                # {'enabled': True, 'level': 2}
    """
    global _debug_enabled, _debug_level
    
    if enable is None:
        return {'enabled': _debug_enabled, 'level': _debug_level}
    
    _debug_enabled = bool(enable)
    if level is not None:
        _debug_level = int(level)
    
    if _debug_enabled:
        _log("debug", f"enabled (level={_debug_level})")

# -----------------------------
# Mixins
# -----------------------------
class PulseMixin:
    """Mixin for pulse detection on clickable controls."""
    def pulse(self, on_click=None):
        """
        Detect button/checkbox press and fire callback.
        
        Args:
            on_click: Optional callback function, called once per click
        
        Returns:
            True if control was clicked this tick, False otherwise
        """
        if self.val == 1:
            self.val = 0  # reset
            if on_click is not None:
                try:
                    on_click()
                except Exception as e:
                    print(f"[TrapCode] pulse on_click error: {e}")
            return True
        return False


class EdgeMixin:
    """Mixin for detecting value transitions on controls."""
    
    def changed(self, threshold=None, callback=None):
        """
        Detect value change since last check.
        
        Args:
            threshold: Minimum delta to trigger change (numeric controls only).
                       None or 0 means any change triggers. Ignored for non-numeric
                       types (Checkbox, Combo, Text).
            callback: Optional callback(new_val, old_val) on change
        
        Returns:
            True if value changed, False otherwise
        
        Note:
            All changed() calls on a control share the same baseline. When any
            call detects a change, the baseline updates. If checking the same
            control with different thresholds, be aware they interact.
        """
        current = self.val
        prev = getattr(self, '_edge_prev', None)
        
        # First call: initialize, no change
        if prev is None:
            self._edge_prev = current
            return False
        
        # Determine if change occurred
        if threshold and isinstance(current, (int, float)) and isinstance(prev, (int, float)):
            # Threshold mode: compare absolute delta
            did_change = abs(current - prev) >= threshold
        else:
            # Default: any change
            did_change = current != prev
        
        if did_change:
            self._edge_prev = current
            if callback is not None:
                try:
                    callback(current, prev)
                except Exception as e:
                    print(f"[TrapCode] changed callback error: {e}")
        return did_change

# -----------------------------
# MIDI voice helper
# -----------------------------
class MIDI(vfx.Voice):
    parentVoice = None
    def __init__(self, incomingVoice):
        super().__init__(incomingVoice)
        self.parentVoice = incomingVoice

# -----------------------------
# Public parameter namespace
# -----------------------------
class Par: pass
par = Par()

# -----------------------------
# Output controllers
# -----------------------------
class Output:
    def __init__(self):
        self._declared = set()

    def add(self, name, default=0.0):
        if name not in self._declared:
            vfx.addOutputController(name, float(default))
            self._declared.add(name)

    def set(self, name, value):
        vfx.setOutputController(name, float(value))

output = Output()

# -----------------------------
# Export proxy (per-control, sink-only)
# -----------------------------
class _Export:
    __slots__ = ("name", "mode", "val", "_last_sent")

    # mode: None | "bind" | "custom"
    def __init__(self, name, mode=None, val=0.0):
        self.name = name
        self.mode = mode
        self.val = float(val)
        self._last_sent = None  # change detector to avoid redundant sets

    # sink semantics: no numeric coercion methods here (no __float__/__int__/__bool__/__index__)
    def __repr__(self):
        return f"<Export name={self.name} mode={self.mode} val={self.val}>"

# Registry of all exports
_exports = []  # list[_Export]

def _coerce_export_mode(m):
    if m is None:
        return None
    if isinstance(m, str):
        s = m.strip().lower()
        if s in ("bind", "custom"):
            return s
        if s in ("none", "off", "false", ""):
            return None
    raise ValueError("export must be None, 'bind', or 'custom'")

def update_exports():
    """
    Push exports each tick:
      - mode == 'bind'   => send the UI value (raw)
      - mode == 'custom' => send export.val
      - mode == None     => skip
    No normalization/clamping here.
    """
    for ex in _exports:
        if ex.mode is None:
            continue
        try:
            if ex.mode == "custom":
                value = float(ex.val)
            else:  # 'bind'
                w = _export_wrappers.get(ex.name)
                if w is None:
                    # If wrapper lost (rename?), skip silently
                    continue
                # Resolve raw UI value by type
                if hasattr(w, "min") and hasattr(w, "max"):      # Knob/KnobInt
                    value = float(w)
                elif hasattr(w, "options"):                       # Combo -> index
                    value = float(int(w))
                elif isinstance(w, UI.CheckboxWrapper):           # Checkbox -> 1.0/0.0
                    value = 1.0 if bool(w) else 0.0
                elif isinstance(w, UI.TextWrapper):               # Text -> float(text) if possible
                    value = float(str(w.val))
                else:
                    value = float(w)
        except Exception:
            # non-numeric text or transient error -> skip this tick
            continue

        if ex._last_sent is None or value != ex._last_sent:
            output.set(ex.name, value)
            ex._last_sent = value

# Map controller name -> wrapper (for 'bind' mode)
_export_wrappers = {}  # {ctrl_name: wrapper}

# -----------------------------
# Base wrapper (coercion + arithmetic)
# -----------------------------
class BaseWrapper:
    _read_only_attrs = []

    def __setattr__(self, key, value):
        if key in self._read_only_attrs:
            raise ValueError(f"{key} cannot be changed after creation.")
        super().__setattr__(key, value)

    # ---- access to underlying .val ----
    def _coerce_val(self):
        if hasattr(self, "val"):
            return self.val
        raise TypeError(f"{self.__class__.__name__} cannot be coerced to a value")

    # numeric/boolean coercion for UI wrappers
    def __float__(self): return float(self._coerce_val())
    def __int__(self):   return int(self._coerce_val())
    def __bool__(self):  return bool(self._coerce_val())
    def __index__(self): return int(self._coerce_val())

    # Basic arithmetic so expressions like par.knob * 2 just work
    def _num(self): return float(self._coerce_val())
    def _coerce_other(self, other):
        return float(other._coerce_val()) if isinstance(other, BaseWrapper) else other

    def __add__(self, other):      return self._num() + self._coerce_other(other)
    def __radd__(self, other):     return self._coerce_other(other) + self._num()
    def __sub__(self, other):      return self._num() - self._coerce_other(other)
    def __rsub__(self, other):     return self._coerce_other(other) - self._num()
    def __mul__(self, other):      return self._num() * self._coerce_other(other)
    def __rmul__(self, other):     return self._coerce_other(other) * self._num()
    def __truediv__(self, other):  return self._num() / self._coerce_other(other)
    def __rtruediv__(self, other): return self._coerce_other(other) / self._num()
    def __pow__(self, other):      return self._num() ** self._coerce_other(other)
    def __rpow__(self, other):     return self._coerce_other(other) ** self._num()
    def __neg__(self):             return -self._num()
    def __pos__(self):             return +self._num()
    def __abs__(self):             return abs(self._num())
    
    # --- Comparisons: allow par.knob > 0.5, par.a == par.b, etc. ---
    def _cmp_other(self, other):
        return other._coerce_val() if isinstance(other, BaseWrapper) else other

    def __eq__(self, other):
        try:
            return float(self._coerce_val()) == float(self._cmp_other(other))
        except Exception:
            return NotImplemented

    def __ne__(self, other):
        try:
            return float(self._coerce_val()) != float(self._cmp_other(other))
        except Exception:
            return NotImplemented

    def __lt__(self, other):
        try:
            return float(self._coerce_val()) < float(self._cmp_other(other))
        except Exception:
            return NotImplemented

    def __le__(self, other):
        try:
            return float(self._coerce_val()) <= float(self._cmp_other(other))
        except Exception:
            return NotImplemented

    def __gt__(self, other):
        try:
            return float(self._coerce_val()) > float(self._cmp_other(other))
        except Exception:
            return NotImplemented

    def __ge__(self, other):
        try:
            return float(self._coerce_val()) >= float(self._cmp_other(other))
        except Exception:
            return NotImplemented


    def __repr__(self):
        name = getattr(self, "name", "?")
        try:
            value = self._coerce_val()
        except Exception:
            value = "?"
        return f"<{self.__class__.__name__} {name}={value}>"

# -----------------------------
# UI
# -----------------------------
class UI:
    _instance = None  # keep idempotent across reloads

    def __init__(self, msg='WE MAKING IT OUT THE TRAP'):
        if UI._instance is not None:
            self.form = UI._instance.form
            return
        self.form = vfx.ScriptDialog('', msg)
        UI._instance = self

    # ---- tiny context manager for grouping
    def group(self, title):
        ui = self
        class _Group:
            def __enter__(self_inner): ui.form.addGroup(title)
            def __exit__(self_inner, exc_type, exc, tb): ui.form.endGroup()
        return _Group()

    # ------------- Controls
    class KnobWrapper(BaseWrapper, EdgeMixin):
        _read_only_attrs = ['name', 'default', 'min', 'max', 'hint']
        def __init__(self, form, name='Knob', d=0, min=0, max=1, hint=''):
            self._form = form
            object.__setattr__(self, 'name', name)
            object.__setattr__(self, 'default', d)
            object.__setattr__(self, 'min', min)
            object.__setattr__(self, 'max', max)
            object.__setattr__(self, 'hint', hint)
            form.addInputKnob(name, d, min, max, hint=hint)
        @property
        def val(self):
            try:
                return vfx.context.form.getInputValue(self.name)
            except AttributeError:
                return self.default
        @val.setter
        def val(self, value):
            _warn_clamp(self.name, value, self.min, self.max)
            t = _norm_from_range(value, self.min, self.max)
            try:
                vfx.context.form.setNormalizedValue(self.name, t)
            except AttributeError:
                pass
        def __str__(self): return str(self.val)

    class KnobIntWrapper(BaseWrapper, EdgeMixin):
        _read_only_attrs = ['name', 'default', 'min', 'max', 'hint']
        def __init__(self, form, name='KnobInt', d=0, min=0, max=1, hint=''):
            self._form = form
            object.__setattr__(self, 'name', name)
            object.__setattr__(self, 'default', int(d))
            object.__setattr__(self, 'min', int(min))
            object.__setattr__(self, 'max', int(max))
            object.__setattr__(self, 'hint', hint)
            form.addInputKnobInt(name, d, min, max, hint=hint)
        @property
        def val(self):
            try:
                return int(vfx.context.form.getInputValue(self.name))
            except (AttributeError, TypeError, ValueError):
                return int(self.default)
        @val.setter
        def val(self, value):
            if not isinstance(value, int):
                raise ValueError(f"Parameter '{self.name}' must be int.")
            _warn_clamp(self.name, value, self.min, self.max)
            t = _norm_from_range(value, self.min, self.max)
            try:
                vfx.context.form.setNormalizedValue(self.name, t)
            except AttributeError:
                pass
        def __str__(self): return str(self.val)

    class CheckboxWrapper(BaseWrapper, PulseMixin, EdgeMixin):
        _read_only_attrs = ['name', 'default', 'hint']
        def __init__(self, form, name='Checkbox', default=False, hint=''):
            self._form = form
            object.__setattr__(self, 'name', name)
            object.__setattr__(self, 'default', bool(default))
            object.__setattr__(self, 'hint', hint)
            form.addInputCheckbox(name, 1 if default else 0, hint)
        @property
        def val(self):
            try:
                return bool(vfx.context.form.getInputValue(self.name))
            except AttributeError:
                return bool(self.default)
        @val.setter
        def val(self, value):
            try:
                vfx.context.form.setNormalizedValue(self.name, 1 if bool(value) else 0)
            except AttributeError:
                pass
        def __str__(self): return str(self.val)

    class ComboWrapper(BaseWrapper, EdgeMixin):
        _read_only_attrs = ['name', 'options', 'default', 'hint']
        def __init__(self, form, name='Combo', options=None, d=0, hint=''):
            self._form = form
            options = options or []
            object.__setattr__(self, 'name', name)
            object.__setattr__(self, 'options', options)
            object.__setattr__(self, 'hint', hint)
            if isinstance(d, str):
                try:
                    d = options.index(d)
                except ValueError:
                    raise ValueError(f"Default '{d}' not in options {options}")
            if not isinstance(d, int):
                raise TypeError("Default must be int (index) or matching str")
            d = _clamp(d, 0, max(0, len(options) - 1))
            object.__setattr__(self, 'default', d)
            form.addInputCombo(name, options, d, hint)
        @property
        def val(self):
            try:
                return int(vfx.context.form.getInputValue(self.name))
            except (AttributeError, TypeError, ValueError):
                return int(self.default)
        @val.setter
        def val(self, value):
            if isinstance(value, str):
                try:
                    value = self.options.index(value)
                except ValueError:
                    raise ValueError(f"'{value}' not in {self.options}")
            if not isinstance(value, int) or not (0 <= value < max(1, len(self.options))):
                raise ValueError(f"Invalid index {value} for combo '{self.name}' (0..{len(self.options)-1}).")
            normalized = value / (len(self.options) - 1) if len(self.options) > 1 else 0.0
            try:
                vfx.context.form.setNormalizedValue(self.name, normalized)
            except AttributeError:
                pass
        def __str__(self): return str(self.val)

    class TextWrapper(BaseWrapper, EdgeMixin):
        _read_only_attrs = ['name', 'default']
        def __init__(self, form, name='Text', default=''):
            self._form = form
            object.__setattr__(self, 'name', name)
            object.__setattr__(self, 'default', default)
            form.addInputText(name, default)
        @property
        def val(self):
            try:
                return vfx.context.form.getInputValue(self.name)
            except AttributeError:
                return self.default
        @val.setter
        def val(self, value):
            try:
                if hasattr(vfx.context.form, "setInputValue"):
                    vfx.context.form.setInputValue(self.name, str(value))
            except AttributeError:
                pass
        def __str__(self): return str(self.val)

    # ------------- Factory + registration (+ export modes)
    def _create_control(self, wrapper_class, name, par_name=None, *, export=None, export_name=None, **kwargs):
        """
        export:       None | 'bind' | 'custom'
            None   -> no export controller (default)
            'bind' -> export follows UI value
            'custom' -> export.val is pushed; you set it manually
        export_name:  optional controller name (defaults to par_name)
        """
        wrapper = wrapper_class(self.form, name, **kwargs)

        # par_name rules
        if par_name is None:
            par_name = re.sub(r'\W+', '_', name).strip('_')
        if not par_name or not par_name.isidentifier():
            raise ValueError(f"Invalid par_name '{par_name}'. Use a valid Python identifier.")
        if hasattr(par, par_name):
            raise ValueError(f"Parameter '{par_name}' already exists; names must be unique.")
        setattr(par, par_name, wrapper)

        # attach export proxy
        ctrl_name = export_name or par_name
        mode = _coerce_export_mode(export)
        default_raw = getattr(wrapper, "default", 0.0)
        ex = _Export(ctrl_name, mode=mode, val=float(default_raw))
        object.__setattr__(wrapper, "export", ex)

        # sugar: assigning a number to wrapper.export sets export.val
        def _get_export(_self): return ex
        def _set_export(_self, value):
            try:
                ex.val = float(value)
            except Exception:
                raise TypeError("Assign a numeric value or use .export.val")
        wrapper.__class__.export = property(_get_export, _set_export)

        # create controller if exporting (bind/custom), and track wrapper for 'bind'
        if mode is not None:
            output.add(ctrl_name, default_raw)
            _export_wrappers[ctrl_name] = wrapper
        _exports.append(ex)

        return wrapper

    def Knob(self, name='Knob', par_name=None, d=0, min=0, max=1, hint='', *, export=None, export_name=None):
        return self._create_control(self.KnobWrapper, name, par_name,
                                    export=export, export_name=export_name,
                                    d=d, min=min, max=max, hint=hint)

    def KnobInt(self, name='KnobInt', par_name=None, d=0, min=0, max=1, hint='', *, export=None, export_name=None):
        return self._create_control(self.KnobIntWrapper, name, par_name,
                                    export=export, export_name=export_name,
                                    d=d, min=min, max=max, hint=hint)

    def Checkbox(self, name='Checkbox', par_name=None, default=False, hint='', *, export=None, export_name=None):
        return self._create_control(self.CheckboxWrapper, name, par_name,
                                    export=export, export_name=export_name,
                                    default=default, hint=hint)

    def Combo(self, name='Combo', par_name=None, options=None, d=0, hint='', *, export=None, export_name=None):
        return self._create_control(self.ComboWrapper, name, par_name,
                                    export=export, export_name=export_name,
                                    options=options or [], d=d, hint=hint)

    def Text(self, name='Text', par_name=None, default='', *, export=None, export_name=None):
        return self._create_control(self.TextWrapper, name, par_name,
                                    export=export, export_name=export_name,
                                    default=default)

    def Surface(self):
        """Embed a Control Surface preset. Must be set via Options arrow in VFX Script."""
        self.form.addInputSurface('')


# -----------------------------
# Control Surface element access
# -----------------------------
class SurfaceWrapper(PulseMixin, EdgeMixin):
    """Wrapper for accessing Control Surface elements by name."""
    def __init__(self, name):
        self._name = name

    @property
    def val(self):
        try:
            return vfx.context.form.getInputValue(self._name)
        except AttributeError:
            return 0

    @val.setter
    def val(self, value):
        try:
            vfx.context.form.setNormalizedValue(self._name, float(value))
        except AttributeError:
            pass

    def __repr__(self):
        return f"<SurfaceWrapper {self._name}={self.val}>"


_surface_cache = {}  # {name: SurfaceWrapper}

def surface(name):
    """Access a Control Surface element by name. Returns a wrapper with .val property."""
    if name not in _surface_cache:
        _surface_cache[name] = SurfaceWrapper(name)
    return _surface_cache[name]


# -----------------------------
# Voice Triggering (Phase 1)
# -----------------------------

# Module-level state
_trigger_queue = []      # Pending TriggerState objects
_active_voices = []      # (voice, release_tick) tuples
_voice_parents = {}      # voice -> parent voice mapping (for programmatic notes)
_update_called = False   # For reminder message
_reminder_shown = False  # One-time reminder flag
_internal_tick = 0       # Internal tick counter (increments each update() call)


def get_parent(voice):
    """
    Get the parent voice for a given voice.
    
    Works with both:
    - MIDI class instances (have .parentVoice attribute)
    - Programmatic notes created with parent= parameter
    
    Returns None if no parent (ghost notes).
    """
    # Check MIDI class instances first
    if hasattr(voice, 'parentVoice'):
        return voice.parentVoice
    # Check programmatic note tracking
    return _voice_parents.get(voice)


def beats_to_ticks(beats):
    """Convert beats to ticks. 1 beat = 1 quarter note."""
    return beats * vfx.context.PPQ


class TriggerState:
    """Tracks a pending or active trigger."""
    def __init__(self, source, note_length, parent=None):
        self.source = source           # Note instance
        self.note_length = note_length # Length in beats
        self.parent = parent           # Optional parent voice (for MIDI-tied notes)
        self.pending = True            # Waiting to fire


# Alias mapping for Note parameters (alias -> canonical name)
_NOTE_ALIASES = {
    # MIDI note number
    'm': 'm', 'midi': 'm',
    # Velocity
    'v': 'v', 'velocity': 'v',
    # Length
    'l': 'l', 'length': 'l',
    # Pan
    'pan': 'pan', 'p': 'pan',
    # Output port
    'output': 'output', 'o': 'output',
    # Filter cutoff / Mod X
    'fcut': 'fcut', 'fc': 'fcut', 'x': 'fcut',
    # Filter resonance / Mod Y
    'fres': 'fres', 'fr': 'fres', 'y': 'fres',
    # Fine pitch
    'finePitch': 'finePitch', 'fp': 'finePitch',
}

# Default values for Note parameters
_NOTE_DEFAULTS = {
    'm': 60, 'v': 100, 'l': 1, 'pan': 0,
    'output': 0, 'fcut': 0, 'fres': 0, 'finePitch': 0,
}


def _resolve_note_kwargs(kwargs):
    """Resolve aliased kwargs to canonical parameter names."""
    resolved = {}
    for key, value in kwargs.items():
        canonical = _NOTE_ALIASES.get(key)
        if canonical is None:
            raise TypeError(f"Note() got unexpected keyword argument '{key}'")
        if canonical in resolved:
            raise TypeError(f"Note() got multiple values for parameter '{canonical}'")
        resolved[canonical] = value
    return resolved


class Note:
    """
    Programmatic note for triggering voices.
    
    Args (aliases in parentheses):
        m (midi): MIDI note number (0-127)
        v (velocity): Velocity (0-127), default 100
        l (length): Length in beats, default 1 (quarter note)
        pan (p): Stereo pan (-1 left, 0 center, 1 right), default 0
        output (o): Voice output port (0-based), default 0
        fcut (fc, x): Mod X / filter cutoff (-1 to 1), default 0
        fres (fr, y): Mod Y / filter resonance (-1 to 1), default 0
        finePitch (fp): Microtonal pitch offset (fractional notes), default 0
    """
    def __init__(self, **kwargs):
        # Resolve aliases to canonical names
        params = _resolve_note_kwargs(kwargs)
        
        # Apply defaults for missing params
        for key, default in _NOTE_DEFAULTS.items():
            if key not in params:
                params[key] = default
        
        # Set canonical attributes with validation
        self.m = _clamp(params['m'], 0, 127)
        self.v = _clamp(params['v'], 0, 127)
        self.l = params['l']
        self.pan = _clamp(params['pan'], -1, 1)
        self.output = int(params['output'])
        self.fcut = _clamp(params['fcut'], -1, 1)
        self.fres = _clamp(params['fres'], -1, 1)
        self.finePitch = params['finePitch']
        self._voices = []  # Active voices for this Note
    
    # Property aliases for attribute access
    @property
    def midi(self): return self.m
    @midi.setter
    def midi(self, val): self.m = _clamp(val, 0, 127)
    
    @property
    def velocity(self): return self.v
    @velocity.setter
    def velocity(self, val): self.v = _clamp(val, 0, 127)
    
    @property
    def length(self): return self.l
    @length.setter
    def length(self, val): self.l = val
    
    @property
    def p(self): return self.pan
    @p.setter
    def p(self, val): self.pan = _clamp(val, -1, 1)
    
    @property
    def o(self): return self.output
    @o.setter
    def o(self, val): self.output = int(val)
    
    @property
    def fc(self): return self.fcut
    @fc.setter
    def fc(self, val): self.fcut = _clamp(val, -1, 1)
    
    @property
    def x(self): return self.fcut
    @x.setter
    def x(self, val): self.fcut = _clamp(val, -1, 1)
    
    @property
    def fr(self): return self.fres
    @fr.setter
    def fr(self, val): self.fres = _clamp(val, -1, 1)
    
    @property
    def y(self): return self.fres
    @y.setter
    def y(self, val): self.fres = _clamp(val, -1, 1)
    
    @property
    def fp(self): return self.finePitch
    @fp.setter
    def fp(self, val): self.finePitch = val
    
    def trigger(self, l=None, cut=True, parent=None):
        """
        Queue a one-shot trigger.
        
        Args:
            l: Optional length override in beats
            cut: If True (default), release previous voices before triggering
            parent: Optional parent voice (ties note to incoming MIDI for release)
        
        Returns:
            self for chaining
        """
        # Cut previous voices if requested
        if cut:
            for voice in self._voices:
                voice.release()
            self._voices.clear()
        
        length = l if l is not None else self.l
        state = TriggerState(source=self, note_length=length, parent=parent)
        _trigger_queue.append(state)
        _check_update_reminder()
        return self


def _check_update_reminder():
    """Show one-time reminder if update() hasn't been called yet."""
    global _reminder_shown
    if not _update_called and not _reminder_shown:
        print("[TrapCode] Reminder: Call tc.update() in onTick() for triggers to fire")
        _reminder_shown = True


def _fire_note(state, current_tick):
    """Create and trigger a voice from a TriggerState."""
    src = state.source
    voice = vfx.Voice()
    # Track parent relationship (if any) in module dict
    if state.parent is not None:
        _voice_parents[voice] = state.parent
    voice.note = src.m
    voice.velocity = src.v / 127.0  # Normalize MIDI 0-127 to 0-1
    voice.length = int(beats_to_ticks(state.note_length))  # FL auto-releases after this
    voice.pan = src.pan
    voice.output = src.output
    voice.fcut = src.fcut
    voice.fres = src.fres
    voice.finePitch = src.finePitch
    voice.trigger()
    
    # Track on Note instance for cut behavior
    state.source._voices.append(voice)
    
    # Track globally for cleanup
    release_tick = current_tick + beats_to_ticks(state.note_length)
    _active_voices.append((state.source, voice, release_tick))


def _get_current_tick():
    """Get the current tick for pattern timing.
    
    Uses internal tick counter which increments each update() call.
    This ensures patterns advance even when FL Studio is stopped.
    """
    return _internal_tick


def _base_update():
    """
    Process triggers and releases (internal). Called by update().
    
    Fires any pending triggers. Voices auto-release via v.length.
    """
    global _update_called
    _update_called = True
    current_tick = _internal_tick
    
    # Fire pending triggers
    for state in _trigger_queue[:]:
        if state.pending:
            _fire_note(state, current_tick)
            state.pending = False
            _trigger_queue.remove(state)
    
    # Clean up expired voice tracking (FL auto-releases via v.length)
    for source, voice, release_tick in _active_voices[:]:
        if current_tick >= int(release_tick):
            # Remove from Note's voice list
            if voice in source._voices:
                source._voices.remove(voice)
            # Clean up parent tracking
            _voice_parents.pop(voice, None)
            _active_voices.remove((source, voice, release_tick))


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                         PATTERN ENGINE (Strudel)                          ║
# ║  Mini-notation parser and temporal pattern system inspired by Strudel/    ║
# ║  TidalCycles. See: https://strudel.cc                                     ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

# Minimal Fraction implementation to avoid FL Studio crash on recompile.
# The standard library's fractions module triggers _decimal C extension loading,
# which corrupts memory when VFX Script reinitializes the Python interpreter.
from math import gcd as _gcd

class Fraction:
    """Minimal rational number for pattern timing. Avoids stdlib fractions/decimal."""
    __slots__ = ('_n', '_d')
    
    def __init__(self, numerator=0, denominator=1):
        if isinstance(numerator, Fraction):
            self._n, self._d = numerator._n, numerator._d
            return
        if isinstance(numerator, float):
            # Convert float to fraction (limited precision)
            if numerator == int(numerator):
                numerator = int(numerator)
            else:
                # Use 1000000 as denominator for float conversion
                self._n, self._d = int(numerator * 1000000), 1000000
                self._reduce()
                return
        if isinstance(numerator, str):
            if '/' in numerator:
                n, d = numerator.split('/')
                numerator, denominator = int(n), int(d)
            else:
                numerator = int(float(numerator))
        n, d = int(numerator), int(denominator)
        if d == 0:
            raise ZeroDivisionError("Fraction denominator cannot be zero")
        if d < 0:
            n, d = -n, -d
        g = _gcd(abs(n), d) if n else 1
        self._n, self._d = n // g, d // g
    
    def _reduce(self):
        g = _gcd(abs(self._n), self._d) if self._n else 1
        self._n, self._d = self._n // g, self._d // g
    
    @property
    def numerator(self): return self._n
    @property
    def denominator(self): return self._d
    
    def __repr__(self): return f"Fraction({self._n}, {self._d})"
    def __str__(self): return f"{self._n}/{self._d}" if self._d != 1 else str(self._n)
    def __float__(self): return self._n / self._d
    def __int__(self): return int(self._n // self._d)
    def __hash__(self): return hash((self._n, self._d))
    
    def __eq__(self, other):
        if isinstance(other, Fraction): return self._n * other._d == other._n * self._d
        if isinstance(other, (int, float)): return float(self) == float(other)
        return NotImplemented
    def __lt__(self, other):
        if isinstance(other, Fraction): return self._n * other._d < other._n * self._d
        if isinstance(other, (int, float)): return float(self) < float(other)
        return NotImplemented
    def __le__(self, other): return self == other or self < other
    def __gt__(self, other):
        if isinstance(other, Fraction): return self._n * other._d > other._n * self._d
        if isinstance(other, (int, float)): return float(self) > float(other)
        return NotImplemented
    def __ge__(self, other): return self == other or self > other
    
    def __add__(self, other):
        if isinstance(other, int): other = Fraction(other)
        elif isinstance(other, float): other = Fraction(other)
        if isinstance(other, Fraction):
            return Fraction(self._n * other._d + other._n * self._d, self._d * other._d)
        return NotImplemented
    def __radd__(self, other): return self.__add__(other)
    
    def __sub__(self, other):
        if isinstance(other, int): other = Fraction(other)
        elif isinstance(other, float): other = Fraction(other)
        if isinstance(other, Fraction):
            return Fraction(self._n * other._d - other._n * self._d, self._d * other._d)
        return NotImplemented
    def __rsub__(self, other): return Fraction(other).__sub__(self)
    
    def __mul__(self, other):
        if isinstance(other, int): other = Fraction(other)
        elif isinstance(other, float): other = Fraction(other)
        if isinstance(other, Fraction):
            return Fraction(self._n * other._n, self._d * other._d)
        return NotImplemented
    def __rmul__(self, other): return self.__mul__(other)
    
    def __truediv__(self, other):
        if isinstance(other, int): other = Fraction(other)
        elif isinstance(other, float): other = Fraction(other)
        if isinstance(other, Fraction):
            return Fraction(self._n * other._d, self._d * other._n)
        return NotImplemented
    def __rtruediv__(self, other): return Fraction(other).__truediv__(self)
    
    def __neg__(self): return Fraction(-self._n, self._d)
    def __pos__(self): return Fraction(self._n, self._d)
    def __abs__(self): return Fraction(abs(self._n), self._d)

from dataclasses import dataclass
from typing import NamedTuple, Iterator, Optional, Any, Callable, List, Tuple

# -----------------------------
# Type Aliases
# -----------------------------
Time = Fraction
Arc = Tuple[Time, Time]

# -----------------------------
# Event (Hap)
# -----------------------------
@dataclass
class Event:
    """
    A musical event with temporal context.
    
    Attributes:
        value: The musical value (MIDI note number, or None for rest)
        whole: The original metric span (logical event duration)
        part: The actual active time window (intersection with query arc)
    """
    value: Any
    whole: Optional[Arc]
    part: Arc
    
    def has_onset(self) -> bool:
        """
        Returns True if this event's onset is within the query arc.
        
        Critical for VFX Script: only trigger notes when has_onset() is True,
        otherwise you'll fire the same note multiple times across tick boundaries.
        """
        return self.whole is not None and self.whole[0] == self.part[0]


# -----------------------------
# Time Conversion
# -----------------------------
def _ticks_to_time(ticks: int, ppq: int, cycle_beats: int) -> Time:
    """Convert FL Studio ticks to cycle time (Fraction)."""
    ticks_per_cycle = ppq * cycle_beats
    return Fraction(ticks, ticks_per_cycle)


def _time_to_ticks(t: Time, ppq: int, cycle_beats: int) -> int:
    """Convert cycle time to FL Studio ticks."""
    ticks_per_cycle = ppq * cycle_beats
    return int(t * ticks_per_cycle)


def _tick_arc(tick: int, ppq: int, cycle_beats: int) -> Arc:
    """Return a 1-tick-wide query arc for the given tick."""
    ticks_per_cycle = ppq * cycle_beats
    return (Fraction(tick, ticks_per_cycle), Fraction(tick + 1, ticks_per_cycle))


# -----------------------------
# Tokenizer
# -----------------------------
class Token(NamedTuple):
    type: str
    value: str
    pos: int


_TOKEN_SPEC = [
    ('NUMBER',  r'-?\d+(\.\d+)?'),  # Negative or positive, optional decimal
    ('REST',    r'[~\-]'),          # ~ or standalone - (only matches if NUMBER didn't)
    ('LBRACK',  r'\['),
    ('RBRACK',  r'\]'),
    ('LANGLE',  r'<'),
    ('RANGLE',  r'>'),
    ('STAR',    r'\*'),
    ('SLASH',   r'/'),
    ('WS',      r'\s+'),
]

_TOK_REGEX = '|'.join(f'(?P<{name}>{pattern})' for name, pattern in _TOKEN_SPEC)
_IGNORE = {'WS'}


def _tokenize(code: str) -> Iterator[Token]:
    """Tokenize mini-notation string into tokens."""
    for mo in re.finditer(_TOK_REGEX, code):
        kind = mo.lastgroup
        if kind not in _IGNORE:
            yield Token(kind, mo.group(), mo.start())


# -----------------------------
# Pattern Class
# -----------------------------
class Pattern:
    """
    A temporal pattern that maps time arcs to events.
    
    Patterns are functions of time: query(arc) returns events within that arc.
    """
    def __init__(self, query_fn: Callable[[Arc], List[Event]]):
        self._query_fn = query_fn
        self._running = False
        self._start_tick = 0
    
    def query(self, arc: Arc) -> List[Event]:
        """Query events within the given time arc."""
        return self._query_fn(arc)
    
    def __call__(self, arc: Arc) -> List[Event]:
        """Alias for query()."""
        return self.query(arc)
    
    @staticmethod
    def pure(value) -> 'Pattern':
        """
        Constant pattern: value repeats every cycle.
        
        Handles multi-cycle queries correctly by returning one event per cycle.
        """
        def query(arc: Arc) -> List[Event]:
            events = []
            cycle_start = int(arc[0])
            cycle_end = int(arc[1]) if arc[1] == int(arc[1]) else int(arc[1]) + 1
            
            for c in range(cycle_start, cycle_end):
                whole = (Fraction(c), Fraction(c + 1))
                part_start = max(arc[0], whole[0])
                part_end = min(arc[1], whole[1])
                if part_start < part_end:
                    events.append(Event(value, whole, (part_start, part_end)))
            return events
        return Pattern(query)
    
    @staticmethod
    def silence() -> 'Pattern':
        """Empty pattern that produces no events."""
        return Pattern(lambda arc: [])
    
    def fast(self, factor) -> 'Pattern':
        """
        Speed up pattern by factor. Used by * in mini notation.
        
        Compresses time: the pattern repeats `factor` times per cycle.
        """
        factor = Fraction(factor)
        if factor == 0:
            return Pattern.silence()
        
        def query(arc: Arc) -> List[Event]:
            # Query inner pattern with compressed arc
            inner_arc = (arc[0] * factor, arc[1] * factor)
            events = self.query(inner_arc)
            
            # Transform both whole and part back to outer time
            result = []
            for e in events:
                new_whole = (e.whole[0] / factor, e.whole[1] / factor) if e.whole else None
                new_part = (e.part[0] / factor, e.part[1] / factor)
                result.append(Event(e.value, new_whole, new_part))
            return result
        
        return Pattern(query)
    
    def slow(self, factor) -> 'Pattern':
        """
        Slow down pattern by factor. Used by / in mini notation.
        
        Expands time: the pattern spans `factor` cycles.
        """
        return self.fast(Fraction(1) / Fraction(factor))
    
    # --- Playback control ---
    def start(self, current_tick: int = None):
        """Start the pattern. Optionally provide current tick, else uses 0."""
        self._running = True
        self._start_tick = current_tick if current_tick is not None else 0
        return self
    
    def stop(self):
        """Stop the pattern."""
        self._running = False
        return self
    
    def reset(self, current_tick: int = None):
        """Reset and restart the pattern."""
        self._start_tick = current_tick if current_tick is not None else 0
        return self
    
    def tick(self, current_tick: int, ppq: int, cycle_beats: int = 4) -> List[Event]:
        """
        Query events that should fire on this tick.
        
        Args:
            current_tick: Current FL Studio tick count
            ppq: Pulses per quarter note
            cycle_beats: Beats per cycle (default 4 = one bar in 4/4)
        
        Returns:
            List of events with onset in this tick window (rests excluded)
        """
        if not self._running:
            return []
        
        # Relative tick since pattern started
        rel_tick = current_tick - self._start_tick
        if rel_tick < 0:
            return []
        
        # Convert to 1-tick-wide arc in cycle time
        arc = _tick_arc(rel_tick, ppq, cycle_beats)
        events = self.query(arc)
        
        # Only fire events where onset falls in this window, skip rests
        return [e for e in events if e.has_onset() and e.value is not None]


# -----------------------------
# Pattern Combinators
# -----------------------------
def _sequence(*patterns) -> Pattern:
    """
    Concatenate patterns, each taking equal time within one cycle.
    
    This is the core subdivision operation. "a b c" means:
    - a occupies 0 - 1/3
    - b occupies 1/3 - 2/3  
    - c occupies 2/3 - 1
    """
    n = len(patterns)
    if n == 0:
        return Pattern.silence()
    if n == 1:
        return patterns[0]
    
    def query(arc: Arc) -> List[Event]:
        results = []
        for i, pat in enumerate(patterns):
            # This child occupies [i/n, (i+1)/n] of each cycle
            child_start = Fraction(i, n)
            child_end = Fraction(i + 1, n)
            
            # For each cycle the arc touches, check if it overlaps this child's slot
            cycle_start = int(arc[0])
            cycle_end = int(arc[1]) if arc[1] == int(arc[1]) else int(arc[1]) + 1
            
            for c in range(cycle_start, cycle_end):
                # This child's absolute time slot in cycle c
                slot_start = Fraction(c) + child_start
                slot_end = Fraction(c) + child_end
                
                # Intersect with query arc
                query_start = max(arc[0], slot_start)
                query_end = min(arc[1], slot_end)
                
                if query_start < query_end:
                    # Transform query to child's local time (0-1 within its slot)
                    local_start = (query_start - slot_start) * n + Fraction(c)
                    local_end = (query_end - slot_start) * n + Fraction(c)
                    
                    # Query child pattern
                    child_events = pat.query((local_start, local_end))
                    
                    # Transform results back to parent time
                    for e in child_events:
                        new_whole = None
                        if e.whole:
                            w_start = slot_start + (e.whole[0] - Fraction(c)) / n
                            w_end = slot_start + (e.whole[1] - Fraction(c)) / n
                            new_whole = (w_start, w_end)
                        p_start = slot_start + (e.part[0] - Fraction(c)) / n
                        p_end = slot_start + (e.part[1] - Fraction(c)) / n
                        new_part = (p_start, p_end)
                        results.append(Event(e.value, new_whole, new_part))
        
        return results
    
    return Pattern(query)


# Alias
_fastcat = _sequence


def _slowcat(*patterns) -> Pattern:
    """
    Cycle alternation: select one child per cycle based on cycle number.
    
    <a b c> plays a on cycle 0, b on cycle 1, c on cycle 2, a on cycle 3, etc.
    """
    n = len(patterns)
    if n == 0:
        return Pattern.silence()
    if n == 1:
        return patterns[0]
    
    def query(arc: Arc) -> List[Event]:
        cycle_num = int(arc[0])  # floor of start time
        pat_index = cycle_num % n
        return patterns[pat_index].query(arc)
    
    return Pattern(query)


# -----------------------------
# Mini-Notation Parser
# -----------------------------
class _MiniParser:
    """Recursive descent parser for mini-notation."""
    
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
    
    def peek(self) -> Optional[Token]:
        """Look at current token without consuming."""
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None
    
    def consume(self, expected_type: str = None) -> Token:
        """Consume and return current token."""
        tok = self.peek()
        if tok is None:
            raise SyntaxError("Unexpected end of input")
        if expected_type and tok.type != expected_type:
            raise SyntaxError(f"Expected {expected_type}, got {tok.type} at position {tok.pos}")
        self.pos += 1
        return tok
    
    def parse(self) -> Pattern:
        """Parse the full pattern."""
        return self.parse_layer()
    
    def parse_layer(self) -> Pattern:
        """
        Parse a sequence of elements.
        layer ::= element+
        """
        elements = []
        while self.peek() and self.peek().type not in ('RBRACK', 'RANGLE'):
            elements.append(self.parse_element())
        
        if not elements:
            return Pattern.silence()
        if len(elements) == 1:
            return elements[0]
        
        return _sequence(*elements)
    
    def parse_element(self) -> Pattern:
        """
        Parse an atom with optional modifiers.
        element ::= atom (modifier)*
        """
        pat = self.parse_atom()
        
        # Consume modifiers
        while self.peek() and self.peek().type in ('STAR', 'SLASH'):
            tok = self.consume()
            # Next token must be a number
            num_tok = self.consume('NUMBER')
            num = Fraction(num_tok.value)
            
            if tok.type == 'STAR':
                pat = pat.fast(num)
            elif tok.type == 'SLASH':
                pat = pat.slow(num)
        
        return pat
    
    def parse_atom(self) -> Pattern:
        """
        Parse a primitive value or grouped pattern.
        atom ::= NUMBER | REST | '[' pattern ']' | '<' pattern+ '>'
        """
        tok = self.peek()
        if tok is None:
            return Pattern.silence()
        
        if tok.type == 'NUMBER':
            self.consume()
            # Parse as int if possible, else float
            if '.' in tok.value:
                return Pattern.pure(float(tok.value))
            else:
                return Pattern.pure(int(tok.value))
        
        elif tok.type == 'REST':
            self.consume()
            return Pattern.pure(None)  # Rest
        
        elif tok.type == 'LBRACK':
            # Subdivision: [a b c]
            self.consume('LBRACK')
            inner = self.parse_layer()
            self.consume('RBRACK')
            return inner
        
        elif tok.type == 'LANGLE':
            # Alternation: <a b c>
            self.consume('LANGLE')
            alternatives = []
            while self.peek() and self.peek().type != 'RANGLE':
                alternatives.append(self.parse_element())
            self.consume('RANGLE')
            
            if not alternatives:
                return Pattern.silence()
            return _slowcat(*alternatives)
        
        else:
            # Unknown token, skip
            return Pattern.silence()


def _parse_mini(code: str) -> Pattern:
    """Parse a mini-notation string into a Pattern."""
    tokens = list(_tokenize(code))
    if not tokens:
        return Pattern.silence()
    parser = _MiniParser(tokens)
    return parser.parse()


# -----------------------------
# Pattern Registry (for update loop)
# -----------------------------
_active_patterns = []  # List of (pattern, root, cycle_beats) tuples


def _update_patterns():
    """Update all active patterns. Called from tc.update()."""
    try:
        ppq = vfx.context.PPQ
    except AttributeError:
        return  # Not in VFX context
    
    # Use internal tick counter for consistent timing
    current_tick = _get_current_tick()
    
    for pattern, root_raw, cycle_beats_raw in _active_patterns[:]:
        # Resolve dynamic parameters each tick
        root = _resolve_dynamic(root_raw)
        cycle_beats = _resolve_dynamic(cycle_beats_raw)
        try:
            cycle_beats = max(1, int(cycle_beats))
        except (TypeError, ValueError):
            cycle_beats = 4
        
        events = pattern.tick(current_tick, ppq, cycle_beats)
        for e in events:
            # Create and trigger note
            note_val = root + e.value if e.value is not None else None
            if note_val is not None:
                # Calculate duration from event's whole span
                if e.whole:
                    duration_time = e.whole[1] - e.whole[0]
                    duration_beats = float(duration_time) * cycle_beats
                else:
                    duration_beats = 1  # Default to 1 beat
                
                note = Note(m=int(note_val), l=duration_beats)
                note.trigger(cut=False)


# -----------------------------
# Public API: tc.n() / tc.note()
# -----------------------------
def note(pattern_str: str, c = 4, root = 60) -> Pattern:
    """
    Create a pattern from mini-notation.
    
    Args:
        pattern_str: Mini-notation string (e.g., "0 3 5 7")
        c: Cycle duration in beats (default 4 = one bar).
           Can be a static value OR a UI wrapper for dynamic updates.
        root: Root note (default 60 = C4). Values in pattern are offsets from root.
              Can be a static value OR a UI wrapper for dynamic updates.
    
    Returns:
        Pattern object. Call .start() to begin playback.
    
    Example:
        pattern = tc.n("0 3 5 7", c=4, root=60)  # Static values
        pattern = tc.n("0 3 5 7", c=tc.par.CycleKnob, root=tc.par.RootKnob)  # Dynamic
        pattern.start()
        
        def onTick():
            tc.update()
    """
    pat = _parse_mini(pattern_str)
    _active_patterns.append((pat, root, c))
    return pat


# Alias
n = note


# -----------------------------
# MIDI.n() Method
# -----------------------------
# Store pattern data on MIDI instances
_midi_patterns = {}  # voice_id -> (pattern, cycle_beats, root, midi_wrapper)


def _resolve_dynamic(value):
    """Resolve a value that may be static or dynamic (wrapper/callable)."""
    if callable(value):
        return value()
    if hasattr(value, 'val'):
        return value.val
    return value


def _midi_n(self, pattern_str: str, c = 4) -> Pattern:
    """
    Create a pattern from mini-notation, using this voice's note as root.
    
    Args:
        pattern_str: Mini-notation string (e.g., "0 3 5 7")
        c: Cycle duration in beats (default 4 = one bar).
           Can be a static value OR a UI wrapper (e.g., tc.par.MyKnob) for dynamic updates.
    
    Returns:
        Pattern object (auto-started, tied to this voice's lifecycle)
    
    Example:
        def onTriggerVoice(incomingVoice):
            midi = tc.MIDI(incomingVoice)
            midi.n("0 3 5 7", c=4)  # Static: 4 beats per cycle
            midi.n("0 3 5 7", c=tc.par.MyKnob)  # Dynamic: follows knob value
    """
    pat = _parse_mini(pattern_str)
    root = self.note  # Use incoming MIDI note as root
    
    # Register pattern with this MIDI wrapper (self is the triggered voice)
    # Store c as-is (may be int, float, wrapper, or callable) for dynamic resolution
    voice_id = id(self.parentVoice)
    _midi_patterns[voice_id] = (pat, c, root, self)
    
    # Auto-start with internal tick counter
    # Pattern starts at current tick; update() processes patterns before incrementing
    pat.start(_get_current_tick())
    
    return pat


# Attach method to MIDI class
MIDI.n = _midi_n




def _update_midi_patterns():
    """Update MIDI-bound patterns. Called from tc.update()."""
    try:
        ppq = vfx.context.PPQ
    except AttributeError:
        return
    
    # Use internal tick counter for consistent timing
    current_tick = _get_current_tick()
    
    for voice_id in list(_midi_patterns.keys()):
        pat, cycle_beats_raw, root, midi_wrapper = _midi_patterns[voice_id]
        
        # Resolve dynamic cycle_beats each tick
        cycle_beats = _resolve_dynamic(cycle_beats_raw)
        try:
            cycle_beats = max(1, int(cycle_beats))  # Ensure positive integer
        except (TypeError, ValueError):
            cycle_beats = 4  # Fallback to default
        
        # Check if the pattern is still running
        if not pat._running:
            del _midi_patterns[voice_id]
            continue
        
        # Debug: show timing info
        rel_tick = current_tick - pat._start_tick
        ticks_per_cycle = ppq * cycle_beats
        arc_start = Fraction(rel_tick, ticks_per_cycle)
        arc_end = Fraction(rel_tick + 1, ticks_per_cycle)
        
        _log("patterns", f"tick={current_tick} rel={rel_tick} start_tick={pat._start_tick} arc=({float(arc_start):.4f}, {float(arc_end):.4f}) c={cycle_beats}", level=2)
        
        # Process events
        events = pat.tick(current_tick, ppq, cycle_beats)
        
        for e in events:
            _log("patterns", f"EVENT value={e.value} whole=({float(e.whole[0]):.4f}, {float(e.whole[1]):.4f}) part=({float(e.part[0]):.4f}, {float(e.part[1]):.4f}) has_onset={e.has_onset()}", level=2)
        
        for e in events:
            note_val = root + e.value if e.value is not None else None
            if note_val is not None:
                # Calculate duration from event's whole span
                if e.whole:
                    duration_time = e.whole[1] - e.whole[0]
                    duration_beats = float(duration_time) * cycle_beats
                else:
                    duration_beats = 1
                
                _log("patterns", f"TRIGGER note={note_val} duration={duration_beats} beats", level=1)
                
                note_obj = Note(m=int(note_val), l=duration_beats)
                note_obj.trigger(cut=False, parent=midi_wrapper.parentVoice)


def stop_patterns_for_voice(parent_voice):
    """
    Stop all patterns associated with a parent voice.
    Call this in onReleaseVoice() to clean up MIDI-bound patterns.
    
    Args:
        parent_voice: The incoming voice that was released
    """
    voice_id = id(parent_voice)
    if voice_id in _midi_patterns:
        pat, _, _, _ = _midi_patterns[voice_id]
        pat.stop()
        del _midi_patterns[voice_id]


def update():
    """
    Process triggers, releases, and patterns. Call in onTick().
    
    Order of operations:
    1. Process pending triggers and releases
    2. Update standalone patterns (tc.n)
    3. Update MIDI-bound patterns (midi.n)
    4. Increment tick counter (so patterns created this frame start at tick 0)
    """
    global _internal_tick
    
    _base_update()
    _update_patterns()
    _update_midi_patterns()
    
    # Increment tick AFTER all processing, so patterns created this frame start at tick 0
    _internal_tick += 1


# Initialization message
print("[TrapCode] Initialized")
