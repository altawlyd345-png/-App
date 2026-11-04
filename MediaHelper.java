package org.bleremote;

import android.app.Activity;
import android.content.ContentUris;
import android.content.Context;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Build;
import android.provider.MediaStore;
import android.provider.OpenableColumns;
import android.util.Size;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.VideoView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.Collections;

/** Shared helper (Sender + Receiver): files, gallery, audio, video, network. */
public class MediaHelper {
    static MediaPlayer audio;
    static View videoHolder;

    public static String localIp() {
        try {
            String best = "";
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InetAddress a : Collections.list(ni.getInetAddresses())) {
                    if (a instanceof Inet4Address && !a.isLoopbackAddress()) {
                        String n = ni.getName();
                        String ip = a.getHostAddress();
                        if (n.startsWith("wlan") || n.startsWith("ap") || n.startsWith("swlan")) return ip;
                        if (best.isEmpty()) best = ip;
                    }
                }
            }
            return best;
        } catch (Exception e) { return ""; }
    }

    public static String listMedia(Context c) {
        JSONArray out = new JSONArray();
        add(c, out, MediaStore.Images.Media.EXTERNAL_CONTENT_URI, "image",
            MediaStore.Images.Media.DISPLAY_NAME, MediaStore.Images.Media.DATE_ADDED, MediaStore.Images.Media.SIZE);
        add(c, out, MediaStore.Video.Media.EXTERNAL_CONTENT_URI, "video",
            MediaStore.Video.Media.DISPLAY_NAME, MediaStore.Video.Media.DATE_ADDED, MediaStore.Video.Media.SIZE);
        add(c, out, MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, "audio",
            MediaStore.Audio.Media.DISPLAY_NAME, MediaStore.Audio.Media.DATE_ADDED, MediaStore.Audio.Media.SIZE);
        return out.toString();
    }

    static void add(Context c, JSONArray out, Uri base, String kind, String nameCol, String dateCol, String sizeCol) {
        Cursor q = null;
        try {
            q = c.getContentResolver().query(base, new String[]{"_id", nameCol, dateCol, sizeCol}, null, null, dateCol + " DESC");
            int n = 0;
            while (q != null && q.moveToNext() && n < 2000) {
                JSONObject o = new JSONObject();
                o.put("uri", ContentUris.withAppendedId(base, q.getLong(0)).toString());
                o.put("kind", kind);
                o.put("name", q.getString(1));
                o.put("date", q.getLong(2));
                o.put("size", q.isNull(3) ? 0 : q.getLong(3));
                out.put(o);
                n++;
            }
        } catch (Exception e) {
        } finally {
            if (q != null) q.close();
        }
    }

    public static byte[] thumb(Context c, String uri, int size) {
        try {
            if (Build.VERSION.SDK_INT < 29) return null;
            Bitmap b = c.getContentResolver().loadThumbnail(Uri.parse(uri), new Size(size, size), null);
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            b.compress(Bitmap.CompressFormat.JPEG, 70, bo);
            return bo.toByteArray();
        } catch (Throwable e) { return null; }
    }

    /** Copies a content:// uri into dir. Returns the saved file name, or "" on failure. */
    public static String copyUri(Context c, String uriStr, String dir) {
        try {
            Uri u = Uri.parse(uriStr);
            String name = "file_" + System.currentTimeMillis();
            Cursor q = c.getContentResolver().query(u, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null);
            if (q != null) {
                if (q.moveToFirst() && !q.isNull(0)) name = q.getString(0);
                q.close();
            }
            name = name.replaceAll("[\\\\/:*?\"<>|]", "_");
            File d = new File(dir);
            d.mkdirs();
            File f = new File(d, name);
            if (f.exists()) f = new File(d, System.currentTimeMillis() + "_" + name);
            InputStream in = c.getContentResolver().openInputStream(u);
            OutputStream out = new FileOutputStream(f);
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            out.close();
            in.close();
            return f.getName();
        } catch (Throwable e) { return ""; }
    }

    public static void playAudio(String path, boolean loop) {
        try {
            stopAudio();
            audio = new MediaPlayer();
            audio.setDataSource(path);
            audio.setLooping(loop);
            audio.prepare();
            audio.start();
        } catch (Throwable e) { audio = null; }
    }

    public static void stopAudio() {
        try { if (audio != null) { audio.stop(); audio.release(); } } catch (Throwable e) {}
        audio = null;
    }

    /** Play audio directly from a MediaStore/content URI without copying it. */
    public static boolean playAudioUri(Context context, String uri, boolean loop) {
        try {
            stopAudio();
            audio = new MediaPlayer();
            audio.setDataSource(context, Uri.parse(uri));
            audio.setLooping(loop);
            audio.prepare();
            audio.start();
            return true;
        } catch (Throwable e) {
            stopAudio();
            return false;
        }
    }

    public static void playVideo(final Activity a, final String path, final boolean loop,
                                 final String text, final int color, final int sizeSp) {
        a.runOnUiThread(new Runnable() {
            public void run() {
                removeVideo();
                FrameLayout f = new FrameLayout(a);
                f.setBackgroundColor(0xFF000000);
                final VideoView v = new VideoView(a);
                v.setZOrderMediaOverlay(true);
                f.addView(v, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
                if (text != null && text.length() > 0) {
                    TextView t = new TextView(a);
                    t.setText(text);
                    t.setTextColor(color);
                    t.setTextSize(sizeSp);
                    t.setGravity(Gravity.CENTER);
                    t.setPadding(24, 24, 24, 24);
                    t.setBackgroundColor(0x66000000);
                    f.addView(t, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
                }
                a.addContentView(f, new ViewGroup.LayoutParams(-1, -1));
                videoHolder = f;
                v.setVideoPath(path);
                v.setOnPreparedListener(new MediaPlayer.OnPreparedListener() {
                    public void onPrepared(MediaPlayer mp) { mp.setLooping(loop); v.start(); }
                });
            }
        });
    }

    /** Display video directly from a MediaStore/content URI without copying it. */
    public static void playVideoUri(final Activity a, final String uri, final boolean loop,
                                    final String text, final int color, final int sizeSp) {
        a.runOnUiThread(new Runnable() {
            public void run() {
                removeVideo();
                FrameLayout f = new FrameLayout(a);
                f.setBackgroundColor(0xFF000000);
                final VideoView v = new VideoView(a);
                v.setZOrderMediaOverlay(true);
                f.addView(v, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
                if (text != null && text.length() > 0) {
                    TextView t = new TextView(a);
                    t.setText(text);
                    t.setTextColor(color);
                    t.setTextSize(sizeSp);
                    t.setGravity(Gravity.CENTER);
                    t.setPadding(24, 24, 24, 24);
                    t.setBackgroundColor(0x66000000);
                    f.addView(t, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
                }
                a.addContentView(f, new ViewGroup.LayoutParams(-1, -1));
                videoHolder = f;
                v.setVideoURI(Uri.parse(uri));
                v.setOnPreparedListener(new MediaPlayer.OnPreparedListener() {
                    public void onPrepared(MediaPlayer mp) { mp.setLooping(loop); v.start(); }
                });
            }
        });
    }

    static void removeVideo() {
        if (videoHolder != null) {
            ViewGroup p = (ViewGroup) videoHolder.getParent();
            if (p != null) p.removeView(videoHolder);
            videoHolder = null;
        }
    }

    public static void stopVideo(final Activity a) {
        a.runOnUiThread(new Runnable() { public void run() { removeVideo(); } });
    }

    static VideoView currentVideo() {
        if (videoHolder instanceof ViewGroup) {
            View c = ((ViewGroup) videoHolder).getChildAt(0);
            if (c instanceof VideoView) return (VideoView) c;
        }
        return null;
    }

    /** Remote playback control. Actions: toggle, pause, resume, seek (arg = delta in ms), volume (arg = 0..100). */
    public static String control(final Activity a, final String action, final int arg) {
        try {
            if ("volume".equals(action)) {
                AudioManager am = (AudioManager) a.getSystemService(Context.AUDIO_SERVICE);
                int max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
                am.setStreamVolume(AudioManager.STREAM_MUSIC, Math.max(0, Math.min(max, Math.round(max * arg / 100f))), 0);
            } else {
                a.runOnUiThread(new Runnable() {
                    public void run() {
                        try {
                            VideoView v = currentVideo();
                            if (v != null) {
                                if ("pause".equals(action)) v.pause();
                                else if ("resume".equals(action)) v.start();
                                else if ("toggle".equals(action)) { if (v.isPlaying()) v.pause(); else v.start(); }
                                else if ("seek".equals(action)) v.seekTo(Math.max(0, Math.min(v.getDuration(), v.getCurrentPosition() + arg)));
                            } else if (audio != null) {
                                if ("pause".equals(action)) audio.pause();
                                else if ("resume".equals(action)) audio.start();
                                else if ("toggle".equals(action)) { if (audio.isPlaying()) audio.pause(); else audio.start(); }
                                else if ("seek".equals(action)) audio.seekTo(Math.max(0, Math.min(audio.getDuration(), audio.getCurrentPosition() + arg)));
                            }
                        } catch (Throwable t) {}
                    }
                });
            }
        } catch (Throwable t) {}
        return status(a);
    }

    /** JSON: {kind: video|audio|none, playing, pos, dur, vol}. */
    public static String status(Context ctx) {
        JSONObject o = new JSONObject();
        try {
            VideoView v = currentVideo();
            if (v != null) { o.put("kind", "video"); o.put("playing", v.isPlaying()); o.put("pos", v.getCurrentPosition()); o.put("dur", v.getDuration()); }
            else if (audio != null) { o.put("kind", "audio"); o.put("playing", audio.isPlaying()); o.put("pos", audio.getCurrentPosition()); o.put("dur", audio.getDuration()); }
            else o.put("kind", "none");
            AudioManager am = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
            o.put("vol", Math.round(100f * am.getStreamVolume(AudioManager.STREAM_MUSIC) / Math.max(1, am.getStreamMaxVolume(AudioManager.STREAM_MUSIC))));
        } catch (Throwable t) {}
        return o.toString();
    }

    public static void keepScreenOn(final Activity a) {
        a.runOnUiThread(new Runnable() {
            public void run() { a.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON); }
        });
    }
}
