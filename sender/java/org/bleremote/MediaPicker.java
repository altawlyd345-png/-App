package org.bleremote;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.UUID;

public class MediaPicker {
    /** Copies a content:// Uri into destDir. Returns "storedFile|originalName" or "ERR:..." */
    public static String copy(Context c, String uriStr, String destDir) {
        try {
            Uri u = Uri.parse(uriStr);
            ContentResolver cr = c.getContentResolver();
            String name = "file";
            Cursor cur = cr.query(u, null, null, null, null);
            if (cur != null) {
                if (cur.moveToFirst()) {
                    int i = cur.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                    if (i >= 0) name = cur.getString(i);
                }
                cur.close();
            }
            String ext = "";
            int d = name.lastIndexOf('.');
            if (d >= 0) ext = name.substring(d).toLowerCase().replaceAll("[^a-z0-9.]", "");
            String fn = UUID.randomUUID().toString().substring(0, 8) + ext;
            InputStream in = cr.openInputStream(u);
            FileOutputStream out = new FileOutputStream(new File(destDir, fn));
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            out.close();
            in.close();
            return fn + "|" + name;
        } catch (Exception e) {
            return "ERR:" + e;
        }
    }
}
