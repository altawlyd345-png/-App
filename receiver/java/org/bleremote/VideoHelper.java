package org.bleremote;

import android.app.Activity;
import android.graphics.Color;
import android.media.MediaPlayer;
import android.view.Gravity;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.VideoView;

public class VideoHelper {
    static FrameLayout root;
    static VideoView vv;

    public static void keepOn(final Activity a) {
        a.runOnUiThread(new Runnable() {
            public void run() { a.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON); }
        });
    }

    static void hideNow() {
        try {
            if (vv != null) vv.stopPlayback();
            if (root != null && root.getParent() != null) ((ViewGroup) root.getParent()).removeView(root);
        } catch (Exception e) { }
        root = null;
        vv = null;
    }

    public static void hide(final Activity a) {
        a.runOnUiThread(new Runnable() { public void run() { hideNow(); } });
    }

    /** Full-screen video with an optional native text overlay (Android shapes Arabic natively). */
    public static void show(final Activity a, final String path, final String text, final String color,
                            final float sp, final boolean loop) {
        a.runOnUiThread(new Runnable() {
            public void run() {
                hideNow();
                root = new FrameLayout(a);
                root.setBackgroundColor(Color.BLACK);
                final VideoView v = new VideoView(a);
                vv = v;
                root.addView(v, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
                if (text != null && text.length() > 0) {
                    TextView tv = new TextView(a);
                    tv.setText(text);
                    tv.setTextColor(Color.parseColor(color));
                    tv.setTextSize(sp);
                    tv.setGravity(Gravity.CENTER);
                    tv.setShadowLayer(6, 2, 2, Color.BLACK);
                    root.addView(tv, new FrameLayout.LayoutParams(-1, -1));
                }
                a.addContentView(root, new ViewGroup.LayoutParams(-1, -1));
                v.setOnPreparedListener(new MediaPlayer.OnPreparedListener() {
                    public void onPrepared(MediaPlayer mp) { mp.setLooping(loop); v.start(); }
                });
                v.setVideoPath(path);
            }
        });
    }
}
