package com.example.scicalc

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.material3.MaterialTheme
import com.example.scicalc.ui.faithful.FaithfulScreen
import com.example.scicalc.ui.faithful.FaithfulViewModel

class MainActivity : ComponentActivity() {
    private val vm: FaithfulViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        // Draw edge-to-edge consistently on every Android version.  The Compose
        // layer insets the calculator by the system bars and display cutout, so
        // the top status row is never hidden behind the status bar or a notch.
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                // SHIFT + AC is the calculator's OFF: close and drop the task so
                // a later launch starts clean instead of re-entering a finished
                // activity (the Python OFF latch is cleared on every ui_start).
                FaithfulScreen(vm, onPowerOff = { finishAndRemoveTask() })
            }
        }
    }
}
