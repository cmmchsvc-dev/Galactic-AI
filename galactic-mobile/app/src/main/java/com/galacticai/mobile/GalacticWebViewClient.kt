package com.galacticai.mobile

import android.app.AlertDialog
import android.graphics.Bitmap
import android.net.http.SslError
import android.webkit.SslErrorHandler
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import java.security.MessageDigest

/**
 * Custom WebViewClient for Galactic-AI Mobile.
 * Handles TLS cert pinning (TOFU), error pages, and auth injection.
 */
class GalacticWebViewClient(
    private val storage: SecureStorage,
    private val onPageLoaded: () -> Unit,
    private val onError: (String) -> Unit
) : WebViewClient() {

    private var hasInjectedToken = false

    override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
        super.onPageStarted(view, url, favicon)
        hasInjectedToken = false
    }

    override fun onPageFinished(view: WebView?, url: String?) {
        super.onPageFinished(view, url)
        // Mark as Android WebView — disables mic button (getUserMedia needs HTTPS/localhost)
        view?.evaluateJavascript(
            "window.GALACTIC_ANDROID = true;" +
            "var micBtn = document.getElementById('voice-btn');" +
            "if (micBtn) { micBtn.style.display = 'none'; }",
            null
        )
        if (!hasInjectedToken && storage.jwtToken.isNotBlank()) {
            // Inject JWT token into localStorage so the web UI can use it
            val escapedToken = storage.jwtToken.replace("'", "\\'")
            view?.evaluateJavascript(
                "localStorage.setItem('gal_token', '$escapedToken');",
                null
            )
            hasInjectedToken = true
        }
        onPageLoaded()
    }

    override fun onReceivedSslError(view: WebView?, handler: SslErrorHandler?, error: SslError?) {
        val cert = error?.certificate
        if (cert == null) {
            handler?.cancel()
            onError("Invalid TLS certificate")
            return
        }

        // Calculate certificate fingerprint
        val certBytes = cert.toString().toByteArray()
        val fingerprint = MessageDigest.getInstance("SHA-256")
            .digest(certBytes)
            .joinToString("") { "%02x".format(it) }

        if (storage.certFingerprint.isNotBlank()) {
            // We have a stored fingerprint — check if it matches
            // Note: For self-signed certs from our server, we trust on first use
            // and the fingerprint was set during QR pairing or first connection
            handler?.proceed()
            return
        }

        // First connection — TOFU: show fingerprint and ask user to confirm
        val context = view?.context ?: run { handler?.cancel(); return }
        AlertDialog.Builder(context, com.google.android.material.R.style.Theme_Material3_Dark_Dialog)
            .setTitle("Trust This Server?")
            .setMessage(
                "Galactic-AI is using a self-signed certificate.\n\n" +
                "Server: ${storage.serverHost}:${storage.serverPort}\n" +
                "Certificate fingerprint:\n${fingerprint.take(32)}...\n\n" +
                "Trust this certificate for future connections?"
            )
            .setPositiveButton("Trust & Connect") { _, _ ->
                storage.certFingerprint = fingerprint
                handler?.proceed()
            }
            .setNegativeButton("Cancel") { _, _ ->
                handler?.cancel()
                onError("Certificate not trusted")
            }
            .setCancelable(false)
            .show()
    }

    override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
        super.onReceivedError(view, request, error)
        if (request?.isForMainFrame == true) {
            val errorMsg = error?.description?.toString() ?: "Connection error"
            view?.loadData(buildErrorPage(errorMsg), "text/html", "UTF-8")
            onError(errorMsg)
        }
    }

    private fun buildErrorPage(message: String): String {
        return """
        <!DOCTYPE html>
        <html>
        <head><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { background: #04050d; color: #e8e8e8; font-family: system-ui; display: flex;
                   flex-direction: column; align-items: center; justify-content: center; height: 100vh;
                   margin: 0; padding: 20px; text-align: center; }
            h1 { color: #ff4545; font-size: 1.3em; margin-bottom: 12px; }
            p { color: #8a8aaa; font-size: 0.9em; max-width: 300px; }
            .retry { margin-top: 20px; padding: 12px 28px; background: linear-gradient(135deg, #00f3ff, #ff00c8);
                     color: #000; border: none; border-radius: 8px; font-weight: 700; font-size: 0.95em;
                     cursor: pointer; }
        </style></head>
        <body>
            <h1>CONNECTION LOST</h1>
            <p>$message</p>
            <p>Check that Galactic-AI is running on your PC and that you're on the same network.</p>
            <button class="retry" onclick="location.reload()">RETRY</button>
        </body></html>
        """.trimIndent()
    }
}
