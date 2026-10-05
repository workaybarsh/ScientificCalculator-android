package com.example.scicalc

import com.chaquo.python.PyObject
import com.chaquo.python.Python
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

/** One display row of the shared calculation history. */
data class HistoryEntry(val expression: String, val result: String)

/**
 * The full JSON result of one bridge call.  `raw` still holds every extra field
 * (matrix data, statistics map, conversion catalogue, spreadsheet snapshot) for
 * callers that need structured values; `text` is always the ready-to-display
 * string.
 */
data class CalcResult(
    val ok: Boolean,
    val text: String = "",
    val error: String = "",
    val history: List<HistoryEntry> = emptyList(),
    val raw: JSONObject? = null,
)

/**
 * Kotlin side of android_bridge.py.  Calls run on ONE dedicated thread because
 * the Python engine is stateful.  On timeout we ask Python to interrupt that
 * thread via cancel(); the engine commits state only after a call succeeds, so
 * a cancelled call leaves Ans/history unchanged.
 */
object PythonBridge {
    private val module: PyObject by lazy { Python.getInstance().getModule("android_bridge") }

    private val dispatcher: CoroutineDispatcher =
        Executors.newSingleThreadExecutor { runnable ->
            Thread(null, runnable, "py-engine", 32L * 1024 * 1024)
        }.asCoroutineDispatcher()

    /** Point the engine at the app's private data directory and load saved state. */
    suspend fun configure(path: String): CalcResult =
        invoke("configure", JSONObject().put("path", path))

    /** Warm up the Python interpreter and the engine imports on a background thread. */
    suspend fun warmup(): CalcResult = invoke("ping", JSONObject())

    suspend fun call(op: String, args: JSONObject = JSONObject(), timeoutMs: Long = 30_000): CalcResult =
        invoke(op, args, timeoutMs)

    private suspend fun invoke(op: String, args: JSONObject, timeoutMs: Long = 30_000): CalcResult =
        coroutineScope {
            // `job` is a sibling of the timeout block, so a timeout cancels only
            // the await and the Python thread is interrupted by cancel() below.
            val job = async(dispatcher) { module.callAttr("call", op, args.toString()).toString() }
            val raw = withTimeoutOrNull(timeoutMs) { job.await() } ?: run {
                module.callAttr("cancel")
                job.await()
            }
            parse(raw)
        }

    /** User-initiated cancel (AC while busy). Safe to call from any thread. */
    fun cancel() {
        module.callAttr("cancel")
    }

    private fun parse(raw: String): CalcResult {
        val o = JSONObject(raw)
        if (!o.getBoolean("ok")) {
            return CalcResult(false, error = o.optString("error", "Internal ERROR"), raw = o)
        }
        return CalcResult(
            ok = true,
            text = o.optString("text"),
            history = parseHistory(o.optJSONArray("history")),
            raw = o,
        )
    }

    private fun parseHistory(array: JSONArray?): List<HistoryEntry> {
        if (array == null) return emptyList()
        return (0 until array.length()).map { index ->
            val entry = array.getJSONObject(index)
            HistoryEntry(entry.getString("expression"), entry.getString("result"))
        }
    }
}
