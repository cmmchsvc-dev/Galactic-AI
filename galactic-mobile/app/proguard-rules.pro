# Galactic-AI Mobile ProGuard Rules
-keepattributes *Annotation*
-keep class com.galacticai.mobile.** { *; }
-keep class com.journeyapps.** { *; }
-dontwarn com.journeyapps.**

# Tink crypto (used by EncryptedSharedPreferences)
-dontwarn javax.annotation.Nullable
-dontwarn javax.annotation.concurrent.GuardedBy
