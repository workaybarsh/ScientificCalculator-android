package com.example.scicalc.ui.faithful

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import com.example.scicalc.CalcResult
import com.example.scicalc.PythonBridge
import org.json.JSONArray
import org.json.JSONObject

data class TemplateItem(
    val kind: String,
    val x: Float,
    val y: Float,
    val x2: Float,
    val y2: Float,
    val text: String,
    val anchor: String,
    val font: String,
    val size: Int,
    val fill: String,
    val width: Float,
    val caretChars: Int,
    val caretTextX: Float,
    val caretText: String,
    val caretSize: Int,
)

data class LcdTemplate(
    val kind: String,
    val items: List<TemplateItem>,
    val width: Float,
    val height: Float,
)

data class MenuItem(val label: String?, val separator: Boolean, val index: Int, val path: List<Int>)

data class DialogNode(
    val id: Int,
    val kind: String,
    val text: String,
    val values: List<String>,
    val value: String,
    val items: List<String>,
    val selection: Int,
    val editable: Boolean,
    val command: Boolean,
    val children: List<DialogNode>,
)

data class LiveDialog(val id: Int, val title: String, val root: DialogNode)

data class PendingDialog(
    val kind: String,
    val title: String,
    val prompt: String,
    val initial: Any?,
    val index: Int,
)

data class InfoMessage(val kind: String, val title: String, val message: String)

data class UiSnapshot(
    val mode: String = "Calculate",
    val angleUnit: String = "RAD",
    val base: Int = 10,
    val shift: Boolean = false,
    val alpha: Boolean = false,
    val status: String = "",
    val expr: String = "",
    val result: String = "0",
    val resultFull: String? = null,
    val resultOffset: Int = 0,
    val powerOff: Boolean = false,
    val hint: String = "",
    val skin: String = "Graphite",
    val template: LcdTemplate? = null,
    val menu: List<MenuItem>? = null,
    val dialog: PendingDialog? = null,
    val dialogs: List<LiveDialog> = emptyList(),
    val info: List<InfoMessage> = emptyList(),
)

data class FaithfulState(
    val ready: Boolean = false,
    val snapshot: UiSnapshot = UiSnapshot(),
    val error: String? = null,
)

/** Drives the real desktop App headlessly through the ui_* bridge operations. */
class FaithfulViewModel(app: Application) : AndroidViewModel(app) {
    private val _state = MutableStateFlow(FaithfulState())
    val state: StateFlow<FaithfulState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            val result = PythonBridge.call("ui_start", JSONObject().put("path", app.filesDir.absolutePath))
            if (result.ok) {
                _state.update { it.copy(ready = true, snapshot = parse(result.raw?.optJSONObject("snapshot"))) }
            } else {
                _state.update { it.copy(ready = true, error = result.error) }
            }
        }
    }

    fun press(key: String) {
        if (!_state.value.ready) return
        viewModelScope.launch {
            val result = PythonBridge.call("ui_press", JSONObject().put("key", key))
            publish(result)
        }
    }

    fun menuSelect(path: List<Int>) {
        viewModelScope.launch {
            val args = JSONObject().put("path", JSONArray(path))
            publish(PythonBridge.call("ui_menu_select", args))
        }
    }

    fun setAngle(unit: String) {
        viewModelScope.launch {
            publish(PythonBridge.call("ui_set_angle", JSONObject().put("unit", unit)))
        }
    }

    fun setSkin(skin: String) {
        viewModelScope.launch {
            publish(PythonBridge.call("ui_set_skin", JSONObject().put("skin", skin)))
        }
    }

    fun clearAll() {
        viewModelScope.launch { publish(PythonBridge.call("ui_clear")) }
    }

    fun answerDialog(value: Any?) {
        viewModelScope.launch {
            publish(PythonBridge.call("ui_dialog_answer", JSONObject().put("value", value)))
        }
    }

    fun invokeDialog(dialog: Int, widget: Int, action: String = "command", value: Any? = null) {
        viewModelScope.launch {
            val args = JSONObject().put("dialog", dialog).put("widget", widget).put("action", action)
            if (value != null) args.put("value", value)
            publish(PythonBridge.call("ui_dialog_invoke", args))
        }
    }

    fun dismissInfo() {
        viewModelScope.launch { publish(PythonBridge.call("ui_dialog_dismiss")) }
    }

    fun closeAllDialogs() {
        viewModelScope.launch { publish(PythonBridge.call("ui_dialog_close_all")) }
    }

    private fun publish(result: CalcResult) {
        if (result.ok) {
            _state.update { it.copy(snapshot = parse(result.raw?.optJSONObject("snapshot")), error = null) }
        } else {
            _state.update { it.copy(error = result.error) }
        }
    }

    private fun parse(json: JSONObject?): UiSnapshot {
        if (json == null) return UiSnapshot()
        return UiSnapshot(
            mode = json.optString("mode", "Calculate"),
            angleUnit = json.optString("angleUnit", "RAD"),
            base = json.optInt("base", 10),
            shift = json.optBoolean("shift", false),
            alpha = json.optBoolean("alpha", false),
            status = json.optString("status"),
            expr = json.optString("expr"),
            result = json.optString("result"),
            resultFull = if (json.isNull("resultFull")) null else json.optString("resultFull"),
            resultOffset = json.optInt("resultOffset", 0),
            powerOff = json.optBoolean("powerOff", false),
            hint = json.optString("hint"),
            skin = json.optString("skin", "Graphite"),
            template = parseTemplate(json.optJSONObject("template")),
            menu = parseMenu(json.optJSONArray("menu")),
            dialog = parsePending(json.optJSONObject("dialog")),
            dialogs = parseDialogs(json.optJSONArray("dialogs")),
            info = parseInfo(json.optJSONArray("info")),
        )
    }

    private fun parsePending(json: JSONObject?): PendingDialog? {
        if (json == null) return null
        return PendingDialog(
            kind = json.optString("kind"),
            title = json.optString("title"),
            prompt = json.optString("prompt"),
            initial = if (json.isNull("initial")) null else json.opt("initial"),
            index = json.optInt("index", 0),
        )
    }

    private fun parseDialogs(array: JSONArray?): List<LiveDialog> {
        if (array == null) return emptyList()
        return (0 until array.length()).map { index ->
            val item = array.getJSONObject(index)
            LiveDialog(
                id = item.optInt("id"),
                title = item.optString("title"),
                root = parseNode(item.getJSONObject("root")),
            )
        }
    }

    private fun parseNode(json: JSONObject): DialogNode {
        val values = ArrayList<String>()
        json.optJSONArray("values")?.let { array -> for (i in 0 until array.length()) values.add(array.optString(i)) }
        val items = ArrayList<String>()
        json.optJSONArray("items")?.let { array -> for (i in 0 until array.length()) items.add(array.optString(i)) }
        val children = ArrayList<DialogNode>()
        json.optJSONArray("children")?.let { array ->
            for (i in 0 until array.length()) children.add(parseNode(array.getJSONObject(i)))
        }
        return DialogNode(
            id = json.optInt("id"),
            kind = json.optString("kind"),
            text = json.optString("text"),
            values = values,
            value = json.optString("value"),
            items = items,
            selection = if (json.isNull("selection")) -1 else json.optInt("selection", -1),
            editable = json.optBoolean("editable", false),
            command = json.optBoolean("command", false),
            children = children,
        )
    }

    private fun parseInfo(array: JSONArray?): List<InfoMessage> {
        if (array == null) return emptyList()
        return (0 until array.length()).map { index ->
            val item = array.getJSONObject(index)
            InfoMessage(
                kind = item.optString("kind"),
                title = item.optString("title"),
                message = item.optString("message"),
            )
        }
    }

    private fun parseTemplate(json: JSONObject?): LcdTemplate? {
        if (json == null) return null
        val canvas = json.optJSONObject("canvas")
        val items = ArrayList<TemplateItem>()
        val array: JSONArray = json.optJSONArray("items") ?: JSONArray()
        for (index in 0 until array.length()) {
            val item = array.getJSONObject(index)
            items.add(
                TemplateItem(
                    kind = item.optString("kind"),
                    x = item.optDouble("x", 0.0).toFloat(),
                    y = item.optDouble("y", 0.0).toFloat(),
                    x2 = item.optDouble("x2", 0.0).toFloat(),
                    y2 = item.optDouble("y2", 0.0).toFloat(),
                    text = item.optString("text"),
                    anchor = item.optString("anchor", "center"),
                    font = item.optString("font", "Monospace"),
                    size = item.optInt("size", 12),
                    fill = item.optString("fill", "#111111"),
                    width = item.optDouble("width", 1.0).toFloat(),
                    caretChars = item.optInt("caretChars", -1),
                    caretTextX = item.optDouble("caretTextX", item.optDouble("x", 0.0)).toFloat(),
                    caretText = item.optString("caretText", ""),
                    caretSize = item.optInt("caretSize", item.optInt("size", 12)),
                ),
            )
        }
        return LcdTemplate(
            kind = json.optString("kind"),
            items = items,
            width = (canvas?.optDouble("width", 381.0) ?: 381.0).toFloat(),
            height = (canvas?.optDouble("height", 58.0) ?: 58.0).toFloat(),
        )
    }

    private fun parseMenu(array: JSONArray?): List<MenuItem>? {
        if (array == null) return null
        return (0 until array.length()).map { index ->
            val item = array.getJSONObject(index)
            val pathArray = item.optJSONArray("path")
            val path = if (pathArray == null) emptyList()
            else (0 until pathArray.length()).map { pathArray.optInt(it) }
            MenuItem(
                label = if (item.isNull("label")) null else item.optString("label"),
                separator = item.optBoolean("separator", false),
                index = item.optInt("index", index),
                path = path,
            )
        }
    }
}
