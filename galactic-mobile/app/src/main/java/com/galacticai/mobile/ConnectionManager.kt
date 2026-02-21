package com.galacticai.mobile

import android.os.Handler
import android.os.Looper
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * Manages connection to the Galactic-AI server.
 * Handles health checks, login, and auto-reconnect with exponential backoff.
 */
class ConnectionManager(private val storage: SecureStorage) {

    interface ConnectionCallback {
        fun onConnected(token: String, expires: Long)
        fun onError(message: String)
        fun onHealthCheck(online: Boolean, model: String?)
    }

    private val handler = Handler(Looper.getMainLooper())
    private var reconnectDelay = 1000L
    private val maxReconnectDelay = 30000L

    /**
     * Attempt login to the server with the given password.
     * Runs on a background thread, callbacks on main thread.
     */
    fun login(host: String, port: Int, useHttps: Boolean, password: String, callback: ConnectionCallback) {
        Thread {
            try {
                val protocol = if (useHttps) "https" else "http"
                val url = URL("$protocol://$host:$port/login")
                val conn = openConnection(url)
                conn.requestMethod = "POST"
                conn.setRequestProperty("Content-Type", "application/json")
                conn.doOutput = true
                conn.connectTimeout = 10000
                conn.readTimeout = 10000

                val body = """{"password":"${password.replace("\"", "\\\"")}"}"""
                conn.outputStream.use { it.write(body.toByteArray()) }

                val responseCode = conn.responseCode
                val response = if (responseCode in 200..299) {
                    conn.inputStream.bufferedReader().readText()
                } else {
                    conn.errorStream?.bufferedReader()?.readText() ?: "Unknown error"
                }

                if (responseCode == 200 && (response.contains("\"success\":true") || response.contains("\"success\": true"))) {
                    // Parse token and expiry from JSON response
                    val token = extractJsonString(response, "token") ?: ""
                    val expires = extractJsonLong(response, "expires")

                    handler.post { callback.onConnected(token, expires) }
                } else {
                    val error = extractJsonString(response, "error") ?: "Login failed (HTTP $responseCode)"
                    handler.post { callback.onError(error) }
                }
            } catch (e: Exception) {
                handler.post { callback.onError("Connection failed: ${e.message}") }
            }
        }.start()
    }

    /**
     * Check server health via GET /api/status.
     */
    fun healthCheck(callback: ConnectionCallback) {
        Thread {
            try {
                val url = URL("${storage.buildBaseUrl()}/api/status")
                val conn = openConnection(url)
                conn.requestMethod = "GET"
                conn.setRequestProperty("Authorization", "Bearer ${storage.jwtToken}")
                conn.connectTimeout = 5000
                conn.readTimeout = 5000

                val responseCode = conn.responseCode
                if (responseCode == 200) {
                    val response = conn.inputStream.bufferedReader().readText()
                    val model = extractJsonString(response, "model")
                    handler.post { callback.onHealthCheck(true, model) }
                } else {
                    handler.post { callback.onHealthCheck(false, null) }
                }
            } catch (e: Exception) {
                handler.post { callback.onHealthCheck(false, null) }
            }
        }.start()
    }

    /**
     * Open a connection, trusting self-signed certs for Galactic-AI servers.
     */
    private fun openConnection(url: URL): HttpURLConnection {
        val conn = url.openConnection() as HttpURLConnection
        if (conn is HttpsURLConnection) {
            // Trust self-signed certificates (TOFU model — verified by fingerprint)
            val trustAllCerts = arrayOf<TrustManager>(object : X509TrustManager {
                override fun checkClientTrusted(chain: Array<java.security.cert.X509Certificate>, authType: String) {}
                override fun checkServerTrusted(chain: Array<java.security.cert.X509Certificate>, authType: String) {
                    // If we have a stored fingerprint, verify it matches
                    if (storage.certFingerprint.isNotBlank() && chain.isNotEmpty()) {
                        val serverFp = chain[0].encoded.let {
                            java.security.MessageDigest.getInstance("SHA-256").digest(it)
                                .joinToString("") { byte -> "%02x".format(byte) }
                        }
                        if (serverFp != storage.certFingerprint) {
                            throw javax.net.ssl.SSLException(
                                "Certificate fingerprint mismatch! Expected: ${storage.certFingerprint.take(16)}..., got: ${serverFp.take(16)}..."
                            )
                        }
                    }
                }
                override fun getAcceptedIssuers(): Array<java.security.cert.X509Certificate> = arrayOf()
            })

            val sslContext = SSLContext.getInstance("TLS")
            sslContext.init(null, trustAllCerts, java.security.SecureRandom())
            conn.sslSocketFactory = sslContext.socketFactory
            conn.hostnameVerifier = javax.net.ssl.HostnameVerifier { _, _ -> true }
        }
        return conn
    }

    fun resetReconnectDelay() {
        reconnectDelay = 1000L
    }

    fun getNextReconnectDelay(): Long {
        val delay = reconnectDelay
        reconnectDelay = (reconnectDelay * 2).coerceAtMost(maxReconnectDelay)
        return delay
    }

    private fun extractJsonString(json: String, key: String): String? {
        val pattern = """"$key"\s*:\s*"([^"]*?)"""".toRegex()
        return pattern.find(json)?.groupValues?.get(1)
    }

    private fun extractJsonLong(json: String, key: String): Long {
        val pattern = """"$key"\s*:\s*(\d+)""".toRegex()
        return pattern.find(json)?.groupValues?.get(1)?.toLongOrNull() ?: 0L
    }
}
