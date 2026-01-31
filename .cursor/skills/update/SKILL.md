---
name: update
description: Deploy trapcode.py to FL Studio's Python Lib folder. Use when the user says /update or asks to deploy/copy trapcode to FL Studio.
---

# Update TrapCode

Deploy `trapcode.py` to FL Studio's Python Lib folder.

## Command

Run this command to copy trapcode.py:

```bash
cp trapcode.py "/Applications/FL Studio 2025.app/Contents/Resources/FL/Shared/Python/Lib/"
```

## After Deployment
- Make sure README.md is updated (for trapcode.py)
- Remind the user to recompile their script in VFX Script (click Compile) to load the updated library.
