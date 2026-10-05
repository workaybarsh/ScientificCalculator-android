// Versions: Chaquopy 17.0.0 supports AGP 8.9–8.13 (per its changelog). The other
// versions are conservative choices that I could not build here; let Android
// Studio's upgrade assistant bump them if it suggests newer ones.
plugins {
    id("com.android.application") version "8.9.1" apply false
    id("org.jetbrains.kotlin.android") version "2.1.20" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.1.20" apply false
    id("com.chaquo.python") version "17.0.0" apply false
}
