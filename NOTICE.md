# Notices and attribution

This project is an Android port of **Scientific Calculator**
(<https://github.com/workaybarsh/ScientificCalculator>), MIT licensed.

## Upstream

- Original project: `workaybarsh/ScientificCalculator`
- License: MIT (`LICENSE`, also kept as `LICENSE-ScientificCalculator-MIT`)
- Copyright: Scientific Calculator contributors

The desktop calculation engine (`app/src/main/python/scientific_calculator/`) is
copied from that project **without source modifications** (aside from the
Android-only adapter modules listed below). The desktop assets
(`app/src/main/assets/skins/*.png`, the application icon) are reused under the
same MIT license.

## Android-only additions

- `MainActivity.kt`, `SciCalcApp.kt`, `PythonBridge.kt`, UI under
  `app/src/main/java/com/example/scicalc/ui/`
- `app/src/main/python/android_bridge.py` — JSON bridge
- `app/src/main/python/headless_app.py` — headless driver for the desktop UI
- `app/src/main/python/tkinter/`, `app/src/main/python/PIL/` — virtual
  Tkinter/PIL used to run the desktop app without a display
- `app/src/main/python/scipy/` — pure-Python SciPy compatibility shim
- `app/src/main/python/scientific_calculator/calculation_controller.py` —
  Android stub replacing the multiprocessing controller

## Third-party

- **SciPy** shim API compatibility — SciPy is BSD-3-Clause; only its public API
  surface is reimplemented here, no SciPy code is included.
- **mpmath** (BSD-3-Clause) — used by the shim, installed at build time.
- **SymPy** (BSD-3-Clause) and **NumPy** (BSD-3-Clause) — installed at build
  time via Chaquopy.
- **Chaquopy** (MIT for the open-source edition) — build-time Gradle plugin.
