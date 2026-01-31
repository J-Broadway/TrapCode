
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
