plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.chaquo.python")
}

android {
    namespace = "com.example.scicalc"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.scicalc"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
        // Python 3.12 builds of Chaquopy do not support 32-bit ABIs.
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    buildFeatures { compose = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    signingConfigs {
        getByName("debug") {
            // A checked-in debug key keeps the signature stable across machines
            // and CI runs.  With the default per-machine debug keystore every
            // freshly generated APK had a different signature, so a new release
            // could not be installed over the previous one.
            storeFile = file("scicalc-debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            // Chaquopy requires a predictable ProGuard configuration; minifying
            // is left off so reflection into the Python runtime stays simple.
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            // Chaquopy's wheel index has no SciPy build for Python 3.12, so the
            // app ships a pure-Python `scipy` compatibility shim in
            // app/src/main/python/scipy (backed by mpmath, a SymPy dependency).
            // See README.md and PORTING_NOTES.md (risk R1).
            install("numpy")
            install("mpmath")
            install("sympy==1.14.0")
        }
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.04.01"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
}
