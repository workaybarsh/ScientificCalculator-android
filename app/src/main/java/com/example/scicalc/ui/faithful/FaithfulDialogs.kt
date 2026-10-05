package com.example.scicalc.ui.faithful

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun PromptDialog(dialog: PendingDialog, onAnswer: (Any?) -> Unit, onDismiss: () -> Unit) {
    var text by remember(dialog.index) { mutableStateOf(dialog.initial?.toString() ?: "") }
    if (dialog.kind == "yesno") {
        AlertDialog(
            onDismissRequest = onDismiss,
            title = { if (dialog.title.isNotEmpty()) Text(dialog.title) },
            text = { Text(dialog.prompt.ifEmpty { "Are you sure?" }) },
            confirmButton = { TextButton(onClick = { onAnswer(true) }) { Text("Yes") } },
            dismissButton = { TextButton(onClick = { onAnswer(false) }) { Text("No") } },
        )
        return
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { if (dialog.title.isNotEmpty()) Text(dialog.title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (dialog.prompt.isNotEmpty()) Text(dialog.prompt)
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val parsed: Any? = when (dialog.kind) {
                    "float" -> text.trim().toDoubleOrNull()
                    "integer" -> text.trim().toIntOrNull()
                    else -> text
                }
                onAnswer(parsed)
            }) { Text("OK") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
fun InfoDialog(message: InfoMessage, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { if (message.title.isNotEmpty()) Text(message.title) },
        text = {
            Text(
                message.message,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
                modifier = Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()),
            )
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("OK") } },
    )
}

@Composable
fun LiveDialogWindow(
    dialog: LiveDialog,
    onInvoke: (widget: Int, action: String, value: Any?) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(dialog.title.ifEmpty { "Dialog" }) },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
        text = {
            Column(
                Modifier
                    .heightIn(max = 520.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                RenderNode(dialog.root, dialog.id, onInvoke, isRoot = true)
            }
        },
    )
}

@Composable
private fun RenderNode(
    node: DialogNode,
    dialogId: Int,
    onInvoke: (Int, String, Any?) -> Unit,
    isRoot: Boolean = false,
) {
    when (node.kind) {
        "Toplevel", "Frame" -> {
            if (!isRoot && node.children.isEmpty()) return
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                node.children.forEach { child -> RenderNode(child, dialogId, onInvoke) }
            }
        }
        "Label" -> {
            if (node.text.isNotEmpty()) Text(node.text, style = MaterialTheme.typography.bodyMedium)
        }
        "Button" -> {
            OutlinedButton(onClick = { onInvoke(node.id, "command", null) }, modifier = Modifier.fillMaxWidth()) {
                Text(node.text.ifEmpty { "Button" })
            }
        }
        "Entry" -> EntryNode(node, onInvoke)
        "Combobox" -> ComboBoxNode(node, onInvoke)
        "Listbox" -> ListBoxNode(node, onInvoke)
        else -> {
            if (node.text.isNotEmpty()) Text(node.text)
            node.children.forEach { child -> RenderNode(child, dialogId, onInvoke) }
        }
    }
}

@Composable
private fun EntryNode(node: DialogNode, onInvoke: (Int, String, Any?) -> Unit) {
    var value by remember(node.id) { mutableStateOf(node.value) }
    Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
        OutlinedTextField(
            value = value,
            onValueChange = { value = it; onInvoke(node.id, "set", it) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun ComboBoxNode(node: DialogNode, onInvoke: (Int, String, Any?) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    var current by remember(node.id) { mutableStateOf(node.value) }
    Box(Modifier.fillMaxWidth()) {
        OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) {
            Text(current.ifEmpty { node.values.firstOrNull() ?: "" })
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            node.values.forEach { option ->
                DropdownMenuItem(
                    text = { Text(option) },
                    onClick = {
                        expanded = false
                        current = option
                        onInvoke(node.id, "set", option)
                    },
                )
            }
        }
    }
}

@Composable
private fun ListBoxNode(node: DialogNode, onInvoke: (Int, String, Any?) -> Unit) {
    var selected by remember(node.id) { mutableStateOf(node.selection) }
    Column(
        Modifier
            .fillMaxWidth()
            .heightIn(max = 300.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        node.items.forEachIndexed { index, item ->
            val isSelected = index == selected
            Text(
                item,
                Modifier
                    .fillMaxWidth()
                    .clickable {
                        selected = index
                        onInvoke(node.id, "select", index)
                    }
                    .padding(vertical = 4.dp, horizontal = 4.dp),
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp,
                color = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
            )
            HorizontalDivider()
        }
    }
}
