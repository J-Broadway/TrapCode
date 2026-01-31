
You can return the current working directory by running this code within VFX Script
```python
import sys
import os

print("sys.path:")
for p in sys.path:
    print("   ", p)

print("CWD:", os.getcwd())
```

## Paths

**Windows:**
```
C:\Program Files\Image-Line\FL Studio 2025\Shared\Python\Lib\
```

**macOS:**
```
/Applications/FL Studio 2025.app/Contents/Resources/FL/Shared/Python/Lib/
```

## FL Studio Python Paths (macOS)

```
/Applications/FL Studio 2025.app/Contents/Resources/FL/Shared/Python/Python.framework/Versions/3.12/lib/python3.12
/Applications/FL Studio 2025.app/Contents/Resources/FL/Shared/Python/Python.framework/Versions/3.12/lib/python3.12/lib-dynload
/Applications/FL Studio 2025.app/Contents/Resources/FL/Shared/Python/Lib
```

CWD: `/Applications/FL Studio 2025.app/Contents/Resources/FL`

## VFX Script Gotchas

### Voice Release Timing
`vfx.context.ticks` only advances during playback. For reliable note release regardless of transport state, set `voice.length` before triggering — FL's audio engine handles the release internally.

### Voice Velocity Range
`voice.velocity` expects **0-1 normalized**, not MIDI 0-127. Divide by 127 when converting from MIDI velocity.
