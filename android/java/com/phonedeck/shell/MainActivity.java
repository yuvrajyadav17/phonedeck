package com.phonedeck.shell;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.pm.PackageManager;
import android.content.DialogInterface;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JsResult;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

/**
 * PhoneDeck shell.
 *
 * A deliberately thin wrapper: the entire interface is the web dashboard the
 * PC serves. Keeping the UI in HTML means layout changes need a file save, not
 * a rebuild and reinstall.
 *
 * The three things this class exists to do -- and that a plain browser cannot
 * do on Android 9 -- are: stay on top of the lock screen, keep the display
 * awake, and recover on its own when the USB link drops.
 */
public class MainActivity extends Activity {

    /**
     * Reached through the `adb reverse` tunnel the PC sets up, so this
     * loopback address resolves to the PC's server, not the phone.
     */
    private static final String HOST = "http://127.0.0.1:8770";
    private static final long RETRY_DELAY_MS = 2500L;

    private WebView web;
    private TextView banner;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean pageLoaded = false;
    /** The last load ended on the WebView's error page. */
    private boolean loadFailed = false;
    private Runnable pendingRetry;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        showOverLockScreen();
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0b0f16"));

        web = new WebView(this);
        configureWebView(web);
        root.addView(web, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        banner = new TextView(this);
        banner.setTextColor(Color.parseColor("#8394ab"));
        banner.setBackgroundColor(Color.parseColor("#0b0f16"));
        banner.setGravity(Gravity.CENTER);
        banner.setTextSize(15f);
        banner.setLineSpacing(0f, 1.3f);
        banner.setText("Connecting to your PC…");
        root.addView(banner, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        // Tapping the failure message forces an immediate retry rather than
        // waiting out the timer.
        banner.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { load(); }
        });

        setContentView(root);
        requestMicPermission();
        load();
    }

    /**
     * Android needs the microphone granted twice over: once by the user for
     * the app, and again by the app for the WebView (see onPermissionRequest).
     * Asking here means the prompt is out of the way before dictation is
     * first used, rather than mid-sentence.
     */
    private void requestMicPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                   != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
        }
    }

    /**
     * Ask the window manager to display this activity above the keyguard and
     * to wake the panel. This is the capability a normal browser cannot offer,
     * and the reason the PC can bring the dashboard up unattended at boot.
     */
    private void showOverLockScreen() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                            | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }
    }

    /**
     * Exposes this WebView to Chrome DevTools over adb. Worth keeping on: the
     * dashboard is the whole interface, and without it the only way to inspect
     * a layout or scripting problem on the device is guesswork.
     */
    private static final boolean WEB_DEBUGGING = true;

    private void configureWebView(WebView view) {
        if (WEB_DEBUGGING) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(true);
        // The dashboard remembers its auth token in localStorage; without DOM
        // storage every launch would look unauthorised.
        settings.setDomStorageEnabled(true);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMediaPlaybackRequiresUserGesture(false);

        view.setBackgroundColor(Color.parseColor("#0b0f16"));
        view.setOverScrollMode(View.OVER_SCROLL_NEVER);
        // A long press would otherwise pop the text-selection menu over a
        // button, which is never what you want on a control surface.
        view.setLongClickable(false);
        view.setHapticFeedbackEnabled(false);

        // Without a WebChromeClient, Android's WebView answers every
        // window.confirm() with false and never shows anything -- so a
        // confirmed button (shut down, close everything) would silently do
        // nothing. These two handlers are what make those dialogs real.
        view.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                // The page only ever asks for the microphone, and only when
                // the dictation button is pressed. Without this the WebView
                // denies getUserMedia outright and says nothing.
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        request.grant(request.getResources());
                    }
                });
            }

            @Override
            public boolean onJsConfirm(WebView v, String url, String message,
                                       final JsResult result) {
                new AlertDialog.Builder(MainActivity.this)
                        .setMessage(message)
                        .setPositiveButton(android.R.string.ok,
                                new DialogInterface.OnClickListener() {
                                    @Override
                                    public void onClick(DialogInterface d, int w) {
                                        result.confirm();
                                    }
                                })
                        .setNegativeButton(android.R.string.cancel,
                                new DialogInterface.OnClickListener() {
                                    @Override
                                    public void onClick(DialogInterface d, int w) {
                                        result.cancel();
                                    }
                                })
                        .setOnCancelListener(
                                new DialogInterface.OnCancelListener() {
                                    @Override
                                    public void onCancel(DialogInterface d) {
                                        result.cancel();
                                    }
                                })
                        .show();
                return true;
            }

            @Override
            public boolean onJsAlert(WebView v, String url, String message,
                                     final JsResult result) {
                new AlertDialog.Builder(MainActivity.this)
                        .setMessage(message)
                        .setPositiveButton(android.R.string.ok,
                                new DialogInterface.OnClickListener() {
                                    @Override
                                    public void onClick(DialogInterface d, int w) {
                                        result.confirm();
                                    }
                                })
                        .setOnCancelListener(
                                new DialogInterface.OnCancelListener() {
                                    @Override
                                    public void onCancel(DialogInterface d) {
                                        result.cancel();
                                    }
                                })
                        .show();
                return true;
            }
        });

        view.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView v, String url) {
                // The WebView fires this for its *own* error page as well, so
                // "finished" alone does not mean "loaded". Trusting it here
                // marked a failed load as successful, which stopped the retry
                // timer and left the app stranded on "Webpage not available"
                // for good -- even after the PC came back.
                if (loadFailed) {
                    scheduleRetry();
                    return;
                }
                pageLoaded = true;
                banner.setVisibility(View.GONE);
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest request,
                                        WebResourceError error) {
                // Sub-resource failures are noise; only a failed main document
                // means we are actually disconnected.
                if (request != null && request.isForMainFrame()) {
                    loadFailed = true;
                    showDisconnected();
                }
            }
        });
    }

    private void load() {
        cancelRetry();
        loadFailed = false;
        banner.setText("Connecting to your PC…");
        banner.setVisibility(View.VISIBLE);
        web.loadUrl(HOST + "/?t=" + getString(R.string.pd_token));
    }

    private void showDisconnected() {
        pageLoaded = false;
        banner.setText("Waiting for the PC…\n\n"
                + "Check the USB cable is connected\nand PhoneDeck is running.\n\n"
                + "Tap to retry now.");
        banner.setVisibility(View.VISIBLE);
        scheduleRetry();
    }

    private void scheduleRetry() {
        cancelRetry();
        pendingRetry = new Runnable() {
            @Override public void run() {
                pendingRetry = null;
                if (!pageLoaded || loadFailed) {
                    loadFailed = false;
                    web.loadUrl(HOST + "/?t=" + getString(R.string.pd_token));
                }
            }
        };
        handler.postDelayed(pendingRetry, RETRY_DELAY_MS);
    }

    private void cancelRetry() {
        if (pendingRetry != null) {
            handler.removeCallbacks(pendingRetry);
            pendingRetry = null;
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        goImmersive();
        // The PC relaunches us whenever the cable is reconnected; if the last
        // attempt had failed, take the opportunity to try again.
        if (!pageLoaded) {
            load();
        }
    }

    /** Hide the status and navigation bars so the dashboard owns the panel. */
    private void goImmersive() {
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            goImmersive();
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        // Back closes the shortcut drawer rather than leaving the app -- on an
        // appliance, backing out to the launcher is almost never intended.
        if (keyCode == KeyEvent.KEYCODE_BACK && pageLoaded) {
            web.evaluateJavascript(
                    "(function(){var d=document.getElementById('drawer');"
                            + "if(d&&!d.hidden){d.hidden=true;return 'closed';}"
                            + "return 'none';})()", null);
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onDestroy() {
        cancelRetry();
        if (web != null) {
            web.destroy();
        }
        super.onDestroy();
    }
}
