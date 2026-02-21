package com.galacticai.mobile

import android.animation.ObjectAnimator
import android.animation.PropertyValuesHolder
import android.annotation.SuppressLint
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

/**
 * Splash screen with animated Galactic-AI branding.
 * Routes to ConnectActivity (first launch) or MainActivity (configured).
 */
@SuppressLint("CustomSplashScreen")
class SplashActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_splash)

        // Fullscreen immersive
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).let { controller ->
            controller.hide(WindowInsetsCompat.Type.systemBars())
            controller.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // Animate the title with a pulse/glow effect
        val titleView = findViewById<TextView>(R.id.splash_title)
        val subtitleView = findViewById<TextView>(R.id.splash_subtitle)

        titleView?.let {
            val pulse = ObjectAnimator.ofPropertyValuesHolder(
                it,
                PropertyValuesHolder.ofFloat(View.ALPHA, 0.6f, 1f),
                PropertyValuesHolder.ofFloat(View.SCALE_X, 0.95f, 1.02f),
                PropertyValuesHolder.ofFloat(View.SCALE_Y, 0.95f, 1.02f)
            )
            pulse.duration = 1200
            pulse.repeatCount = ObjectAnimator.INFINITE
            pulse.repeatMode = ObjectAnimator.REVERSE
            pulse.start()
        }

        subtitleView?.let {
            it.alpha = 0f
            it.animate().alpha(1f).setDuration(800).setStartDelay(400).start()
        }

        // Navigate after 2 seconds
        Handler(Looper.getMainLooper()).postDelayed({
            val storage = SecureStorage(this)
            val intent = if (storage.isConfigured && storage.isTokenValid) {
                Intent(this, MainActivity::class.java)
            } else {
                Intent(this, ConnectActivity::class.java)
            }
            startActivity(intent)
            finish()
            overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
        }, 2000)
    }
}
