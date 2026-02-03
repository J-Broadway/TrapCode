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
                # Handle decimal strings like "0.5" -> Fraction(1, 2)
                f = float(numerator)
                if f != int(f):
                    # Convert decimal to fraction: find power of 10 needed
                    s = numerator.rstrip('0')  # Remove trailing zeros
                    if '.' in s:
                        decimal_places = len(s) - s.index('.') - 1
                        scale = 10 ** decimal_places
                        numerator = int(round(f * scale))
                        denominator = scale
                    else:
                        numerator = int(f)
                else:
                    numerator = int(f)
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
# AbsoluteNote Marker
# -----------------------------
@dataclass(frozen=True)
class AbsoluteNote:
    """
    Marker for absolute MIDI values (from note names).
    
    Distinguishes note names (e.g., 'c4' -> AbsoluteNote(60)) from
    numeric offsets (e.g., '0' -> int) at trigger time.
    """
    midi: int


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
# Note Name Parsing
# -----------------------------

# Chroma values for each note letter (C = 0)
_CHROMAS = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}

# Accidental semitone offsets (# and s = sharp, b and f = flat)
_ACCIDENTALS = {'#': 1, 'b': -1, 's': 1, 'f': -1}


def _tokenize_note(note: str) -> tuple:
    """
    Parse note string into (letter, accidentals, octave).
    
    Returns:
        (letter: str, accidentals: str, octave: int or None)
    
    Examples:
        'c4' -> ('c', '', 4)
        'eb5' -> ('e', 'b', 5)
        'f##3' -> ('f', '##', 3)
        'c' -> ('c', '', None)
    """
    if not note or not isinstance(note, str):
        return (None, '', None)
    
    # Match: letter + accidentals + optional octave
    match = re.match(r'^([a-gA-G])([#bsf]*)(-?\d*)$', note)
    if not match:
        return (None, '', None)
    
    letter = match.group(1).lower()
    accidentals = match.group(2)
    octave_str = match.group(3)
    octave = int(octave_str) if octave_str else None
    
    return (letter, accidentals, octave)


def _get_accidental_offset(accidentals: str) -> int:
    """Sum of semitone offsets for accidentals string."""
    return sum(_ACCIDENTALS.get(c, 0) for c in accidentals)


def _note_to_midi(note: str, default_octave: int = 3) -> int:
    """
    Convert note name to MIDI number.
    
    Args:
        note: Note string like 'c4', 'eb5', 'f##'
        default_octave: Octave to use if not specified (default 3)
    
    Returns:
        MIDI note number (0-127)
    
    Examples:
        'c4' -> 60
        'c#4' -> 61
        'db4' -> 61
        'c5' -> 72
        'c' -> 48 (octave 3 default)
    
    Raises:
        ValueError if note format is invalid
    """
    letter, accidentals, octave = _tokenize_note(note)
    
    if letter is None:
        raise ValueError(f"Invalid note format: '{note}'")
    
    if octave is None:
        octave = default_octave
    
    chroma = _CHROMAS[letter]
    offset = _get_accidental_offset(accidentals)
    
    # MIDI formula: (octave + 1) * 12 + chroma + offset
    midi = (octave + 1) * 12 + chroma + offset
    
    # Clamp to valid MIDI range
    return _clamp(midi, 0, 127)


def _is_note(value: str) -> bool:
    """Check if string is a valid note name."""
    if not isinstance(value, str):
        return False
    letter, _, _ = _tokenize_note(value)
    return letter is not None


# -----------------------------
# Tokenizer
# -----------------------------
class Token(NamedTuple):
    type: str
    value: str
    pos: int


_TOKEN_SPEC = [
    ('NUMBER',  r'-?\d+(\.\d+)?'),  # Negative or positive, optional decimal
    ('NOTE',    r'[a-gA-G][#bsf]*-?\d*'),  # Note name: c, c#, eb4, f##5
    ('REST',    r'[~\-]'),          # ~ or standalone - (only matches if NUMBER didn't)
    ('LBRACK',  r'\['),
    ('RBRACK',  r'\]'),
    ('LANGLE',  r'<'),
    ('RANGLE',  r'>'),
    ('STAR',    r'\*'),
    ('SLASH',   r'/'),
    ('AT',      r'@'),              # Weighting
    ('BANG',    r'!'),              # Replicate
    ('QUESTION', r'\?'),            # Degrade
    ('COMMA',   r','),              # Polyphony
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
# Bus System (Pattern State Access)
# -----------------------------
import time as _time

class PatternChain:
    """
    Universal container for pattern-based operations with state exposure.
    
    Wraps pattern operations, maintains state dictionary, and provides
    change detection for cross-scope access via the bus system.
    """
    
    def __init__(self, midi_wrapper=None, mute=False):
        self._midi = midi_wrapper
        self._mute = mute
        self._running = True
        self._pattern = None              # The underlying Pattern object
        self._patterns = {}               # method_name -> Pattern (for chained modifiers)
        self._updaters = []               # List of update functions
        self._prev_state = {}             # For change detection
        self._root = 60                   # Root note for offset calculation
        self._cycle_beats = 4             # Cycle duration in beats
        
        # Bus registration info
        self._bus_name = None
        self._bus_voice_id = None
        
        # Parent voice tracking (for lifecycle management)
        self._parent_voice = None
        
        # Base state dictionary
        self._state = {
            'notes': [],
            'n': [],
            'step': 0,
            'phase': 0.0,
            'cycle': 0,
            'onset': False,
            'mute': mute,
            'parentVoice': None,    # Parent voice (incoming MIDI voice)
            'note': 60.0,
            'finePitch': 0.0,
            'velocity': 0.8,
            'pan': 0.0,
            'length': 0,
            'output': 0,
            'fcut': 0.0,
            'fres': 0.0,
        }
    
    def _register(self, keys: dict, updater=None):
        """Register state keys and optional per-tick updater."""
        self._state.update(keys)
        if updater:
            self._updaters.append(updater)
    
    # --- Dunder methods for Pythonic access ---
    
    def __getitem__(self, key: str):
        """Direct key access: chain['n'] instead of chain.dict()['n']."""
        return self._state.get(key)
    
    def __contains__(self, key: str) -> bool:
        """Membership test: 'n' in chain."""
        return key in self._state
    
    def __bool__(self) -> bool:
        """Truthy if onset occurred this tick."""
        return self._state.get('onset', False)
    
    def __repr__(self) -> str:
        """Useful debug output."""
        notes = self._state.get('notes', [])
        step = self._state.get('step', 0)
        return f"<PatternChain step={step} notes={notes}>"
    
    # --- State access methods ---
    
    def dict(self) -> dict:
        """Return snapshot of current state."""
        return self._state.copy()
    
    def changed(self, key: str = None) -> bool:
        """
        Detect state changes.
        
        Args:
            key: Specific key to check, or None for onset detection
        
        Returns:
            True if change occurred this tick
        """
        if key is None:
            return self._state.get('onset', False)
        
        current = self._state.get(key)
        previous = self._prev_state.get(key)
        return current != previous
    
    def tick(self, current_tick: int, ppq: int, cycle_beats: float):
        """
        Update state for this tick. Called by tc.update().
        
        Args:
            current_tick: Current tick count
            ppq: Pulses per quarter note
            cycle_beats: Beats per cycle
        """
        if not self._running or self._pattern is None:
            return
        
        # Store previous state for change detection
        self._prev_state = self._state.copy()
        
        # Reset onset flag
        self._state['onset'] = False
        
        # Get events from underlying pattern
        events = self._pattern.tick(current_tick, ppq, cycle_beats)
        
        # Update phase/cycle/step from pattern's internal state
        phase = self._pattern._phase
        phase_float = float(phase)
        self._state['phase'] = phase_float - int(phase_float)  # Fractional part [0.0, 1.0)
        self._state['cycle'] = int(phase_float)
        
        # Process events
        if events:
            self._state['onset'] = True
            
            # Collect values and durations from events
            n_values = []
            notes = []
            durations = []
            for e in events:
                if isinstance(e.value, AbsoluteNote):
                    n_values.append(e.value.midi)
                    notes.append(e.value.midi)
                elif isinstance(e.value, (int, float)):
                    n_values.append(e.value)
                    notes.append(int(self._root + e.value))
                else:
                    continue  # Skip rests or unknown values
                
                # Calculate duration from event's whole span (same as _update_midi_patterns)
                if e.whole:
                    duration_time = e.whole[1] - e.whole[0]
                    duration_beats = float(duration_time) * cycle_beats
                else:
                    duration_beats = 0.1  # Short default for continuous patterns
                durations.append(max(0.01, duration_beats))
            
            self._state['n'] = n_values
            self._state['notes'] = notes
            self._state['_durations'] = durations  # Internal: per-note durations
            
            # Calculate step from pattern position
            # Using the first event's whole span to determine step
            if events[0].whole:
                whole_start = float(events[0].whole[0])
                step_frac = whole_start - int(whole_start)  # Fractional part [0.0, 1.0)
                # Count unique onset positions (not total events, which includes stacked notes)
                unique_onsets = len(set(float(e.whole[0]) for e in events if e.whole))
                # Estimate steps per cycle from events with different onset times
                self._state['step'] = int(step_frac * max(1, unique_onsets))
        
        # Run all registered updaters (for chained modifiers like .v(), .pan())
        for updater in self._updaters:
            updater(current_tick, ppq, cycle_beats)
        
        # Fire notes if not muted and onset occurred
        if not self._mute and self._state['onset']:
            self._fire_notes()
    
    def _get_steps_per_cycle(self) -> int:
        """
        Estimate number of unique onset positions per cycle.
        
        For chords like [c4,e4,g4], multiple notes share the same onset,
        so we count unique onset times rather than total events.
        """
        try:
            events = self._pattern.query((Fraction(0), Fraction(1)))
            if not events:
                return 1
            # Count unique onset positions (whole[0] values)
            unique_onsets = set()
            for e in events:
                if e.whole:
                    unique_onsets.add(float(e.whole[0]))
            return max(len(unique_onsets), 1)
        except:
            return 1
    
    def _fire_notes(self):
        """Fire MIDI notes for current state. Skipped when mute=True."""
        notes = self._state['notes']
        durations = self._state.get('_durations', [])
        
        for i, midi_note in enumerate(notes):
            # Use per-note duration from event's whole span, or fallback
            if i < len(durations):
                duration_beats = durations[i]
            else:
                # Fallback: estimate from cycle_beats (shouldn't happen normally)
                duration_beats = max(0.01, self._cycle_beats / 4)
            
            # Allow explicit length override from state
            if self._state['length']:
                duration_beats = self._state['length']
            
            note_obj = Note(
                m=int(midi_note),
                l=duration_beats,
                v=int(self._state['velocity'] * 127),
                p=self._state['pan'],
            )
            
            # Get parent voice for triggering
            parent = None
            if self._midi and hasattr(self._midi, 'parentVoice'):
                parent = self._midi.parentVoice
            elif self._parent_voice:
                parent = self._parent_voice
            
            if parent:
                note_obj.trigger(cut=False, parent=parent)
    
    # --- Lifecycle ---
    
    def stop(self):
        """
        Stop the pattern and remove from bus.
        
        For standalone patterns (tc.n without parent), this is required
        for cleanup. Voice-scoped patterns are cleaned up automatically.
        """
        self._running = False
        
        # Stop the underlying pattern
        if self._pattern:
            self._pattern.stop()
        
        # Remove from bus if registered
        if self._bus_name and self._bus_voice_id:
            bus_reg = bus(self._bus_name)
            if self._bus_voice_id in bus_reg:
                dict.__delitem__(bus_reg, self._bus_voice_id)
        
        # Remove from chain registry
        _unregister_chain(self)


class BusRegistry(dict):
    """
    Dict-like container for PatternChains keyed by voice ID.
    
    Provides iteration, index access, and history tracking for released voices.
    """
    
    def __init__(self):
        super().__init__()
        self._history = []            # List of (release_tick, [chains]) tuples
        self.history_limit = 10       # Max batches to keep
        self._voice_counter = 0       # For unique IDs
        self.name = ''                # Set when registered via tc.bus()
    
    # --- Dunder methods for Pythonic access ---
    
    def __iter__(self):
        """Iterate PatternChains directly (not voice IDs)."""
        return iter(self.values())
    
    def __getitem__(self, key):
        """Access by index (int) or voice_id (tuple)."""
        if isinstance(key, int):
            # tc.bus('clock')[0] — get by index
            values = list(self.values())
            if not values or key >= len(values) or key < -len(values):
                raise IndexError(f"Bus index {key} out of range")
            return values[key]
        return super().__getitem__(key)  # voice_id tuple access
    
    def __bool__(self):
        """Truthy if has active voices."""
        return len(self) > 0
    
    def __repr__(self):
        """Useful debug output."""
        return f"<BusRegistry '{self.name}': {len(self)} voices>"
    
    # --- Core methods ---
    
    def _generate_id(self) -> tuple:
        """Generate unique voice ID: (timestamp, counter)."""
        self._voice_counter += 1
        return (_time.time(), self._voice_counter)
    
    def register(self, chain: 'PatternChain') -> tuple:
        """Add chain to registry, return voice ID."""
        voice_id = self._generate_id()
        dict.__setitem__(self, voice_id, chain)  # Use dict method to avoid override issues
        return voice_id
    
    def release(self, voice_id: tuple, release_tick: int):
        """Move chain to history on voice release."""
        if voice_id not in self:
            return
        
        chain = self.pop(voice_id)
        
        # Group by release tick
        if self._history and self._history[0][0] == release_tick:
            self._history[0][1].append(chain)
        else:
            self._history.insert(0, (release_tick, [chain]))
        
        # Trim history
        while len(self._history) > self.history_limit:
            self._history.pop()
    
    def newest(self) -> 'PatternChain | None':
        """Get most recently triggered chain."""
        if not self:
            return None
        return dict.__getitem__(self, max(self.keys()))
    
    def oldest(self) -> 'PatternChain | None':
        """Get earliest triggered chain."""
        if not self:
            return None
        return dict.__getitem__(self, min(self.keys()))
    
    def last(self, n: int = 0) -> list:
        """Get chains from nth-most-recent release batch."""
        if n >= len(self._history):
            return []
        return self._history[n][1]
    
    def history(self) -> list:
        """Get all release batches (newest first)."""
        return [batch[1] for batch in self._history]


class BusContainer(dict):
    """Dict-like container for all buses. Accessed via tc.buses."""
    pass


# Module-level bus storage
_buses = BusContainer()

# Public API: direct access to all buses
buses = _buses


def bus(name: str) -> BusRegistry:
    """
    Get or create bus registry by name. Auto-creates if missing.
    
    Args:
        name: Bus name (e.g., 'melody', 'clock')
    
    Returns:
        BusRegistry for the given name
    """
    if name not in _buses:
        _buses[name] = BusRegistry()
        _buses[name].name = name
    return _buses[name]


# Chain registry: tracks all active PatternChains for update loop
# Maps: id(chain) -> (chain, cycle_beats, root, parent_voice_id)
_chain_registry = {}

# Voice-to-chains mapping for cleanup
# Maps: id(parent_voice) -> [(bus_name, bus_voice_id, chain_id), ...]
_voice_chain_map = {}


def _register_chain(parent_voice, chain: PatternChain, cycle_beats, root: int):
    """Register a PatternChain for the update loop."""
    chain_id = id(chain)
    parent_id = id(parent_voice) if parent_voice else None
    
    _chain_registry[chain_id] = (chain, cycle_beats, root, parent_id)
    
    # Track for voice cleanup
    if parent_id:
        if parent_id not in _voice_chain_map:
            _voice_chain_map[parent_id] = []
        _voice_chain_map[parent_id].append((chain._bus_name, chain._bus_voice_id, chain_id))


def _unregister_chain(chain: PatternChain):
    """Remove a PatternChain from the update loop."""
    chain_id = id(chain)
    if chain_id in _chain_registry:
        del _chain_registry[chain_id]


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
        # Phase tracking for cycle-latched updates
        self._phase = Fraction(0)      # Current position in cycle-time (0.0 to ∞)
        self._last_tick = None         # Last tick we processed
        self._latched_cycle_beats = None  # Cycle beats latched at cycle start
        self._pending_cycle_beats = None  # Next cycle beats (applied at cycle boundary)
    
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
    
    def repeatCycles(self, n) -> 'Pattern':
        """
        Repeat each cycle of the pattern n times.
        
        Unlike fast(), this doesn't compress time within each cycle.
        Instead, it repeats the entire cycle content n times before
        moving to the next cycle of the source pattern.
        
        For example, with a slowcat pattern <a b>:
        - repeatCycles(2) gives: a a b b a a b b ...
        - fast(2) gives: a b a b a b ... (twice as fast)
        
        This is used by the replicate (!) operator.
        """
        n = int(n)
        if n <= 0:
            return Pattern.silence()
        if n == 1:
            return self
        
        outer_self = self
        
        def query(arc: Arc) -> List[Event]:
            # Get the current cycle number
            cycle = int(arc[0])
            # Calculate which source cycle this maps to
            source_cycle = cycle // n
            # Calculate the offset within the repetition group
            delta = Fraction(cycle - source_cycle * n)
            
            # Shift the query back to the source cycle
            shifted_arc = (arc[0] - delta, arc[1] - delta)
            
            # Query the source pattern
            events = outer_self.query(shifted_arc)
            
            # Shift the results forward to the current cycle
            result = []
            for e in events:
                new_whole = None
                if e.whole:
                    new_whole = (e.whole[0] + delta, e.whole[1] + delta)
                new_part = (e.part[0] + delta, e.part[1] + delta)
                result.append(Event(e.value, new_whole, new_part))
            
            return result
        
        return Pattern(query)
    
    def degrade(self, probability: float = 0.5) -> 'Pattern':
        """
        Randomly drop events with given probability of keeping them.
        
        Args:
            probability: Chance of keeping the event (0.0 to 1.0)
        
        Uses true randomness for natural variation. Each event is independently
        evaluated with the given probability.
        """
        import random
        outer_self = self
        
        def query(arc: Arc) -> List[Event]:
            events = outer_self.query(arc)
            result = []
            for e in events:
                # Use true randomness for natural musical variation
                if random.random() < probability:
                    result.append(e)
            return result
        
        return Pattern(query)
    
    # --- Playback control ---
    def start(self, current_tick: int = None):
        """Start the pattern. Optionally provide current tick, else uses 0."""
        self._running = True
        self._start_tick = current_tick if current_tick is not None else 0
        self._phase = Fraction(0)
        self._last_tick = current_tick
        self._latched_cycle_beats = None  # Will be set on first tick()
        self._pending_cycle_beats = None
        return self
    
    def stop(self):
        """Stop the pattern."""
        self._running = False
        return self
    
    def reset(self, current_tick: int = None):
        """Reset and restart the pattern."""
        self._start_tick = current_tick if current_tick is not None else 0
        self._phase = Fraction(0)
        self._last_tick = current_tick
        self._latched_cycle_beats = None
        self._pending_cycle_beats = None
        return self
    
    def tick(self, current_tick: int, ppq: int, cycle_beats = 4) -> List[Event]:
        """
        Query events that should fire on this tick.
        
        Uses cycle-latched timing: cycle_beats changes only take effect at the
        start of each cycle. This prevents glitchy artifacts when automating
        the cycle parameter.
        
        Args:
            current_tick: Current FL Studio tick count
            ppq: Pulses per quarter note
            cycle_beats: Beats per cycle (default 4 = one bar in 4/4).
                         Changes are latched and applied at cycle boundaries.
        
        Returns:
            List of events with onset in this tick window (rests excluded)
        """
        if not self._running:
            return []
        
        # Clamp incoming cycle_beats to minimum
        cycle_beats = float(cycle_beats)
        if cycle_beats < 0.01:
            cycle_beats = 0.01
        
        # Snap to nearest integer if very close (fixes float precision from UI knobs)
        rounded = round(cycle_beats)
        if abs(cycle_beats - rounded) < 0.001:
            cycle_beats = float(rounded)
        
        # Handle first tick: latch initial cycle_beats
        if self._last_tick is None:
            self._last_tick = current_tick
            self._phase = Fraction(0)
            self._latched_cycle_beats = cycle_beats
            self._pending_cycle_beats = cycle_beats
        
        # Store pending value for next cycle boundary
        self._pending_cycle_beats = cycle_beats
        
        # Use latched value for this cycle (fallback to incoming if not yet latched)
        active_cycle_beats = self._latched_cycle_beats if self._latched_cycle_beats is not None else cycle_beats
        
        # Calculate phase increment using latched cycle_beats
        ticks_per_cycle = ppq * active_cycle_beats
        phase_increment = Fraction(1, int(ticks_per_cycle))
        
        # Check for cycle boundary BEFORE advancing phase
        phase_before = self._phase
        cycle_before = int(phase_before)
        
        # Advance phase
        ticks_elapsed = current_tick - self._last_tick
        if ticks_elapsed > 0:
            self._phase = self._phase + phase_increment * ticks_elapsed
            self._last_tick = current_tick
        
        # Check if we crossed a cycle boundary
        cycle_after = int(self._phase)
        if cycle_after > cycle_before:
            # Crossed into new cycle - latch the pending cycle_beats
            self._latched_cycle_beats = self._pending_cycle_beats
        
        # Query 1-phase-increment-wide arc at current phase
        arc_start = self._phase
        arc_end = self._phase + phase_increment
        
        events = self.query((arc_start, arc_end))
        
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


def _stack(*patterns) -> Pattern:
    """
    Layer patterns for simultaneous playback (polyphony).
    
    All patterns are queried with the same arc, results merged.
    "a, b" plays both a and b at the same time.
    """
    if not patterns:
        return Pattern.silence()
    if len(patterns) == 1:
        return patterns[0]
    
    def query(arc: Arc) -> List[Event]:
        results = []
        for pat in patterns:
            results.extend(pat.query(arc))
        return results
    
    return Pattern(query)


def _weighted_sequence(elements: List[Tuple[Pattern, int]]) -> Pattern:
    """
    Like _sequence(), but with weighted time allocation.
    
    Args:
        elements: List of (pattern, weight) tuples
    
    Example:
        "a@2 b" gives a 2/3 of the time, b 1/3
        "a b@3 c" gives a=1/5, b=3/5, c=1/5
    """
    if not elements:
        return Pattern.silence()
    
    total_weight = sum(w for _, w in elements)
    if total_weight == 0:
        return Pattern.silence()
    
    # Pre-calculate cumulative positions
    positions = []
    cumulative = Fraction(0)
    for pat, weight in elements:
        start = cumulative
        end = cumulative + Fraction(weight, total_weight)
        positions.append((pat, start, end))
        cumulative = end
    
    def query(arc: Arc) -> List[Event]:
        results = []
        cycle_start = int(arc[0])
        cycle_end = int(arc[1]) if arc[1] == int(arc[1]) else int(arc[1]) + 1
        
        for pat, child_start, child_end in positions:
            child_duration = child_end - child_start
            if child_duration == 0:
                continue  # Skip zero-weight elements
            
            for c in range(cycle_start, cycle_end):
                # This child's absolute time slot in cycle c
                slot_start = Fraction(c) + child_start
                slot_end = Fraction(c) + child_end
                
                # Intersect with query arc
                query_start = max(arc[0], slot_start)
                query_end = min(arc[1], slot_end)
                
                if query_start < query_end:
                    # Transform to child's local time (0-1 within its slot)
                    # Inverse of the slot mapping
                    scale = Fraction(1) / child_duration
                    local_start = (query_start - slot_start) * scale + Fraction(c)
                    local_end = (query_end - slot_start) * scale + Fraction(c)
                    
                    child_events = pat.query((local_start, local_end))
                    
                    # Transform results back to parent time
                    for e in child_events:
                        new_whole = None
                        if e.whole:
                            w_start = slot_start + (e.whole[0] - Fraction(c)) * child_duration
                            w_end = slot_start + (e.whole[1] - Fraction(c)) * child_duration
                            new_whole = (w_start, w_end)
                        p_start = slot_start + (e.part[0] - Fraction(c)) * child_duration
                        p_end = slot_start + (e.part[1] - Fraction(c)) * child_duration
                        new_part = (p_start, p_end)
                        results.append(Event(e.value, new_whole, new_part))
        
        return results
    
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
        """
        Parse the full pattern.
        pattern ::= layer (',' layer)*
        """
        layers = [self.parse_layer()]
        
        while self.peek() and self.peek().type == 'COMMA':
            self.consume('COMMA')
            layers.append(self.parse_layer())
        
        if len(layers) == 1:
            return layers[0]
        
        return _stack(*layers)
    
    def parse_layer(self) -> Pattern:
        """
        Parse a sequence of weighted elements.
        layer ::= element+
        """
        elements = []  # List of (pattern, weight) tuples
        while self.peek() and self.peek().type not in ('RBRACK', 'RANGLE', 'COMMA'):
            elements.append(self.parse_element())
        
        if not elements:
            return Pattern.silence()
        
        # Check if any element has non-default weight
        has_weights = any(w != 1 for _, w in elements)
        
        if has_weights:
            return _weighted_sequence(elements)
        else:
            # Use original sequence for efficiency (extract patterns from tuples)
            if len(elements) == 1:
                return elements[0][0]
            return _sequence(*[p for p, _ in elements])
    
    def parse_element(self) -> Tuple[Pattern, int]:
        """
        Parse an atom with optional modifiers, return (pattern, weight).
        element ::= atom (modifier)*
        """
        pat = self.parse_atom()
        weight = 1  # Default weight
        
        # Consume modifiers
        while self.peek() and self.peek().type in ('STAR', 'SLASH', 'AT', 'BANG', 'QUESTION'):
            tok = self.consume()
            
            if tok.type == 'QUESTION':
                # ? has optional probability argument
                if self.peek() and self.peek().type == 'NUMBER':
                    prob = float(self.consume().value)
                else:
                    prob = 0.5  # Default probability
                pat = pat.degrade(prob)
            else:
                # STAR, SLASH, AT, BANG all require a number
                num_tok = self.consume('NUMBER')
                
                if tok.type == 'STAR':
                    # *n accepts float for fractional speed
                    pat = pat.fast(Fraction(num_tok.value))
                elif tok.type == 'SLASH':
                    # /n accepts float for fractional slow
                    pat = pat.slow(Fraction(num_tok.value))
                elif tok.type == 'AT':
                    # @n weight must be int
                    weight = int(float(num_tok.value))
                elif tok.type == 'BANG':
                    # !n replication: repeat each cycle n times, then speed up
                    # This matches Strudel's behavior: pat._repeatCycles(n)._fast(n)
                    # ALSO sets weight so replicated element takes proportional time
                    # Example: "a!3 b" -> a takes 3/4 time, b takes 1/4
                    num = int(float(num_tok.value))
                    if num > 0:
                        pat = pat.repeatCycles(num).fast(num)
                        weight = num  # Replicated elements take proportional time
                    else:
                        pat = Pattern.silence()
                        weight = 0
        
        return (pat, weight)
    
    def parse_atom(self) -> Pattern:
        """
        Parse a primitive value or grouped pattern.
        atom ::= NUMBER | NOTE | REST | '[' pattern ']' | '<' pattern+ '>'
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
        
        elif tok.type == 'NOTE':
            self.consume()
            # Convert note name to MIDI, wrap in AbsoluteNote marker
            midi = _note_to_midi(tok.value)
            return Pattern.pure(AbsoluteNote(midi))
        
        elif tok.type == 'REST':
            self.consume()
            return Pattern.pure(None)  # Rest
        
        elif tok.type == 'LBRACK':
            # Subdivision: [a b c] (allow commas for polyphony inside)
            self.consume('LBRACK')
            inner = self.parse()
            self.consume('RBRACK')
            return inner
        
        elif tok.type == 'LANGLE':
            # Slowcat notation: <a b c> — distributes elements across cycles
            # Unlike [a b c] which subdivides within a cycle, <a b c> plays
            # a on cycle 0, b on cycle 1, c on cycle 2, then repeats
            #
            # Implementation: parse contents as weighted sequence, then slow
            # by total weight. This matches Strudel's polymeter_slowcat behavior.
            # 
            # Example: <a!2 b> → sequence with total weight 3, slowed by 3
            #   - Cycle 0: first 1/3 of sequence (a at 2x speed in 2/3 slot)
            #   - Cycle 1: middle 1/3 of sequence (rest of a)
            #   - Cycle 2: last 1/3 of sequence (b in 1/3 slot)
            self.consume('LANGLE')
            
            # Parse contents as weighted sequence (same as parse_layer)
            elements = []  # List of (pattern, weight) tuples
            while self.peek() and self.peek().type not in ('RANGLE', 'COMMA'):
                elements.append(self.parse_element())
            
            self.consume('RANGLE')
            
            if not elements:
                return Pattern.silence()
            
            # Calculate total weight
            total_weight = sum(w for _, w in elements)
            
            # Build the sequence (weighted if needed)
            has_weights = any(w != 1 for _, w in elements)
            if has_weights:
                inner = _weighted_sequence(elements)
            else:
                if len(elements) == 1:
                    inner = elements[0][0]
                else:
                    inner = _sequence(*[p for p, _ in elements])
            
            # Slow by total weight so it spans that many cycles
            if total_weight > 1:
                return inner.slow(total_weight)
            return inner
        
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
        # Resolve dynamic parameters each tick (allow fractional for smooth control)
        root = _resolve_dynamic(root_raw)
        cycle_beats = _resolve_dynamic(cycle_beats_raw)
        try:
            cycle_beats = float(cycle_beats)
            if cycle_beats <= 0:
                cycle_beats = 0.01  # Minimum: very fast
        except (TypeError, ValueError):
            cycle_beats = 4
        
        events = pattern.tick(current_tick, ppq, cycle_beats)
        
        # Use the latched cycle_beats for duration calculation
        active_cycle_beats = pattern._latched_cycle_beats or cycle_beats
        
        for e in events:
            # Resolve note value: AbsoluteNote is absolute, numbers are relative to root
            if isinstance(e.value, AbsoluteNote):
                note_val = e.value.midi  # Absolute MIDI from note name
            elif isinstance(e.value, (int, float)):
                note_val = root + e.value  # Relative offset from root
            else:
                note_val = None  # Rest or unknown
            
            if note_val is not None:
                # Calculate duration from event's whole span (use latched value)
                if e.whole:
                    duration_time = e.whole[1] - e.whole[0]
                    duration_beats = float(duration_time) * active_cycle_beats
                else:
                    duration_beats = 0.1  # Short default for fast patterns
                
                # Clamp minimum duration
                duration_beats = max(0.01, duration_beats)
                
                note = Note(m=int(note_val), l=duration_beats)
                note.trigger(cut=False)


# -----------------------------
# Public API: tc.n() / tc.note()
# -----------------------------
def note(pattern_str: str, c=4, root=60, parent=None, mute=False, bus_name=None) -> 'PatternChain':
    """
    Create a standalone pattern from mini-notation.
    
    Args:
        pattern_str: Mini-notation string (e.g., "0 3 5 7")
        c: Cycle duration in beats (default 4 = one bar).
           Can be a static value OR a UI wrapper for dynamic updates.
        root: Root note (default 60 = C4). Values in pattern are offsets from root.
              Can be a static value OR a UI wrapper for dynamic updates.
        parent: Optional parent voice (ties pattern to voice lifecycle).
                If provided, pattern is cleaned up via stop_patterns_for_voice().
                If None, pattern persists until .stop() is called.
        mute: If True, pattern is ghost/silent (state-only, no audio). Default False.
        bus_name: Optional bus name for cross-scope state access.
    
    Returns:
        PatternChain object (auto-started)
    
    Example:
        # Tied to voice lifecycle
        def onTriggerVoice(v):
            tc.n("<0 3 5>", c=4, parent=v, bus='melody')
        
        # Persistent (manual cleanup required)
        _clock = None
        def onTick():
            global _clock
            if _clock is None:
                _clock = tc.n("<0 1 2 3>", c=1, mute=True, bus='clock')
            tc.update()
        
        # Manual cleanup
        _clock.stop()
    """
    # Create PatternChain (no MIDI wrapper for standalone patterns)
    chain = PatternChain(midi_wrapper=None, mute=mute)
    
    # Parse and set up the pattern
    pat = _parse_mini(pattern_str)
    chain._pattern = pat
    chain._root = root
    chain._cycle_beats = c
    chain._parent_voice = parent
    
    # Expose parent voice in state (if provided)
    chain._state['parentVoice'] = parent
    
    # Register to bus if name provided
    if bus_name:
        voice_id = bus(bus_name).register(chain)
        chain._bus_name = bus_name
        chain._bus_voice_id = voice_id
    
    # Auto-start the underlying pattern
    pat.start(_get_current_tick())
    
    # Register chain for update loop
    _register_chain(parent, chain, c, root)
    
    return chain


def n(pattern_str: str, c=4, root=60, parent=None, mute=False, bus=None) -> 'PatternChain':
    """
    Create a standalone pattern from mini-notation.
    
    Alias for tc.note() with 'bus' as keyword arg name.
    See tc.note() for full documentation.
    """
    return note(pattern_str, c=c, root=root, parent=parent, mute=mute, bus_name=bus)


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


def _midi_n(self, pattern_str: str, c=4, mute=False, bus_name=None) -> 'PatternChain':
    """
    Create a pattern from mini-notation, using this voice's note as root.
    
    Args:
        pattern_str: Mini-notation string (e.g., "0 3 5 7")
        c: Cycle duration in beats (default 4 = one bar).
           Can be a static value OR a UI wrapper (e.g., tc.par.MyKnob) for dynamic updates.
        mute: If True, pattern is ghost/silent (state-only, no audio). Default False.
        bus_name: Optional bus name for cross-scope state access.
    
    Returns:
        PatternChain object (auto-started, tied to this voice's lifecycle)
    
    Example:
        def onTriggerVoice(incomingVoice):
            midi = tc.MIDI(incomingVoice)
            midi.n("0 3 5 7", c=4)  # Static: 4 beats per cycle
            midi.n("0 3 5 7", c=tc.par.MyKnob)  # Dynamic: follows knob value
            midi.n("<0 1 2 3>", c=1, mute=True, bus='clock')  # Ghost clock pattern
    """
    # Create PatternChain with mute setting
    chain = PatternChain(midi_wrapper=self, mute=mute)
    
    # Parse and set up the pattern
    pat = _parse_mini(pattern_str)
    chain._pattern = pat
    chain._root = self.note  # Use incoming MIDI note as root
    chain._cycle_beats = c
    chain._parent_voice = self.parentVoice
    
    # Expose parent voice in state
    chain._state['parentVoice'] = self.parentVoice
    
    # Initialize bus registration tracking on MIDI wrapper if needed
    if not hasattr(self, '_bus_registrations'):
        self._bus_registrations = []
    
    # Register to bus if name provided
    if bus_name:
        voice_id = bus(bus_name).register(chain)
        chain._bus_name = bus_name
        chain._bus_voice_id = voice_id
        self._bus_registrations.append((bus_name, voice_id))
    
    # Auto-start the underlying pattern
    pat.start(_get_current_tick())
    
    # Register chain for update loop (tied to parentVoice)
    _register_chain(self.parentVoice, chain, c, self.note)
    
    return chain


# Attach method to MIDI class (use 'bus' as parameter name in public API)
def _midi_n_wrapper(self, pattern_str: str, c=4, mute=False, bus=None) -> 'PatternChain':
    """Wrapper to allow 'bus' as keyword arg (avoiding shadowing global bus())."""
    return _midi_n(self, pattern_str, c=c, mute=mute, bus_name=bus)

MIDI.n = _midi_n_wrapper




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
        
        # Resolve dynamic cycle_beats each tick (allow fractional for smooth control)
        cycle_beats = _resolve_dynamic(cycle_beats_raw)
        try:
            cycle_beats = float(cycle_beats)
            if cycle_beats <= 0:
                cycle_beats = 0.01  # Minimum: very fast (100x per beat)
        except (TypeError, ValueError):
            cycle_beats = 4  # Fallback to default
        
        # Check if the pattern is still running
        if not pat._running:
            del _midi_patterns[voice_id]
            continue
        
        # Debug: show timing info (using pattern's internal phase and latched cycle)
        latched_c = pat._latched_cycle_beats or cycle_beats
        _log("patterns", f"tick={current_tick} phase={float(pat._phase):.4f} c={cycle_beats:.3f} latched_c={latched_c:.3f}", level=2)
        
        # Process events (pattern.tick() uses cycle-latched timing)
        events = pat.tick(current_tick, ppq, cycle_beats)
        
        # Use the latched cycle_beats for duration calculation (consistent within cycle)
        active_cycle_beats = pat._latched_cycle_beats or cycle_beats
        
        for e in events:
            _log("patterns", f"EVENT value={e.value} whole=({float(e.whole[0]):.4f}, {float(e.whole[1]):.4f}) part=({float(e.part[0]):.4f}, {float(e.part[1]):.4f}) has_onset={e.has_onset()}", level=2)
        
        for e in events:
            # Resolve note value: AbsoluteNote is absolute, numbers are relative to root
            if isinstance(e.value, AbsoluteNote):
                note_val = e.value.midi  # Absolute MIDI from note name
            elif isinstance(e.value, (int, float)):
                note_val = root + e.value  # Relative offset from root
            else:
                note_val = None  # Rest or unknown
            
            if note_val is not None:
                # Calculate duration from event's whole span (use latched cycle_beats)
                if e.whole:
                    duration_time = e.whole[1] - e.whole[0]
                    duration_beats = float(duration_time) * active_cycle_beats
                else:
                    duration_beats = 0.1  # Short default for fast patterns
                
                # Clamp minimum duration to avoid zero-length notes
                duration_beats = max(0.01, duration_beats)
                
                _log("patterns", f"TRIGGER note={note_val} duration={duration_beats:.3f} beats", level=1)
                
                note_obj = Note(m=int(note_val), l=duration_beats)
                note_obj.trigger(cut=False, parent=midi_wrapper.parentVoice)


def _update_pattern_chains():
    """Update all registered PatternChains. Called from tc.update()."""
    try:
        ppq = vfx.context.PPQ
    except AttributeError:
        return  # Not in VFX context
    
    current_tick = _get_current_tick()
    
    for chain_id in list(_chain_registry.keys()):
        chain, cycle_beats_raw, root_raw, parent_id = _chain_registry[chain_id]
        
        # Skip if chain stopped
        if not chain._running:
            del _chain_registry[chain_id]
            continue
        
        # Resolve dynamic cycle_beats each tick
        cycle_beats = _resolve_dynamic(cycle_beats_raw)
        try:
            cycle_beats = float(cycle_beats)
            if cycle_beats <= 0:
                cycle_beats = 0.01
        except (TypeError, ValueError):
            cycle_beats = 4
        
        # Resolve dynamic root
        root = _resolve_dynamic(root_raw)
        chain._root = root
        chain._cycle_beats = cycle_beats
        
        # Tick the chain (updates state and fires notes if not muted)
        chain.tick(current_tick, ppq, cycle_beats)


def stop_patterns_for_voice(parent_voice):
    """
    Stop all patterns associated with a parent voice.
    Call this in onReleaseVoice() to clean up MIDI-bound patterns and PatternChains.
    
    Args:
        parent_voice: The incoming voice that was released
    """
    voice_id = id(parent_voice)
    
    # Get current tick for history tracking
    try:
        release_tick = vfx.context.ticks
    except AttributeError:
        release_tick = _get_current_tick()
    
    # Clean up legacy _midi_patterns (for backward compatibility)
    if voice_id in _midi_patterns:
        pat, _, _, _ = _midi_patterns[voice_id]
        pat.stop()
        del _midi_patterns[voice_id]
    
    # Clean up PatternChains registered to this voice
    if voice_id in _voice_chain_map:
        for bus_name, bus_voice_id, chain_id in _voice_chain_map[voice_id]:
            # Release from bus (moves to history)
            if bus_name and bus_voice_id:
                bus(bus_name).release(bus_voice_id, release_tick)
            
            # Remove from chain registry
            if chain_id in _chain_registry:
                chain, _, _, _ = _chain_registry[chain_id]
                chain._running = False
                if chain._pattern:
                    chain._pattern.stop()
                del _chain_registry[chain_id]
        
        del _voice_chain_map[voice_id]


def update():
    """
    Process triggers, releases, and patterns. Call in onTick().
    
    Order of operations:
    1. Process pending triggers and releases
    2. Update standalone patterns (tc.n - legacy)
    3. Update MIDI-bound patterns (midi.n - legacy)
    4. Update PatternChains (new bus system)
    5. Increment tick counter (so patterns created this frame start at tick 0)
    """
    global _internal_tick
    
    _base_update()
    _update_patterns()
    _update_midi_patterns()
    _update_pattern_chains()
    
    # Increment tick AFTER all processing, so patterns created this frame start at tick 0
    _internal_tick += 1


# Initialization message
print("[TrapCode] Initialized")
