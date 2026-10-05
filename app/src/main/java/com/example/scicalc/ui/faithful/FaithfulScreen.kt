package com.example.scicalc.ui.faithful

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.displayCutout
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

// Skin geometry: every desktop skin is 480x980, and App._ui() places its LCD and
// hotspots in that coordinate space.  dx scales those units to the display.
private const val SKIN_W = 480f
private const val SKIN_H = 980f
private const val LCD_X1 = 40f
private const val LCD_Y1 = 128f
private const val LCD_X2 = 435f
private const val LCD_Y2 = 289f

private data class Hotspot(val key: String, val x1: Float, val y1: Float, val x2: Float, val y2: Float)

// App._skin_xy(): original generated-image coordinates -> 100% canvas pixels.
private fun skinX(sourceX: Float): Float = (sourceX - 330f) * 0.8f
private fun skinY(sourceY: Float): Float = (sourceY - 5f) * 0.8f

private val HOTSPOTS = listOf(
    Hotspot("SHIFT", 375f, 430f, 425f, 482f),
    Hotspot("ALPHA", 452f, 430f, 504f, 482f),
    Hotspot("MENU", 742f, 430f, 792f, 482f),
    Hotspot("ON", 820f, 430f, 872f, 482f),
    Hotspot("UP", 589f, 429f, 656f, 477f),
    Hotspot("LEFT", 526f, 470f, 586f, 530f),
    Hotspot("RIGHT", 659f, 470f, 720f, 530f),
    Hotspot("DOWN", 589f, 522f, 656f, 570f),
    Hotspot("OPTN", 363f, 536f, 438f, 585f),
    Hotspot("CALC", 451f, 536f, 526f, 585f),
    Hotspot("INTEGRAL", 720f, 536f, 785f, 585f),
    Hotspot("X", 808f, 536f, 873f, 585f),
    Hotspot("FRACTION", 363f, 610f, 437f, 660f),
    Hotspot("SQRT", 451f, 610f, 525f, 660f),
    Hotspot("SQUARE", 540f, 610f, 614f, 660f),
    Hotspot("POWER", 628f, 610f, 703f, 660f),
    Hotspot("LOG", 716f, 610f, 792f, 660f),
    Hotspot("LN", 805f, 610f, 879f, 660f),
    Hotspot("NEG", 363f, 683f, 437f, 733f),
    Hotspot("DMS", 451f, 683f, 525f, 733f),
    Hotspot("INV", 540f, 683f, 614f, 733f),
    Hotspot("SIN", 628f, 683f, 703f, 733f),
    Hotspot("COS", 716f, 683f, 792f, 733f),
    Hotspot("TAN", 805f, 683f, 879f, 733f),
    Hotspot("STO", 363f, 754f, 437f, 807f),
    Hotspot("ENG", 451f, 754f, 525f, 807f),
    Hotspot("LPAREN", 540f, 754f, 614f, 807f),
    Hotspot("RPAREN", 628f, 754f, 703f, 807f),
    Hotspot("SD", 716f, 754f, 792f, 807f),
    Hotspot("MPLUS", 805f, 754f, 879f, 807f),
    Hotspot("7", 363f, 832f, 456f, 902f),
    Hotspot("8", 468f, 832f, 561f, 902f),
    Hotspot("9", 574f, 832f, 667f, 902f),
    Hotspot("DEL", 680f, 832f, 773f, 902f),
    Hotspot("AC", 786f, 832f, 879f, 902f),
    Hotspot("4", 363f, 918f, 456f, 987f),
    Hotspot("5", 468f, 918f, 561f, 987f),
    Hotspot("6", 574f, 918f, 667f, 987f),
    Hotspot("MUL", 680f, 918f, 773f, 987f),
    Hotspot("DIV", 786f, 918f, 879f, 987f),
    Hotspot("1", 363f, 1002f, 456f, 1073f),
    Hotspot("2", 468f, 1002f, 561f, 1073f),
    Hotspot("3", 574f, 1002f, 667f, 1073f),
    Hotspot("PLUS", 680f, 1002f, 773f, 1073f),
    Hotspot("MINUS", 786f, 1002f, 879f, 1073f),
    Hotspot("0", 363f, 1088f, 456f, 1158f),
    Hotspot("DOT", 468f, 1088f, 561f, 1158f),
    Hotspot("SCI", 574f, 1088f, 667f, 1158f),
    Hotspot("ANS", 680f, 1088f, 773f, 1158f),
    Hotspot("EQUALS", 786f, 1088f, 879f, 1158f),
)

// Touch targets are the printed keys grown to the midpoint towards their nearest
// neighbours.  The keys are drawn with small gaps, so a tap that landed in a gap
// used to hit nothing, and the smallest keys (SHIFT/ALPHA, the arrow cluster)
// were smaller than a comfortable thumb target.  Growing to the midpoint makes
// every key own its whole cell without ever overlapping the next key.
private val TOUCH_HOTSPOTS: List<Hotspot> by lazy { expandHotspots(HOTSPOTS) }

private fun expandHotspots(spots: List<Hotspot>, margin: Float = 12f): List<Hotspot> {
    fun verticalOverlap(a: Hotspot, b: Hotspot): Boolean =
        minOf(a.y2, b.y2) - maxOf(a.y1, b.y1) > 0f

    fun horizontalOverlap(a: Hotspot, b: Hotspot): Boolean =
        minOf(a.x2, b.x2) - maxOf(a.x1, b.x1) > 0f

    return spots.map { h ->
        val left = spots.filter { it !== h && it.x2 <= h.x1 && verticalOverlap(it, h) }.maxByOrNull { it.x2 }
        val right = spots.filter { it !== h && it.x1 >= h.x2 && verticalOverlap(it, h) }.minByOrNull { it.x1 }
        val up = spots.filter { it !== h && it.y2 <= h.y1 && horizontalOverlap(it, h) }.maxByOrNull { it.y2 }
        val down = spots.filter { it !== h && it.y1 >= h.y2 && horizontalOverlap(it, h) }.minByOrNull { it.y1 }
        Hotspot(
            key = h.key,
            x1 = left?.let { (it.x2 + h.x1) / 2f } ?: (h.x1 - margin),
            y1 = up?.let { (it.y2 + h.y1) / 2f } ?: (h.y1 - margin),
            x2 = right?.let { (it.x1 + h.x2) / 2f } ?: (h.x2 + margin),
            y2 = down?.let { (it.y1 + h.y2) / 2f } ?: (h.y2 + margin),
        )
    }
}

@Composable
fun FaithfulScreen(vm: FaithfulViewModel, onPowerOff: () -> Unit = {}) {
    val state by vm.state.collectAsStateWithLifecycle()
    val snapshot = state.snapshot
    val ready = state.ready

    // SHIFT+AC (OFF) asks the Android activity to close.
    LaunchedEffect(snapshot.powerOff) {
        if (snapshot.powerOff) onPowerOff()
    }

    // The keypad and LCD paint immediately; only the LCD reports "Loading…"
    // while the Python engine starts, matching the desktop.
    CalculatorFace(snapshot, if (ready) state.error else null, vm, loading = !ready)

    if (!ready) return

    if (snapshot.menu != null) {
        ModeMenu(snapshot.menu, onDismiss = { vm.press("AC") }) { item ->
            vm.menuSelect(item.path)
        }
    }

    // Modal prompt raised by the desktop (CALC/SOLVE/STO/RanInt/...).
    snapshot.dialog?.let { pending ->
        PromptDialog(
            dialog = pending,
            onAnswer = { vm.answerDialog(it) },
            onDismiss = { vm.answerDialog(cancelValue(pending.kind)) },
        )
    }

    // Informational message boxes (help, recall, ...).
    snapshot.info.lastOrNull()?.let { message ->
        InfoDialog(message = message, onDismiss = { vm.dismissInfo() })
    }

    // Custom Toplevel dialogs (SETUP/CONST/CONV/RESET) — show the topmost.
    snapshot.dialogs.lastOrNull()?.let { live ->
        LiveDialogWindow(
            dialog = live,
            onInvoke = { widget, action, value -> vm.invokeDialog(live.id, widget, action, value) },
            onDismiss = { vm.closeAllDialogs() },
        )
    }
}

private fun cancelValue(kind: String): Any? = when (kind) {
    "float", "integer" -> null
    "yesno" -> false
    else -> null
}

@Composable
private fun CalculatorFace(snapshot: UiSnapshot, error: String?, vm: FaithfulViewModel, loading: Boolean) {
    val context = LocalContext.current
    val bitmap: ImageBitmap? = remember(snapshot.skin) {
        runCatching {
            context.assets.open("skins/skin_${snapshot.skin.lowercase()}.png").use {
                BitmapFactory.decodeStream(it).asImageBitmap()
            }
        }.getOrNull()
    }

    BoxWithConstraints(
        Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.systemBars.union(WindowInsets.displayCutout))
            .background(Color(0xFFFFFFFF)),
    ) {
        val aspect = SKIN_H / SKIN_W
        var skinWidth: Dp = maxWidth
        var skinHeight: Dp = maxWidth * aspect
        if (skinHeight > maxHeight) {
            skinHeight = maxHeight
            skinWidth = maxHeight / aspect
        }
        val unit = skinWidth.value / SKIN_W // dp per skin unit

        Box(
            Modifier
                .align(Alignment.Center)
                .size(skinWidth, skinHeight)
                .drawBehind {
                    if (bitmap == null) drawRect(color = Color(0xFFF2F4EF))
                },
        ) {
            if (bitmap != null) {
                Image(bitmap, contentDescription = "Calculator skin", modifier = Modifier.fillMaxSize())
            }

            LcdOverlay(snapshot, error, unit, loading)

            // Invisible-but-generous tap targets covering each key's full cell.
            TOUCH_HOTSPOTS.forEach { spot ->
                val source = remember { MutableInteractionSource() }
                val left = skinX(spot.x1)
                val top = skinY(spot.y1)
                val width = skinX(spot.x2) - left
                val height = skinY(spot.y2) - top
                Box(
                    Modifier
                        .offset(x = (left * unit).dp, y = (top * unit).dp)
                        .size(width = (width * unit).dp, height = (height * unit).dp)
                        .clickable(interactionSource = source, indication = null) { vm.press(spot.key) },
                )
            }
        }
    }
}

@Composable
private fun LcdOverlay(snapshot: UiSnapshot, error: String?, unit: Float, loading: Boolean) {
    // Positions copied verbatim from App._ui() and render_template(), in 480x980
    // skin units.  A background panel plus individually placed elements keeps
    // the LCD pixel-accurate at every display size.
    Box(
        Modifier
            .offset(x = (LCD_X1 * unit).dp, y = (LCD_Y1 * unit).dp)
            .size(((LCD_X2 - LCD_X1) * unit).dp, ((LCD_Y2 - LCD_Y1) * unit).dp)
            .background(Color(0xFFEAF0E5)),
    )

    if (loading) {
        // Mirrors the desktop, which shows its notice on the LCD while the
        // calculation engine imports; the keypad and skin are already visible.
        LcdText("Loading…", 47f, 428f, 200f, unit, 20f, true, Color(0xFF273026), "w")
        return
    }

    // Status line (mode / angle / base) and modifier indicators.
    LcdText(snapshot.status, 47f, 428f, 145f, unit, 12f, true, Color(0xFF273026), "w")
    if (snapshot.shift) LcdText("SHIFT", 323f, 372f, 145f, unit, 12f, true, Color(0xFF273026), "e")
    if (snapshot.alpha) LcdText("ALPHA", 374f, 428f, 145f, unit, 12f, true, Color(0xFF273026), "e")

    if (snapshot.template != null) {
        TemplateCanvas(
            template = snapshot.template,
            unit = unit,
            modifier = Modifier
                .offset(x = (47f * unit).dp, y = (158f * unit).dp)
                .size((381f * unit).dp, (92f * unit).dp),
        )
        LcdText(
            error ?: snapshot.result, 47f, 428f, 265f, unit, 24f, true,
            if (error != null) Color(0xFFB00020) else Color(0xFF111111), "e",
        )
    } else {
        InputLcdText(snapshot.expr, 47f, 428f, 187f, unit, 25f, Color(0xFF111111))
        FittedLcdText(
            text = snapshot.result,
            fullText = snapshot.resultFull,
            left = 47f, right = 428f, centerY = 246f, unit = unit, fontPx = 24f,
            bold = true,
            color = if (error != null) Color(0xFFB00020) else Color(0xFF111111),
            align = "e",
        )
    }
}

@Composable
private fun FittedLcdText(
    text: String,
    fullText: String?,
    left: Float,
    right: Float,
    centerY: Float,
    unit: Float,
    fontPx: Float,
    bold: Boolean,
    color: Color,
    align: String,
) {
    // Android-native result display.  The whole value is shown inside a
    // horizontally scrollable row that the user pans with a normal swipe; the
    // desktop's own viewport slice and offset are deliberately ignored, because
    // re-deriving that window with Compose metrics is what made panning look
    // like characters were being deleted.  A short result still hugs the right
    // edge (Arrangement.End) exactly like the calculator LCD.
    val body = (fullText ?: text).ifEmpty { " " }
    val fontScale = androidx.compose.ui.platform.LocalDensity.current.fontScale
    val height = (fontPx * unit * 2.4f)
    val scroll = rememberScrollState()
    Box(
        Modifier
            .offset(x = (left * unit).dp, y = ((centerY * unit) - height / 2f).dp)
            .size((((right - left) * unit)).dp, height.dp),
    ) {
        Row(
            Modifier
                .fillMaxSize()
                .horizontalScroll(scroll),
            horizontalArrangement = if (align == "e") Arrangement.End else Arrangement.Start,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                body,
                fontFamily = FontFamily.Monospace,
                fontSize = (fontPx * unit / fontScale).sp,
                fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal,
                color = color,
                maxLines = 1,
                softWrap = false,
            )
        }
    }
}

@Composable
private fun InputLcdText(
    text: String,
    left: Float,
    right: Float,
    centerY: Float,
    unit: Float,
    fontPx: Float,
    color: Color,
) {
    val fontScale = androidx.compose.ui.platform.LocalDensity.current.fontScale
    // 2.0x the font leaves headroom for tall glyphs (√, ∫, superscripts) so they
    // are not clipped by the fixed-height row.
    val height = (fontPx * unit * 2.0f)
    Box(
        Modifier
            .offset(x = (left * unit).dp, y = ((centerY * unit) - height / 2f).dp)
            .size((((right - left) * unit)).dp, height.dp),
        contentAlignment = Alignment.CenterEnd,
    ) {
        Text(
            text.ifEmpty { " " },
            fontFamily = FontFamily.Monospace,
            fontSize = (fontPx * unit / fontScale).sp,
            color = color,
            maxLines = 1,
            // The editable expression keeps its caret at the end, so the right
            // edge is authoritative: show it and ellipsize the hidden start.
            // Let Compose's own layout decide the cut instead of measuring by
            // hand, which had collapsed a long expression to a bare ellipsis.
            overflow = TextOverflow.StartEllipsis,
            textAlign = TextAlign.End,
        )
    }
}

@Composable
private fun LcdText(
    text: String,
    left: Float,
    right: Float,
    centerY: Float,
    unit: Float,
    fontPx: Float,
    bold: Boolean,
    color: Color,
    align: String,
    maxLines: Int = 1,
) {
    val density = androidx.compose.ui.platform.LocalDensity.current
    val fontScale = density.fontScale
    val fontSizeSp = (fontPx * unit / fontScale).coerceAtLeast(4f)
    // Match the expression/result rows: enough height for tall glyphs so the
    // status line and template results are never clipped in half.
    val height = (fontPx * unit * 2.0f)
    Box(
        Modifier
            .offset(x = (left * unit).dp, y = ((centerY * unit) - height / 2f).dp)
            .size((((right - left) * unit)).dp, height.dp),
        contentAlignment = when (align) {
            "w" -> Alignment.CenterStart
            "e" -> Alignment.CenterEnd
            else -> Alignment.Center
        },
    ) {
        Text(
            text.ifEmpty { " " },
            fontFamily = FontFamily.Monospace,
            fontSize = fontSizeSp.sp,
            fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal,
            color = color,
            maxLines = maxLines,
            overflow = TextOverflow.Ellipsis,
            textAlign = when (align) {
                "w" -> TextAlign.Start
                "e" -> TextAlign.End
                else -> TextAlign.Center
            },
        )
    }
}

@Composable
private fun TemplateCanvas(template: LcdTemplate, unit: Float, modifier: Modifier) {
    val measurer = rememberTextMeasurer()
    val density = androidx.compose.ui.platform.LocalDensity.current
    val fontScale = density.fontScale
    androidx.compose.foundation.Canvas(modifier) {
        val scaleX = if (template.width > 0f) size.width / template.width else 1f
        val scaleY = if (template.height > 0f) size.height / template.height else 1f
        for (item in template.items) {
            when (item.kind) {
                "rectangle" -> {
                    val left = item.x * scaleX
                    val top = item.y * scaleY
                    val right = item.x2 * scaleX
                    val bottom = item.y2 * scaleY
                    drawRect(
                        color = parseColor(item.fill, Color(0xFF222222)),
                        topLeft = Offset(left, top),
                        size = Size((right - left).coerceAtLeast(1f), (bottom - top).coerceAtLeast(1f)),
                        style = Stroke(width = (item.width * scaleY).coerceAtLeast(1f)),
                    )
                }
                "line" -> {
                    if (item.caretChars >= 0 && item.caretText.isNotEmpty()) {
                        // Place the caret with Compose's own metrics so it sits
                        // exactly on the glyph boundary the user sees.
                        val careStyle = TextStyle(
                            fontFamily = FontFamily.Monospace,
                            fontSize = (item.caretSize * unit / fontScale).sp,
                        )
                        val prefix = item.caretText.substring(0, item.caretChars.coerceIn(0, item.caretText.length))
                        val prefixWidth = if (prefix.isEmpty()) 0f
                        else measurer.measure(AnnotatedString(prefix), careStyle).size.width.toFloat()
                        val caretX = item.caretTextX * scaleX + prefixWidth
                        drawLine(
                            color = parseColor(item.fill, Color(0xFF111111)),
                            start = Offset(caretX, item.y * scaleY),
                            end = Offset(caretX, item.y2 * scaleY),
                            strokeWidth = (item.width * scaleY).coerceAtLeast(1f),
                        )
                    } else {
                        drawLine(
                            color = parseColor(item.fill, Color(0xFF111111)),
                            start = Offset(item.x * scaleX, item.y * scaleY),
                            end = Offset(item.x2 * scaleX, item.y2 * scaleY),
                            strokeWidth = (item.width * scaleY).coerceAtLeast(1f),
                        )
                    }
                }
                "text" -> drawItemText(measurer, item, scaleX, scaleY, unit)
            }
        }
    }
}

private fun parseColor(value: String, fallback: Color): Color {
    return try {
        if (value.startsWith("#") && value.length == 7) {
            Color(android.graphics.Color.parseColor(value))
        } else {
            fallback
        }
    } catch (e: IllegalArgumentException) {
        fallback
    }
}

private fun DrawScope.drawItemText(
    measurer: TextMeasurer,
    item: TemplateItem,
    scaleX: Float,
    scaleY: Float,
    unit: Float,
) {
    if (item.text.isEmpty()) return
    // item.size is the desktop pixel size at 100%.  Convert logical desktop
    // pixels to sp (accounting for font scale) so text stays proportional.
    val fontSizeSp = (item.size * unit / fontScale).coerceIn(4f, 200f)
    val measured = measurer.measure(
        AnnotatedString(item.text),
        style = TextStyle(
            fontFamily = FontFamily.Monospace,
            fontSize = fontSizeSp.sp,
        ),
    )
    val x = item.x * scaleX
    val y = item.y * scaleY
    val topLeft = when (item.anchor) {
        "w" -> Offset(x, y - measured.size.height / 2f)
        "e" -> Offset(x - measured.size.width, y - measured.size.height / 2f)
        else -> Offset(x - measured.size.width / 2f, y - measured.size.height / 2f)
    }
    drawText(measured, topLeft = topLeft)
}

@Composable
private fun ModeMenu(items: List<MenuItem>, onDismiss: () -> Unit, onSelect: (MenuItem) -> Unit) {
    var expanded by remember { mutableStateOf(true) }
    Box(Modifier.fillMaxSize()) {
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false; onDismiss() }) {
            items.forEach { item ->
                if (item.separator) {
                    HorizontalDivider()
                } else {
                    DropdownMenuItem(
                        text = { Text(item.label ?: "") },
                        onClick = { expanded = false; onSelect(item) },
                    )
                }
            }
        }
    }
}

// The Setup screen is the desktop SETUP Toplevel, serialized into
// LiveDialogWindow above; the skin choice now drives the native keypad palette.
