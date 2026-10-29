# Index0 Startup Notes

Use the Windows Python launcher for this project.

Current local conclusion:

- `py -3.14` is the working interpreter for the UI on this machine.
- `py -3.14` already has `pygame-ce` and `owlready2` installed.
- `py -3.13` is installed, but currently does not have `pygame`.
- Plain `python` is not registered on PATH here and opens the Windows Store alias error.

Useful checks:

```powershell
py -3.14 -c "import pygame, owlready2; print(pygame.version.ver); print('owlready2 ok')"
py -3.13 -c "import pygame, owlready2"
```

For rendering or running the Pygame UI from automation, prefer:

```powershell
py -3.14 app/app.py
```

Package execution is also supported:

```powershell
py -3.14 -m app.app
```

Neither command requires a custom `PYTHONPATH`.

For headless screenshot rendering, set:

```powershell
$env:SDL_VIDEODRIVER='dummy'
$env:PYGAME_HIDE_SUPPORT_PROMPT='1'
```
