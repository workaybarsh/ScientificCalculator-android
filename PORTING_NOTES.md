# Scientific Calculator → Android: analysis and starter project

Source: `workaybarsh/ScientificCalculator` 1.0.0 (MIT). Keep `LICENSE-ScientificCalculator-MIT` with any redistribution.

> **Status: completed, built, and tested.**  The starter MVP grew into a full
> port: every desktop workspace now has a Compose screen backed by the real
> engine, settings/history persist in SQLite, a pure-Python SciPy shim replaces
> the unavailable Chaquopy wheel, and `assembleDebug` was run to a successful
> ≈86 MB APK.  The "starter" notes below are kept because they still describe why
> the port is structured this way; each open item records its resolution.

## 1. What is in this project

| Path | Status |
|---|---|
| `app/src/main/python/scientific_calculator/` | Copy of the desktop package with `__main__.py` omitted and `calculation_controller.py` replaced by a small Android stub (no working `multiprocessing`). Every other module, including the Tk `app.py`, is kept unchanged so the faithful screen can drive it headlessly. |
| `app/src/main/python/android_bridge.py` | Complete. ~70 allow-listed operations covering all 12 modes, English errors, thread-interrupt cancel, SQLite persistence. **Host-tested.** |
| `app/src/main/python/scipy/` | Pure-Python SciPy compatibility shim (`stats`, `integrate`). New; the engine source is unmodified. |
| `tests/test_android_bridge.py`, `tests/test_scipy_shim.py`, `tests/test_headless_app.py`, `tests/test_ui_bridge.py`, `tests/test_dialogs.py` | 72 host tests (all pass): every operation, settings policy, error boundary, cancellation, persistence, the shim, and the headless desktop UI. |
| `app/src/main/java/.../` | Kotlin + Compose **faithful** UI: renders the headless LCD plus its keypad, menus, Setup pane, and modal dialogs. **Compiled and packaged** (`assembleDebug` locally and via GitHub Actions). |

## 2. `app.py` analysis (≈3776 lines at the time of writing, one `App(tk.Tk)` class, ≈277 methods)

Classification by AST + token scan of each method body:

| Category | Methods | Lines | Meaning for the port |
|---|---|---|---|
| Direct Tk drawing/dialogs (`tk.`, `ttk.`, canvas, `ImageTk`) | 38 | ~1024 | Rewritten in Compose. Largest: `render_template` (316), `_ui` (123), `setup_dialog` (76). |
| Widget-coupled logic (touches `self.expr/result/status`, `render_template`) | 57 | ~819 | Reached through the bridge instead of a UI seam. |
| Logic only (settings, history, flow state, validation) | 181 | ~1411 | Reused from the engine and the Tk-free helper modules. |

Already Tk-free and reused as-is: `math_template`, `expression_document`, `lcd_fields`, `lcd_forms`, `lcd_flow_state`, `entry_rules`, `lcd_layout`, `template_session`, `spreadsheet*`, `history`, `settings_codec`, `settings_store`, `application_persistence`, `application_services`. The repo's own `test_architecture_boundaries.py` enforces that the engine kernel never imports UI code, which is why the engine ports cleanly.

Engine surface used by the UI is small: ~45 members of `ScientificCalculatorEngine` (evaluate, solve, matrix/vector ops, statistics, distributions, base-N, convert, …).

## 3. Two possible architectures

**A. Touch-native UI over the engine (prototyped first, then removed).** Kotlin forms call engine operations through the bridge. Fast to ship, feels native, and does not reproduce the desktop's key-by-key LCD state machine (SHIFT/ALPHA, in-LCD templates).

**B. Keep the LCD state machine in Python.** Extract the 181+57 logic methods of `App` into a headless `CalculatorSession` (`press(key) -> LcdSnapshot`) and let Compose only render snapshots. Highest fidelity (same 12 modes, same key behavior), but it is a refactor of ~2000 lines of tightly coupled code. Desktop tests (`tests/test_app_*.py`) would have to be retargeted to the new session.

This port ships architecture **B**: `headless_app.py` drives the real `app.py`
and Compose renders its LCD, so all twelve modes, SHIFT/ALPHA, templates, and
skins behave as on the desktop.  Architecture A was prototyped first but its
unused native screens were removed; only B ships, and it is what gives exact
desktop key-flow parity.

## 4. Risks and open items

- **R1 – SciPy availability.** Resolved with a shim.  Chaquopy's wheel index
  (pypi-13.1) publishes SciPy only for Python 3.8–3.10 (latest `scipy 1.8.1`
  for cp310), but this engine requires Python 3.12 (`enum.StrEnum` and PEP 695
  generics in `calculation_result.py`).  Rather than editing the engine,
  `app/src/main/python/scipy/` reimplements the exact imported subset:
  `stats.norm/binom/poisson` (pure `math.erf` / `statistics.NormalDist`) and
  `integrate.quad/dblquad/tplquad/IntegrationWarning` (mpmath-backed).  NumPy
  resolves to `1.26.2`, which satisfies the engine.  The desktop project's 286
  numeric-calculus tests pass against the shim.
- **R2 – Chaquopy facts.** Verified against the Chaquopy 17.0.0 docs:
  Python 3.12 supported, AGP 8.9–8.13 supported, Kotlin `.kts` uses the top-level
  `chaquopy {}` block, 32-bit ABIs are unavailable on Python ≥ 3.12 (hence
  `arm64-v8a` + `x86_64`), and `pluginManagement` only needs `mavenCentral()`.
- **R3 – Cancellation.** Resolved with an in-process interrupt
  (`PyThreadState_SetAsyncExc`): reliable for SymPy (pure Python), but a long
  single native SciPy call only stops when it returns to Python.  Kotlin also
  enforces a 30-second wall-clock timeout.  Hard-kill would need a separate
  Android `:py` process.
- **R4 – Persistence.** Resolved.  `configure(filesDir)` opens
  `filesDir/settings.db` through `SettingsStore`; settings and history are
  saved atomically after every mutating call and reloaded on launch.  Invalid
  saved values are ignored using the desktop validation policy.
- **R5 – Input UX.** The expression field supports free typing plus a keypad for
  Calc/Complex; other modes use numeric forms.  Cursor-level editing from
  `expression_document` / `lcd_fields` is not reproduced.
- **R6 – Output format.** Resolved.  `solve` is rendered as `x = …`, polynomial
  roots as `x1 = …`, simultaneous systems as `x1 = …`, and matrices/statistics
  as aligned monospace blocks.
- **R7 – Size and startup.** SymPy + SciPy + NumPy make the APK large and the
  first import slow.  The bridge is warmed up on a background thread at launch
  while the UI reports "Loading…".
- **R8 – Engine errors are Turkish internally.** The bridge reuses
  `translate_error_message` (as the desktop app does) so users see English; a
  test asserts every returned error is ASCII.

## 5. Build

1. Install Android Studio with a **JDK 17** toolchain and a host **Python 3.12**
   (Chaquopy needs it to run pip at build time).
2. Open the `android` folder; let Studio create the Gradle wrapper (the version
   is pinned in `gradle/wrapper/gradle-wrapper.properties`).
3. Run on an arm64 device or an x86_64 emulator.
4. Host tests for the bridge: `python -m unittest discover -s tests`.

See `README.md` for the feature matrix and the architecture diagram.
