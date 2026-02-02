# TrapCode Debugging System

## Overview

A simple, scalable logging system for TrapCode that follows standard design patterns. Provides a global toggle with log levels to control verbosity.

## Public API

```python
tc.debug(True)            # Enable debugging, level 1 (default)
tc.debug(True, level=2)   # Enable debugging, level 2 (verbose)
tc.debug(False)           # Disable debugging
tc.debug()                # Query state -> {'enabled': bool, 'level': int}
```

## Log Levels

| Level | Description | Use Cases |
|-------|-------------|-----------|
| 1 | Important events | Triggers, releases, errors, state changes |
| 2 | Verbose/frequent | Tick timing, arc calculations, internal state |

## Internal Implementation

### Module-Level State

```python
_debug_enabled = False
_debug_level = 1
```

### Internal Logger Function

```python
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
```

### Public Debug Function

```python
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
```

## Categories

Categories are used for consistent log prefixes. Current categories:

| Category | Description |
|----------|-------------|
| `debug` | Debug system messages |
| `patterns` | Pattern engine (parsing, events, timing) |
| `triggers` | Voice triggering and releases |
| `exports` | Output controller exports |
| `ui` | UI control changes |

Categories are for formatting only - no filtering implemented yet. Filtering can be added later without API changes.

## Migration: Existing Debug Code

### Before (current)

```python
_DEBUG_PATTERNS = True

# Scattered in _update_midi_patterns():
if _DEBUG_PATTERNS and rel_tick < 10:
    print(f"[Pattern] tick={current_tick} ...")

if _DEBUG_PATTERNS and events:
    for e in events:
        print(f"[Pattern] EVENT value={e.value} ...")

if _DEBUG_PATTERNS:
    print(f"[Pattern] TRIGGER note={note_val} ...")
```

### After (refactored)

```python
_debug_enabled = False
_debug_level = 1

# In _update_midi_patterns():
_log("patterns", f"tick={current_tick} rel={rel_tick} ...", level=2)

for e in events:
    _log("patterns", f"EVENT value={e.value} ...", level=2)

_log("patterns", f"TRIGGER note={note_val} duration={duration_beats}", level=1)
```

## Implementation Checklist

1. [x] Add `_debug_enabled` and `_debug_level` module state (near top, after helpers)
2. [x] Add `_log()` internal function
3. [x] Add `debug()` public function
4. [x] Remove `_DEBUG_PATTERNS = True`
5. [x] Replace all `if _DEBUG_PATTERNS:` blocks with `_log()` calls
6. [x] Assign appropriate levels (1=important, 2=verbose)
7. [x] Update README.md with debug API documentation

## Future Extensions (Not Implemented)

These can be added later without breaking the API:

- **Category filtering**: `tc.debug(True, categories=['patterns'])`
- **Log to file**: Not necessary, Fl Studio VFX environment restricts this behavior
- **Timestamps**: `tc.debug(True, timestamps=True)`
- **Custom formatters**: For structured output
