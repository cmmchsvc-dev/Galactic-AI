package com.galacticai.mobile

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Encrypted credential storage backed by Android Keystore (AES-256-GCM).
 * Stores server URL, JWT token, cert fingerprint, and user preferences.
 */
class SecureStorage(context: Context) {

    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        context,
        "galactic_secure_prefs",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    var serverHost: String
        get() = prefs.getString(KEY_HOST, "") ?: ""
        set(value) = prefs.edit().putString(KEY_HOST, value).apply()

    var serverPort: Int
        get() = prefs.getInt(KEY_PORT, 17789)
        set(value) = prefs.edit().putInt(KEY_PORT, value).apply()

    var useHttps: Boolean
        get() = prefs.getBoolean(KEY_HTTPS, true)
        set(value) = prefs.edit().putBoolean(KEY_HTTPS, value).apply()

    var jwtToken: String
        get() = prefs.getString(KEY_TOKEN, "") ?: ""
        set(value) = prefs.edit().putString(KEY_TOKEN, value).apply()

    var tokenExpiry: Long
        get() = prefs.getLong(KEY_EXPIRY, 0)
        set(value) = prefs.edit().putLong(KEY_EXPIRY, value).apply()

    var certFingerprint: String
        get() = prefs.getString(KEY_CERT_FP, "") ?: ""
        set(value) = prefs.edit().putString(KEY_CERT_FP, value).apply()

    var biometricEnabled: Boolean
        get() = prefs.getBoolean(KEY_BIOMETRIC, false)
        set(value) = prefs.edit().putBoolean(KEY_BIOMETRIC, value).apply()

    var autoSpeak: Boolean
        get() = prefs.getBoolean(KEY_AUTO_SPEAK, false)
        set(value) = prefs.edit().putBoolean(KEY_AUTO_SPEAK, value).apply()

    val isConfigured: Boolean
        get() = serverHost.isNotBlank() && jwtToken.isNotBlank()

    val isTokenValid: Boolean
        get() = jwtToken.isNotBlank() && (tokenExpiry == 0L || tokenExpiry > System.currentTimeMillis() / 1000)

    fun buildBaseUrl(): String {
        val protocol = if (useHttps) "https" else "http"
        return "$protocol://$serverHost:$serverPort"
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val KEY_HOST = "server_host"
        private const val KEY_PORT = "server_port"
        private const val KEY_HTTPS = "use_https"
        private const val KEY_TOKEN = "jwt_token"
        private const val KEY_EXPIRY = "token_expiry"
        private const val KEY_CERT_FP = "cert_fingerprint"
        private const val KEY_BIOMETRIC = "biometric_enabled"
        private const val KEY_AUTO_SPEAK = "auto_speak"
    }
}
