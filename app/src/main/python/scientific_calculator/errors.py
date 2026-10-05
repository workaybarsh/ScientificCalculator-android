"""Domain exceptions and presentation helpers shared by calculation modules.

The calculation engine deliberately retains its existing error strings for API
compatibility.  The desktop UI should call :func:`translate_error_message`
immediately before putting an error on the LCD.  This keeps library callers
from receiving a surprising, translated exception while ensuring that users
never see one of the legacy Turkish messages.
"""

from __future__ import annotations

import re
from enum import StrEnum

# These are message *fragments*, rather than exception types, because a number
# of the older errors interpolate a label (for example, ``"Upper bound"``).
# Order here does not matter: the table is re-sorted by descending fragment
# length below, so an exact sentence always wins over its own constituents.
# Every source fragment contains Turkish-specific wording, which means an
# already-English message is returned byte-for-byte unchanged.
_TURKISH_TO_ENGLISH: tuple[tuple[str, str], ...] = (
    # Spreadsheet, entry parsing, and safe-expression validation.
    ("Denklem için SOLVE kullanın; kırmızı = yalnız denklem girdisidir.",
     "Use SOLVE for equations; the red = is only for equation input."),
    ("Bitişik çarpım ifadesi çok karmaşık", "Implicit-multiplication expression is too complex"),
    ("Matematiksel ifade bekleniyor", "A mathematical expression is required"),
    ("Özellik erişimine izin verilmez", "Attribute access is not allowed"),
    ("İfade yapısına izin verilmez", "Expression structure is not allowed"),
    ("Faktöriyel girdisi çok büyük", "Factorial input is too large"),
    ("Kombinatorik girdi çok büyük", "Combinatorial input is too large"),
    ("Matematik dışı karakter", "Non-mathematical character"),
    ("Matematik dışı ifade", "Non-mathematical expression"),
    ("Matematik dışı sabit", "Non-mathematical constant"),
    ("Fonksiyona izin verilmez", "Function is not allowed"),
    ("İşleme izin verilmez", "Operation is not allowed"),
    ("İfade çok karmaşık", "Expression is too complex"),
    ("İfade çok uzun", "Expression is too long"),
    ("İfade metin olmalıdır", "Expression must be text"),
    ("Geçersiz değişken değeri", "Invalid variable value"),
    ("Değişken tek harf olmalıdır", "Variable must be a single letter"),
    ("Bilinmeyen ad:", "Unknown name:"),
    ("Bilinmeyen ad", "Unknown name"),
    ("Boş ifade", "Empty expression"),
    ("Geçersiz ifade", "Invalid expression"),
    ("Çok fazla ardışık ifade", "Too many consecutive expressions"),
    ("yüzde için geçerli sol değer gerekli", "percentage requires a valid left value"),
    ("yüzde için sol değer gerekli", "percentage requires a left value"),
    ("Üs sonucu çok büyük", "Exponent result is too large"),
    ("üs sonucu çok büyük", "exponent result is too large"),
    ("Üs çok büyük", "Exponent is too large"),
    ("formül 49 baytı aşıyor", "formula exceeds 49 bytes"),
    ("sabit 10 baytı aşıyor", "constant exceeds 10 bytes"),
    ("adım yönü başlangıç/bitiş ile uyuşmuyor", "step direction does not match start/end"),
    # Solving, symbolic calculations, and number bases.
    ("Bilinen değer girilmeli:", "A known value is required:"),
    ("Başlangıç tahminini değiştirin", "Change the initial estimate"),
    ("kök doğrulanamadı", "root could not be verified"),
    ("sembolik integral alınamadı", "symbolic integral could not be computed"),
    ("integral kapalı biçimde bulunamadı", "integral could not be found in closed form"),
    ("sembolik türev alınamadı", "symbolic derivative could not be computed"),
    ("türev istenen toleransa yakınsamadı", "derivative did not converge to the requested tolerance"),
    ("türev toleransı pozitif sonlu sayı olmalıdır", "derivative tolerance must be a positive finite number"),
    ("türev noktası sonlu reel olmalıdır", "derivative point must be finite and real"),
    ("türev bu noktada sonlu reel değil", "derivative is not finite and real at this point"),
    ("türev örneklemi sonlu reel değil", "derivative sample is not finite and real"),
    ("türev sonucu sonlu reel değil", "derivative result is not finite and real"),
    ("Σ aralığı hesaplama sınırını aşıyor", "Sigma range exceeds the calculation limit"),
    ("Σ hesaplanamadı", "Sigma could not be computed"),
    ("Geçersiz bellek", "Invalid memory"),
    ("Geçersiz taban", "Invalid base"),
    ("Base-N ifadesi çok uzun", "Base-N expression is too long"),
    ("geçersiz Base-N ifadesi", "invalid Base-N expression"),
    ("Base-N ifadesi", "Base-N expression"),
    ("geçersiz tabanlı sayı", "invalid base-N number"),
    ("tabanlı sayı", "base number"),
    # Integrals and multivariate calculus.
    ("integral toleransı pozitif sonlu sayı olmalıdır", "integral tolerance must be a positive finite number"),
    ("integral iç tekilliği yakınsak değil", "integral interior singularity is not convergent"),
    ("integral hata tahmini sonlu değil", "integral error estimate is not finite"),
    ("integral sınırı sayısal olmalıdır", "integral bound must be numeric"),
    ("integral sınırı metin olmalıdır", "integral bound must be text"),
    ("integral sınırları sonlu reel olmalıdır", "integral bounds must be finite and real"),
    ("integral sayısal sonuç vermedi", "integral did not produce a numeric result"),
    ("integral sonucu sonlu karmaşık değil", "integral result is not a finite complex number"),
    ("integral sonucu sonlu reel değil", "integral result is not finite and real"),
    ("integral sonlu karmaşık değil", "integral result is not a finite complex number"),
    ("integral sonlu reel değil", "integral result is not finite and real"),
    ("integralde bilinmeyen değişken var", "integral contains an unknown variable"),
    ("integral değişkenleri farklı olmalıdır", "integral variables must be different"),
    ("çoklu integral sınırları sonlu reel olmalıdır", "multiple-integral bounds must be finite and real"),
    ("çoklu integral hata tahmini geçersiz", "multiple-integral error estimate is invalid"),
    ("çoklu integral hata tahmini sonlu değil", "multiple-integral error estimate is not finite"),
    ("çoklu integral sonucu sonlu reel değil", "multiple-integral result is not finite and real"),
    ("karmaşık çift katlı integral sonucu sonlu değil", "complex double-integral result is not finite"),
    ("karmaşık çift katlı integral hesaplanamadı", "complex double integral could not be computed"),
    ("çift katlı integral hesaplanamadı", "double integral could not be computed"),
    ("üç katlı integral hesaplanamadı", "triple integral could not be computed"),
    ("karmaşık çift katlı integralde bilinmeyen değişken var", "complex double integral contains an unknown variable"),
    ("çift katlı integralde bilinmeyen değişken var", "double integral contains an unknown variable"),
    ("üç katlı integralde bilinmeyen değişken var", "triple integral contains an unknown variable"),
    # Differential equations and initial conditions.
    ("bağımlı ve bağımsız değişken farklı olmalıdır", "dependent and independent variables must be different"),
    ("ODE değişkeni d, e veya i olamaz", "ODE variable cannot be d, e, or i"),
    ("yalnız birinci ve ikinci dereceden türevler desteklenir",
     "only first- and second-order derivatives are supported"),
    ("yalnız birinci ve ikinci dereceden ODE desteklenir", "only first- and second-order ODEs are supported"),
    ("diferansiyel denklem yalnız bir = içerebilir", "differential equation may contain only one ="),
    ("ODE ayrılmış ifade adını kullanamaz", "ODE cannot use a reserved expression name"),
    ("ODE türevi seçilen bağımsız değişkeni kullanmalıdır",
     "ODE derivative must use the selected independent variable"),
    ("ODE birinci veya ikinci türev içermelidir", "ODE must contain a first- or second-order derivative"),
    ("ODE denkleminin iki tarafı da gerekli", "both sides of the ODE equation are required"),
    ("yalnız seçilen fonksiyonun türevi desteklenir", "only the selected function's derivative is supported"),
    ("başlangıç koşulları x0=…, y0=… biçiminde olmalıdır",
     "initial conditions must use the form x0=…, y0=…"),
    ("başlangıç koşulları metin veya eşleme olmalıdır", "initial conditions must be text or a mapping"),
    ("başlangıç koşulu birden fazla verildi", "an initial condition was provided more than once"),
    ("başlangıç koşulları farklı noktalara ait", "initial conditions apply to different points"),
    ("başlangıç koşulları x0 ve y0 birlikte gerektirir", "initial conditions require x0 and y0 together"),
    ("birinci dereceden ODE için y'(x0) girilmez", "do not provide y'(x0) for a first-order ODE"),
    ("ikinci dereceden ODE için dy0 gereklidir", "dy0 is required for a second-order ODE"),
    ("başlangıç değeri bağımsız veya bağımlı değişken içeremez",
     "initial value cannot contain the independent or dependent variable"),
    ("diferansiyel denklem kapalı biçimde çözülemedi", "differential equation could not be solved in closed form"),
    ("diferansiyel denklem tek bir çözüm vermedi", "differential equation did not produce exactly one solution"),
    ("başlangıç koşulu adı metin olmalıdır", "initial-condition name must be text"),
    ("başlangıç koşulu x0, y0 veya dy0 olmalıdır", "initial-condition name must be x0, y0, or dy0"),
    ("başlangıç noktası sonlu reel olmalıdır", "initial point must be finite and real"),
    # Matrix, vector, statistics, regression, distributions, and ratios.
    ("geçersiz matris verisi", "invalid matrix data"),
    ("geçersiz matris adı", "invalid matrix name"),
    ("matris verileri sonlu olmalıdır", "matrix values must be finite"),
    ("ikinci matris tanımsız", "second matrix is undefined"),
    ("matris tanımsız", "matrix is undefined"),
    ("matris verileri geçersiz", "matrix values are invalid"),
    ("matris sonucu sonlu değil", "matrix result is not finite"),
    ("tekil matris", "singular matrix"),
    ("geçersiz vektör verisi", "invalid vector data"),
    ("geçersiz vektör adı", "invalid vector name"),
    ("vektör verileri sonlu olmalıdır", "vector values must be finite"),
    ("ikinci vektör tanımsız", "second vector is undefined"),
    ("vektör verileri geçersiz", "vector values are invalid"),
    ("vektör sonucu sonlu değil", "vector result is not finite"),
    ("sıfır vektörün açısı tanımsızdır", "angle of the zero vector is undefined"),
    ("arg(0) tanımsızdır", "arg(0) is undefined"),
    ("karmaşık sonuç sadeleştirilemedi", "complex result could not be simplified"),
    ("geçersiz regresyon verisi", "invalid regression data"),
    ("dönüştürülmüş regresyon verileri sonlu olmalıdır", "transformed regression values must be finite"),
    ("regresyon verileri sonlu olmalıdır", "regression values must be finite"),
    ("bağımsız veri çeşitliliği yetersiz", "independent-data variation is insufficient"),
    ("regresyon hesaplanamadı", "regression could not be computed"),
    ("regresyon katsayıları sonlu değil", "regression coefficients are not finite"),
    ("istatistik sonucu sonlu değil", "statistical result is not finite"),
    ("frekanslar güvenli tam sayı aralığında olmalıdır", "frequencies must be within the safe integer range"),
    ("toplam frekans güvenli tam sayı aralığında olmalıdır",
     "total frequency must be within the safe integer range"),
    ("toplam frekans pozitif olmalıdır", "total frequency must be positive"),
    ("geçersiz frekans", "invalid frequency"),
    ("veriler sonlu olmalıdır", "values must be finite"),
    ("geçersiz veri", "invalid data"),
    ("veri yok", "no data was provided"),
    ("dağılım sonucu sonlu değil", "distribution result is not finite"),
    ("geçersiz denklem verisi", "invalid equation data"),
    ("denklem verileri sonlu olmalıdır", "equation values must be finite"),
    ("denklem sonucu sonlu değil", "equation result is not finite"),
    ("oran değeri eksik", "ratio value is missing"),
    ("oran sonucu sonlu değil", "ratio result is not finite"),
    ("sayısal sonuç görüntüleme aralığını aşıyor", "numeric result exceeds the display range"),
    ("sayısal sonuç görüntüleme sınırını aşıyor", "numeric result exceeds the display limit"),
    ("görüntüleme aralığını aşıyor", "exceeds the display range"),
    ("kesin sonuç görüntüleme sınırını aşıyor", "exact result exceeds the display limit"),
    ("kesin sonuç hesaplama sınırını aşıyor", "exact result exceeds the calculation limit"),
    ("başlangıç tahmini sonlu reel olmalıdır", "initial estimate must be finite and real"),
    ("sonlu reel kök bulunamadı", "a finite real root could not be found"),
    ("skaler sonlu reel olmalıdır", "scalar must be finite and real"),
    ("oran değerleri sonlu reel olmalıdır", "ratio values must be finite and real"),
    ("sonuç sonlu değil", "result is not finite"),
    ("alt sınır üst sınırı aşamaz", "lower bound cannot exceed upper bound"),
    ("0 ile 1 arasında olmalıdır", "must be between 0 and 1"),
    ("lambda negatif olamaz", "lambda cannot be negative"),
    ("sigma pozitif olmalıdır", "sigma must be positive"),
    # Dynamic-label suffixes and small, reusable phrases.  They are kept last
    # to avoid changing one of the more specific sentences above.
    (" tek harf olmalıdır", " must be a single letter"),
    (" metin veya sayı olmalıdır", " must be text or a number"),
    (" metin olmalıdır", " must be text"),
    (" yalnız dış integral değişkenlerini içerebilir", " may contain only outer integral variables"),
    (" sayısal hesaplamaya hazırlanamadı", " could not be prepared for numerical calculation"),
    (" negatif olmayan tam sayı olmalıdır", " must be a non-negative integer"),
    (" sonlu olmalıdır", " must be finite"),
    (" sonlu karmaşık olmalıdır", " must be a finite complex number"),
    (" sonlu reel olmalıdır", " must be finite and real"),
    (" hesaplanamadı", " could not be computed"),
    (" geçersiz", " is invalid"),
)
_TURKISH_TO_ENGLISH = tuple(
    sorted(_TURKISH_TO_ENGLISH, key=lambda replacement: len(replacement[0]), reverse=True)
)


# Diacritics identify the vast majority of legacy messages.  The word list
# catches the few Turkish phrases that are ASCII-only (for example ``oran``),
# as well as a future message that was not added to the table above.  If one
# survives translation, show a precise English category rather than leak a
# Turkish warning to the LCD.
_TURKISH_DIACRITIC_RE = re.compile(r"[çÇğĞıİöÖşŞüÜ]")
_TURKISH_WORD_RE = re.compile(
    r"\b(?:"
    r"adim|adım|alan|asiyor|aşıyor|baslangic|başlangıç|bellek|biciminde|biçiminde|"
    r"birinci|bitiş|cift|çift|cok|çok|degisken|değişken|denklem|diger|dış|dışı|"
    r"diferansiyel|dizisi|dogrulanamadi|doğrulanamadı|donusturulmus|dönüştürülmüş|"
    r"frekans|gecersiz|geçersiz|gerekli|girilmez|goruntuleme|görüntüleme|hesaplanamadi|"
    r"hesaplanamadı|ifade|ikinci|katsayilari|katsayıları|kirmizi|kırmızı|"
    r"kök|matris|olamaz|olmalidir|olmalıdır|oran|sinir|sınır|sayisal|sayısal|"
    r"taban|tanimli|tanımsız|turev|türev|uc|üç|ust|üst|vektor|vektör|yalniz|yalnız"
    r")\b",
    re.IGNORECASE,
)
_ERROR_CATEGORY_RE = re.compile(r"^(?P<category>[A-Za-z][A-Za-z ]*ERROR):?")


def translate_error_message(message: object) -> str:
    """Return an English LCD-safe rendering of a legacy calculator error.

    English input is intentionally returned unchanged.  The helper accepts an
    exception as well as a string so UI boundaries can simply pass their caught
    error object.  Unknown Turkish wording degrades to an English category
    message instead of exposing a partially translated warning.
    """

    text = str(message)
    translated = text
    for source, target in _TURKISH_TO_ENGLISH:
        translated = translated.replace(source, target)

    if not (_TURKISH_DIACRITIC_RE.search(translated) or _TURKISH_WORD_RE.search(translated)):
        return translated

    category = _ERROR_CATEGORY_RE.match(text)
    if category:
        return f"{category.group('category')}: The request could not be completed."
    return "Calculation ERROR: The input could not be understood."


class ErrorCode(StrEnum):
    """Stable categories for expected calculator-domain failures."""

    SYNTAX = "syntax"
    ARGUMENT = "argument"
    DIMENSION = "dimension"
    MEMORY = "memory"
    RANGE = "range"
    MATH = "math"
    CALCULATION = "calculation"
    INTERNAL = "internal"


_CODE_MESSAGES = {
    ErrorCode.SYNTAX: "Syntax ERROR",
    ErrorCode.ARGUMENT: "Argument ERROR",
    ErrorCode.DIMENSION: "Dimension ERROR",
    ErrorCode.MEMORY: "Memory ERROR",
    ErrorCode.RANGE: "Range ERROR",
    ErrorCode.MATH: "Math ERROR",
    ErrorCode.CALCULATION: "Calculation ERROR",
    ErrorCode.INTERNAL: "Internal ERROR",
}


def _infer_code(message: str) -> ErrorCode:
    prefix = message.split(":", 1)[0].strip().upper()
    return {
        "SYNTAX ERROR": ErrorCode.SYNTAX,
        "ARGUMENT ERROR": ErrorCode.ARGUMENT,
        "DIMENSION ERROR": ErrorCode.DIMENSION,
        "MEMORY ERROR": ErrorCode.MEMORY,
        "RANGE ERROR": ErrorCode.RANGE,
        "MATH ERROR": ErrorCode.MATH,
    }.get(prefix, ErrorCode.CALCULATION)


class CalculatorError(Exception):
    """A safe, English calculator-domain error with a stable semantic code.

    Legacy callers may still pass historical message text unchanged.  The UI
    boundary remains responsible for rendering those compatibility messages in
    English, while new callers can select a stable code directly.
    """

    def __init__(self, message: str | ErrorCode = ErrorCode.CALCULATION, *, code: ErrorCode | None = None) -> None:
        if isinstance(message, ErrorCode):
            code = message
            message = _CODE_MESSAGES[message]
        self.code = code or _infer_code(message)
        self.message = message
        super().__init__(message)
