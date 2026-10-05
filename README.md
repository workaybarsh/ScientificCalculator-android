# Scientific Calculator for Android

A touch-native Android port of
[`workaybarsh/ScientificCalculator`](https://github.com/workaybarsh/ScientificCalculator)
(MIT).  The Python calculation engine is reused unchanged through
[Chaquopy](https://chaquo.com/chaquopy/); only the Tk user interface is replaced
with Kotlin + Jetpack Compose.

## Download

The current published build is **1.0.0** (arm64-v8a and x86_64, one universal
APK):

- Release page: <https://github.com/workaybarsh/ScientificCalculator-android/releases/tag/v1.0.0>
- APK asset: `ScientificCalculator-android-v1.0.0.apk`
- SHA-256: published in `SHA256SUMS.txt` on the release page

The same APK is referenced from the desktop repository's download table, which
links directly to this repository's release.

Every release is compiled and published by GitHub Actions
(`.github/workflows/release.yml`) from the tagged source; no local build is
required.

The build is signed with the checked-in `app/scicalc-debug.keystore` so every
release shares one signature; a new APK installs straight over the previous one.

## What is in this release

- **Faithful desktop interface.** The default screen runs the real desktop
  `scientific_calculator.app` headlessly and renders the LCD it produces, so the
  SHIFT/ALPHA state machine, the twelve modes, the templates, and the four skins
  match the desktop. The SHIFT/ALPHA overlay squares are gone; the LCD text
  alone reports the active modifier, exactly as on the desktop.
- **OFF.** SHIFT then AC powers the calculator off (the activity finishes and
  its task is cleared). Re-opening the app from the launcher or recents starts
  cleanly: every start clears the OFF latch and the modifier state, so a
  still-running process no longer closes again.
- **Result inspection.** ◀/▶ pan a long result and mark the hidden side with an
  ellipsis (like the integral field's caret view), so nothing looks deleted; the
  long input line keeps its tail visible with a leading ellipsis.
- **Layout.** The calculator is drawn inside the system bars and display cutout,
  so the status row is never clipped on notched or tall-status-bar devices. The
  face appears at once and only the LCD reports `Loading…`.
- **Touch.** Every key's target fills its whole cell (grown to the midpoint
  towards its neighbours), so gap taps register and small keys such as
  SHIFT/ALPHA and the arrow cluster are easier to hit.
- **Setup.** The desktop-only UI Scale row is not offered, because the Compose
  layer sizes the skin itself.
- **Signing and releases.** A stable key signs every build so a newer APK
  installs over the old one, and GitHub Actions builds and publishes each
  release from the tagged source.

## What is included

All twelve desktop workspaces have an Android screen backed by the real engine:

| Mode | Operations exposed |
|---|---|
| **Calculate** | evaluate (exact/approx), symbolic & numeric derivative, indefinite/definite integral, double & triple integral, summation, ODE |
| **Complex** | complex evaluate, `arg`, rectangular ↔ polar, complex derivative (Cauchy–Riemann), complex limit, complex integral |
| **Base-N** | evaluate in BIN/OCT/DEC/HEX, 32-bit AND/OR/XOR/XNOR/NOT/NEG, format, parse |
| **Matrix** | define MatA–MatD, add/subtract/multiply, determinant, inverse, transpose, square/cube, absolute, identity |
| **Vector** | define VctA–VctD, add/subtract, dot, cross, angle, norm, unit, scalar scale |
| **Statistics** | one-variable summary (with optional frequency), linear/quadratic/log/exp/power/inverse regression, standard-normal P/Q/R |
| **Distribution** | Normal PD/CD, Inverse Normal, Binomial PD/CD, Poisson PD/CD |
| **Equation** | numeric solve, simultaneous systems (2×2–4×4), polynomial roots, polynomial inequalities, ratios |
| **Convert** | the full 46-entry unit-conversion catalogue |
| **Table** | function table `f(x)` over a start/end/step range |
| **Spreadsheet** | 5×45 sheet with references, ranges (`Sum`, `Mean`, `Min`, `Max`), formula/value display, auto-calc |
| **Tools** | prime factorization, random integer/number, decimal ↔ DMS, polar/rectangular, standard normal P/Q/R |

Settings, memory, and the last ten history entries persist in SQLite inside the
app's private data directory.  The Setup dialog mirrors the desktop policy
(angle unit, input/output, number format/digits, complex format, decimal mark,
scientific-constant dataset, and the boolean switches).

## Architecture

```text
Compose screen / ViewModel
  -> PythonBridge.kt            (one dedicated engine thread, JSON in/out, cancel + timeout)
  -> android_bridge.py          (allow-listed operations, English error boundary)
  -> ScientificCalculatorEngine (unchanged Tk-free engine from the desktop project)
  -> sympy / numpy + a pure-Python `scipy` shim + SQLite SettingsStore
```

### Faithful desktop UI (headless Tk)

The app's default screen is not a re-implementation: it runs the desktop's
**real `scientific_calculator.app`** headlessly and renders the LCD it produces.

```text
Compose (FaithfulScreen)
  -> ui_* bridge ops
  -> headless_app.py            (press(key) / snapshot() / menu_select())
  -> real app.py, unmodified
  -> virtual `tkinter` + `PIL` packages (no display)
```

- Android has no Tk, so `app/src/main/python/tkinter/` and `PIL/` implement the
  exact widget surface `app.py` uses and record state (text, canvas items,
  menus) instead of drawing.
- `headless_app.py` constructs the App once (with CAS inline and the
  multiprocessing controller disabled), maps each keypad hotspot to its desktop
  method, and returns an LCD snapshot: status line, expression, result, active
  template items, and any captured popup menu.
- Because the desktop's own `_lcd_*` state machine drives everything, mode
  navigation, the 12 workspaces, SHIFT/ALPHA, templates, and history behave as
  they do on the desktop. Menu items (including History/Setup) are captured and
  shown as a Compose menu.
- Modal dialogs are interactive too: `simpledialog`/`messagebox` prompts
  (CALC variables, SOLVE, STO, RanInt, root degree, table, DMS, …) use a replay
  protocol, and custom `Toplevel` dialogs (SETUP, CONST, CONV, RESET) are
  serialized into Compose forms whose buttons and dropdowns invoke the desktop
  commands directly.

### Skins

All four desktop skins (**Graphite, Blue, Pink, White**) ship as Android assets
(`app/src/main/assets/skins/`) and are drawn full-surface at their native
480×980 geometry, with the LCD text and the exact `App._ui()` hotspot grid
overlaid on top. Selecting a skin in Setup updates the render immediately and
persists it through the desktop settings store.

- `android_bridge.py` is the only Kotlin→Python entry point.  It never raises;
  unexpected failures are returned as `Internal ERROR` so a bad calculation
  cannot kill the app process.
- `app/src/main/python/scientific_calculator/` is the desktop package with
  `__main__.py` omitted and `calculation_controller.py` replaced by a small
  import-compatible Android stub (Android has no working `multiprocessing`).
  The Tk application (`app.py`) and every other module are kept byte-for-byte,
  because the faithful screen drives them headlessly; no engine source is edited.
- Cancellation uses `PyThreadState_SetAsyncExc` because Android has no reliable
  `multiprocessing`; it interrupts pure-Python (SymPy) work at bytecode
  boundaries.

## Requirements

1. **Android Studio** with a JDK 17 toolchain.  The project pins AGP 8.9.1,
   Kotlin 2.1.20 and Chaquopy 17.0.0.
2. **Host Python 3.12** on `PATH` (or via the Windows `py -3.12` launcher).
   Chaquopy runs pip on the build machine and requires the same major/minor
   version as the app.  The build host's `python` must be 3.12.
3. A 64-bit target: an **arm64-v8a** device/emulator or an **x86_64** emulator.
   Chaquopy's Python 3.12 runtime has no 32-bit ABI build.

## Build and run

1. Open the `android` folder in Android Studio.  On first sync Studio creates
   the Gradle wrapper (the intended version is pinned in
   `gradle/wrapper/gradle-wrapper.properties`) and downloads dependencies.
2. Select an arm64 device or an x86_64 emulator.
3. Run the `app` configuration.

The first launch imports SymPy/SciPy/NumPy in the background; the keypad appears
immediately and the "Loading Python engine…" screen is only shown while the
bridge is being configured.

## Host tests

The bridge is fully testable on the host without Android:

```powershell
cd android
python -m unittest discover -s tests -v
```

72 tests cover every operation, the settings policy, the English error
boundary, cancellation, the SQLite persistence round-trip, the pure-Python
SciPy shim (distributions, quadrature, and the numeric-engine paths), and the
headless desktop UI (real `app.py` under the virtual Tk layer, including skin
selection, mode navigation, and interactive modal dialogs).  The host needs
`sympy`, `numpy` and `mpmath`; the tests shadow the real SciPy with the shim so
the Android behaviour is what is exercised.

## Verified build

This project was actually built in a clean Windows environment with only the
Android command-line tools:

- Temurin JDK 17, Gradle 8.11.1, Android SDK platform 35 + build-tools 35.0.0,
  Chaquopy 17.0.0 (Python 3.12), NumPy 1.26.2, SymPy 1.14.0, mpmath 1.3.0.
- `gradle :app:assembleDebug` → **BUILD SUCCESSFUL**: an ≈86 MB debug APK with both `arm64-v8a` and `x86_64` ABIs, including the four
  desktop skin assets (the size varies slightly with the build environment).
- The APK contains the compiled bridge, engine and shim (`app.imy`) plus the
  packaged dependencies.
- 72 project tests pass, and the **desktop project's own 286 numeric-calculus
  tests also pass with the shim**, which is the strongest available check that
  the shim matches SciPy for the engine's usage.
- The 1.0.0 APK is produced by the GitHub Actions workflow on a clean
  `ubuntu-latest` runner (JDK 17, Android SDK 35, Chaquopy 17.0.0, host
  Python 3.12), then attached to a GitHub release.

See `VERIFICATION.md` for the exact commands and recorded results.


## Known limitations and risks

- **SciPy (resolved).**  Chaquopy's wheel index publishes SciPy only up to
  Python 3.10, while this engine needs Python 3.12 (`enum.StrEnum` and PEP 695
  generics).  `app/src/main/python/scipy/` is therefore a pure-Python
  compatibility shim providing exactly the APIs the engine imports:
  `scipy.stats.norm/binom/poisson` (via `math.erf` and `statistics.NormalDist`)
  and `scipy.integrate.quad/dblquad/tplquad/IntegrationWarning` (via `mpmath`,
  a SymPy dependency).  The engine source itself is unmodified.
- **Native-call cancellation.**  A single long native SciPy routine only stops
  when it returns to Python.  Kotlin enforces a 30-second wall-clock timeout and
  then interrupts the thread.
- **APK size / startup.**  SymPy + SciPy + NumPy make the APK large (tens of MB
  per ABI) and the first import is noticeable; the engine is warmed up on a
  background thread at launch.
- **Physical-device coverage.**  The APK compiles and the 72-test host suite
  passes, but the build has not been validated on a broad range of physical
  devices; first-import time and native SciPy calls are the main device-dependent
  risks.  Desktop key-flow parity itself is provided by the faithful headless
  screen described below and in `PORTING_NOTES.md`.

## Faithful mode (default)

The default screen runs the real `app.py` headlessly (see below), so it *does*
reproduce the desktop's SHIFT/ALPHA LCD state machine, its 12-mode navigator,
its templates, and all four skins.  The remaining fidelity gaps are the modal
sub-dialogs (CALC/SOLVE/OPTN choices, the full Setup pane, constants/conversion
pickers), which are implemented as Compose dialogs where needed; and the
template canvas overlay is an approximation of the desktop's pixel layout.

## Device orientation

The app is locked to **portrait** (`android:screenOrientation="portrait"` in the
manifest).  It is designed for a phone held upright; it does not rotate, and the
skin is scaled to fit the available portrait area.

## App icon

The desktop `assets/icons/app.ico` is converted into Android launcher icons
(legacy `ic_launcher`/`ic_launcher_round` plus an adaptive icon whose background
matches the calculator body) under `app/src/main/res/mipmap-*`.

## License

The desktop project is MIT licensed; `LICENSE-ScientificCalculator-MIT` is kept
with this project and must accompany any redistribution.

