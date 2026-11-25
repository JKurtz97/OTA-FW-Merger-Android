package com.jkurtz.otafwmerger;

import android.content.ComponentCallbacks;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.content.res.Configuration;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

public class MonetInitProvider extends ContentProvider {
    private static String hex(Context ctx, int resId) {
        int c = ctx.getColor(resId) & 0xFFFFFF;
        return String.format("#%06X", c);
    }

    public static void exportPalette(Context ctx) {
        if (ctx == null || Build.VERSION.SDK_INT < 31) return;
        try {
            int uiMode = ctx.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK;
            boolean isDark = (uiMode == Configuration.UI_MODE_NIGHT_YES);
            JSONObject j = new JSONObject();
            j.put("is_dark", isDark);
            j.put("a1_50",  hex(ctx, android.R.color.system_accent1_50));
            j.put("a1_100", hex(ctx, android.R.color.system_accent1_100));
            j.put("a1_200", hex(ctx, android.R.color.system_accent1_200));
            j.put("a1_300", hex(ctx, android.R.color.system_accent1_300));
            j.put("a1_400", hex(ctx, android.R.color.system_accent1_400));
            j.put("a1_500", hex(ctx, android.R.color.system_accent1_500));
            j.put("a1_600", hex(ctx, android.R.color.system_accent1_600));
            j.put("a1_700", hex(ctx, android.R.color.system_accent1_700));
            j.put("a1_800", hex(ctx, android.R.color.system_accent1_800));
            j.put("a1_900", hex(ctx, android.R.color.system_accent1_900));

            j.put("a2_100", hex(ctx, android.R.color.system_accent2_100));
            j.put("a2_200", hex(ctx, android.R.color.system_accent2_200));
            j.put("a2_700", hex(ctx, android.R.color.system_accent2_700));
            j.put("a2_800", hex(ctx, android.R.color.system_accent2_800));

            j.put("n1_0",    hex(ctx, android.R.color.system_neutral1_0));
            j.put("n1_10",   hex(ctx, android.R.color.system_neutral1_10));
            j.put("n1_50",   hex(ctx, android.R.color.system_neutral1_50));
            j.put("n1_100",  hex(ctx, android.R.color.system_neutral1_100));
            j.put("n1_200",  hex(ctx, android.R.color.system_neutral1_200));
            j.put("n1_700",  hex(ctx, android.R.color.system_neutral1_700));
            j.put("n1_800",  hex(ctx, android.R.color.system_neutral1_800));
            j.put("n1_900",  hex(ctx, android.R.color.system_neutral1_900));
            j.put("n1_1000", hex(ctx, android.R.color.system_neutral1_1000));

            j.put("n2_200",  hex(ctx, android.R.color.system_neutral2_200));
            j.put("n2_400",  hex(ctx, android.R.color.system_neutral2_400));
            j.put("n2_500",  hex(ctx, android.R.color.system_neutral2_500));
            j.put("n2_700",  hex(ctx, android.R.color.system_neutral2_700));
            j.put("n2_800",  hex(ctx, android.R.color.system_neutral2_800));

            File out = new File(ctx.getFilesDir(), "monet_palette.json");
            try (FileOutputStream fos = new FileOutputStream(out)) {
                fos.write(j.toString().getBytes(StandardCharsets.UTF_8));
            }
        } catch (Exception ignored) {}
    }

    @Override
    public boolean onCreate() {
        final Context ctx = getContext();
        if (ctx != null) {
            exportPalette(ctx);
            Context appCtx = ctx.getApplicationContext();
            if (appCtx != null) {
                appCtx.registerComponentCallbacks(new ComponentCallbacks() {
                    @Override public void onConfigurationChanged(Configuration newConfig) { exportPalette(appCtx); }
                    @Override public void onLowMemory() {}
                });
            }
        }
        return true;
    }

    @Override public Cursor query(Uri u, String[] p, String s, String[] sa, String so) { return null; }
    @Override public String getType(Uri u) { return null; }
    @Override public Uri insert(Uri u, ContentValues v) { return null; }
    @Override public int delete(Uri u, String s, String[] sa) { return 0; }
    @Override public int update(Uri u, ContentValues v, String s, String[] sa) { return 0; }
}
