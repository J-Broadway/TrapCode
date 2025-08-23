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
    class KnobWrapper(BaseWrapper):
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

    class KnobIntWrapper(BaseWrapper):
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

    class CheckboxWrapper(BaseWrapper):
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

    class ComboWrapper(BaseWrapper):
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

    class TextWrapper(BaseWrapper):
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
