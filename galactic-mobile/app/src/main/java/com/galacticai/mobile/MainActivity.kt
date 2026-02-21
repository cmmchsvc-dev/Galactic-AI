package com.galacticai.mobile

import android.annotation.SuppressLint
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

/**
 * Main activity — hosts the Galactic-AI Control Deck WebView.
 * Full-screen, hardware-accelerated, landscape-locked.
 * Voice input is handled by the Control Deck web UI (mic button in the chat bar).
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var storage: SecureStorage
    private var biometricHelper: BiometricHelper? = null
    private var backPressedTime = 0L
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Fullscreen immersive
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).let { controller ->
            controller.hide(WindowInsetsCompat.Type.systemBars())
            controller.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.statusBarColor = 0xFF0a0b18.toInt()
        window.navigationBarColor = 0xFF04050d.toInt()

        storage = SecureStorage(this)
        webView = findViewById(R.id.webview)

        // Check biometric if enabled
        if (storage.biometricEnabled) {
            biometricHelper = BiometricHelper(this)
            webView.visibility = View.INVISIBLE
            biometricHelper?.authenticate(object : BiometricHelper.AuthCallback {
                override fun onSuccess() {
                    webView.visibility = View.VISIBLE
                    loadControlDeck()
                }
                override fun onFailure(message: String) {
                    Toast.makeText(this@MainActivity, message, Toast.LENGTH_SHORT).show()
                    finish()
                }
                override fun onNotAvailable() {
                    webView.visibility = View.VISIBLE
                    loadControlDeck()
                }
            })
        } else {
            loadControlDeck()
        }

        // Network change listener for WebSocket reconnect
        registerNetworkCallback()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun loadControlDeck() {
        if (!storage.isConfigured) {
            startActivity(Intent(this, ConnectActivity::class.java))
            finish()
            return
        }

        // Configure WebView
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            cacheMode = WebSettings.LOAD_DEFAULT
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false
            useWideViewPort = true
            loadWithOverviewMode = true
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = true
        }

        // Hardware acceleration for CRT effects
        webView.setLayerType(View.LAYER_TYPE_HARDWARE, null)

        webView.webViewClient = GalacticWebViewClient(
            storage,
            onPageLoaded = {
                // Page loaded successfully
            },
            onError = { message ->
                runOnUiThread {
                    Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
                }
            }
        )

        webView.webChromeClient = WebChromeClient()

        // Load the Control Deck
        webView.loadUrl(storage.buildBaseUrl())
    }

    private fun registerNetworkCallback() {
        val cm = getSystemService(CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()

        networkCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                // Network recovered — reload WebView to reconnect WebSocket
                runOnUiThread {
                    if (webView.url?.isNotBlank() == true) {
                        webView.reload()
                    }
                }
            }
            override fun onLost(network: Network) {
                // Network lost — WebSocket will disconnect, WebView shows error
            }
        }
        cm.registerNetworkCallback(request, networkCallback!!)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            if (System.currentTimeMillis() - backPressedTime < 2000) {
                super.onBackPressed()
            } else {
                backPressedTime = System.currentTimeMillis()
                Toast.makeText(this, "Press back again to exit", Toast.LENGTH_SHORT).show()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        webView.onResume()
    }

    override fun onPause() {
        super.onPause()
        webView.onPause()
    }

    override fun onDestroy() {
        networkCallback?.let {
            (getSystemService(CONNECTIVITY_SERVICE) as? ConnectivityManager)?.unregisterNetworkCallback(it)
        }
        webView.destroy()
        super.onDestroy()
    }
}
