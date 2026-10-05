# Verification record

Reproducible evidence that the port builds and behaves like the desktop
project.  All commands were run on Windows with Python 3.12, Temurin JDK 17,
Gradle 8.11.1, Android SDK 35, and Chaquopy 17.0.0.

## 1. Project bridge + shim tests (host, no Android)

```powershell
cd android
python -m unittest discover -s tests -v
```

Result: **46 passed** (`tests/test_android_bridge.py` + `tests/test_scipy_shim.py`).

## 1b. Faithful desktop UI driver (headless Tk)

```powershell
cd android
python -m unittest tests.test_headless_app tests.test_ui_bridge tests.test_dialogs -v
```

Result: **26 passed**.  These run the *real* `scientific_calculator.app` under the
virtual `tkinter`/`PIL` packages and assert the LCD matches the desktop:
`2+3 = 5`, `DEG sin(30) = 1/2`, the 12-mode menu, `Matrix -> "MAT Define / Edit ◀▶ ="`,
skin selection, and the interactive modal dialogs (CALC, STO, CONST, CONV, SETUP).

Total host tests: **72 passed**.

## 2. SciPy shim parity vs the real desktop SciPy

The same eight numeric-calculus test files were run twice: once against the
real SciPy (baseline) and once with the Android `scipy` shim shadowing it.

```powershell
# Baseline (real SciPy). PYTHONPATH = <desktop>\src
python -m pytest -o addopts="" -q -p no:cacheprovider `
  tests/test_calculus_modularity.py tests/test_calculus_numeric_adapter_guards.py `
  tests/test_complex_calculus_results.py tests/test_engine_calculate_calculus.py `
  tests/test_engine_modes.py tests/test_engine_multivariate_calculus.py `
  tests/test_engine_odes.py tests/test_improper_integrals.py
```

```powershell
# Shim. PYTHONPATH = <android>\app\src\main\python;<desktop>\src
python -c "import scipy; print(scipy.__file__, scipy.__version__)"   # -> ...\scipy\__init__.py 0.0.0+scicalc-shim
python -m pytest -o addopts="" -q -p no:cacheprovider `
  tests/test_calculus_modularity.py tests/test_calculus_numeric_adapter_guards.py `
  tests/test_complex_calculus_results.py tests/test_engine_calculate_calculus.py `
  tests/test_engine_modes.py tests/test_engine_multivariate_calculus.py `
  tests/test_engine_odes.py tests/test_improper_integrals.py *> shim_tests_full.log
```

| Run | Result |
|---|---|
| Baseline (real SciPy) | **286 passed** |
| Android SciPy shim | **286 passed** |

The first shim run exposed two real shim defects (fixed in `scipy/integrate.py`):

1. Divergent infinite tails (`∫ x dx`, `∫ 1/x dx` on `[1, ∞)`) were reported as
   finite because mpmath's tanh-sinh returns a large number instead of failing.
   Fixed with an explicit `|f|` decay check on infinite intervals.
2. The engine lambdifies integrands with NumPy, which rejects mpmath `mpf`
   arguments. Fixed by converting quadrature nodes to `float` before calling the
   integrand.

## 3. Android build

```powershell
gradle :app:assembleDebug
```

Result: **BUILD SUCCESSFUL** — `app/build/outputs/apk/debug/app-debug.apk`
(≈86 MB, ABIs `arm64-v8a` + `x86_64`). `compileDebugKotlin` reports no
errors or warnings.  The same `gradle :app:assembleDebug` target is what the
release workflow runs on the CI runner.

## 4. Continuous build and release (1.0.0)

`.github/workflows/release.yml` builds the debug APK on every `v*` tag and
publishes it as a GitHub release.  The 1.0.0 tag was built on `ubuntu-latest`
with JDK 17, Android SDK platform 35 / build-tools 35.0.0, Chaquopy 17.0.0 and
host Python 3.12:

- Host suite: **72 passed**.
- Gradle: **BUILD SUCCESSFUL** (`:app:assembleDebug`).
- Asset: `ScientificCalculator-android-v1.0.0.apk` (~86 MB) plus
  `SHA256SUMS.txt`.

## Known environment substitutions

- NumPy resolves to **1.26.2** (Chaquopy's Python 3.12 wheel), not the desktop's
  2.5.2; the engine's usage is compatible.
- SciPy is the pure-Python shim described above, because Chaquopy publishes no
  SciPy wheel for Python 3.12.
