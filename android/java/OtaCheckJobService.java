package com.jkurtz.otafwmerger;

import android.app.DownloadManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class OtaCheckJobService extends JobService {
    public static final int JOB_ID = 10515;
    private static final String CHANNEL_ID = "ota_fw_updates";
    private static final String TRACKER_PATH = "/storage/emulated/0/Download/OTAFirmwareMerger/ota_tracker.json";

    public static void syncSchedule(Context ctx) {
        JobScheduler js = (JobScheduler) ctx.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        JSONObject st = readTracker();
        boolean enabled = st != null && st.optBoolean("daily_check", false);
        if (!enabled) {
            js.cancel(JOB_ID);
            return;
        }
        ComponentName cn = new ComponentName(ctx, OtaCheckJobService.class);
        JobInfo.Builder b = new JobInfo.Builder(JOB_ID, cn)
                .setPeriodic(24L * 60L * 60L * 1000L)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true);
        js.schedule(b.build());
    }

    private static JSONObject readTracker() {
        try {
            File f = new File(TRACKER_PATH);
            if (!f.exists()) return null;
            byte[] buf = new byte[(int) f.length()];
            try (FileInputStream fis = new FileInputStream(f)) {
                int n = fis.read(buf);
                if (n <= 0) return null;
            }
            return new JSONObject(new String(buf, StandardCharsets.UTF_8));
        } catch (Exception e) {
            return null;
        }
    }

    private static void saveTracker(JSONObject obj) {
        try (FileOutputStream fos = new FileOutputStream(TRACKER_PATH)) {
            fos.write(obj.toString(2).getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) {}
    }

    @Override
    public boolean onStartJob(final JobParameters params) {
        new Thread(() -> {
            try {
                runCheck();
            } finally {
                jobFinished(params, false);
            }
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }

    private static String[] resolveZones(String model, String otaVer) {
        String m = model.toUpperCase();
        String v = otaVer.toUpperCase();
        if (m.startsWith("PLK") || m.startsWith("PJD") || m.startsWith("PJZ") || m.startsWith("PHB")
                || m.startsWith("PJA") || m.startsWith("PGP") || m.startsWith("PKG")
                || m.startsWith("PKR") || m.startsWith("PKX") || v.contains("(CN")) {
            return new String[]{"CN"};
        }
        if (m.endsWith("IN") || v.contains("(IN")) {
            return new String[]{"IN", "EU"};
        }
        return new String[]{"EU", "IN"};
    }

    private static String findSu() {
        String[] cands = {"/data/adb/ksu/bin/su", "/data/adb/ap/bin/su", "/system/bin/su", "/system/xbin/su", "/sbin/su"};
        for (String c : cands) {
            if (new File(c).exists()) return c;
        }
        return "su";
    }

    private String captureRootUrl() {
        try {
            String probe = "grep -rhoE 'https?://(android\\.googleapis\\.com/packages/ota-api/package/[^<>[:space:]&]+|[^<>[:space:]&]*allawn[^<>[:space:]&]*\\.zip[^<>[:space:]&]*)' "
                    + "/data/data/com.google.android.gms/shared_prefs/ /data/data/com.oplus.ota/shared_prefs/ 2>/dev/null | tail -n 1";
            Process p = new ProcessBuilder(findSu(), "-c", probe).redirectErrorStream(true).start();
            String last = "";
            try (BufferedReader br = new BufferedReader(new InputStreamReader(p.getInputStream()))) {
                String line;
                while ((line = br.readLine()) != null) {
                    if (line.trim().startsWith("http")) last = line.trim();
                }
            }
            p.waitFor();
            return last;
        } catch (Exception e) {
            return "";
        }
    }

    private String queryOplus(String binPath, String model, String queryVer, String[] zones, String carrier) throws Exception {
        String out = "";
        for (String z : zones) {
            List<String> cmd = new ArrayList<>();
            cmd.add(binPath);
            cmd.add(queryVer);
            cmd.add("--model=" + model);
            cmd.add("--region=" + z);
            if (!carrier.isEmpty()) cmd.add("--carrier=" + carrier);

            Process p = new ProcessBuilder(cmd).redirectErrorStream(true).start();
            StringBuilder sb = new StringBuilder();
            try (BufferedReader br = new BufferedReader(new InputStreamReader(p.getInputStream()))) {
                String line;
                while ((line = br.readLine()) != null) sb.append(line).append('\n');
            }
            p.waitFor();
            out = sb.toString();
            if (Pattern.compile("https?://[^\\s\"'<>]+\\.zip").matcher(out).find()) break;
        }
        return out;
    }

    private void runCheck() {
        JSONObject st = readTracker();
        if (st == null || !st.optBoolean("daily_check", false)) return;
        String model = st.optString("model", "").trim();
        String otaVer = st.optString("ota_version", "").trim();
        String dispVer = st.optString("display_version", "").trim();
        if (otaVer.isEmpty()) otaVer = dispVer;
        boolean rootCap = st.optBoolean("root_capture", false);
        boolean forceLatest = st.optBoolean("force_latest", false);

        try {
            if (rootCap) {
                String gotaUrl = captureRootUrl();
                if (!gotaUrl.isEmpty() && (forceLatest || !gotaUrl.equals(st.optString("last_found_url", "")))) {
                    String tag = model.isEmpty() ? "GOTA_captured" : (model + "_GOTA_captured");
                    st.put("last_found_version", tag);
                    st.put("last_found_url", gotaUrl);
                    saveTracker(st);
                    boolean autoDl = st.optBoolean("auto_download", false);
                    if (autoDl) enqueueDownload(gotaUrl, tag);
                    postNotification(model.isEmpty() ? "Device" : model, tag, autoDl);
                    return;
                }
            }

            if (model.isEmpty() || otaVer.isEmpty()) return;
            String carrier = st.optString("carrier", "").trim();
            String[] zones = resolveZones(model, otaVer);
            String binPath = getApplicationInfo().nativeLibraryDir + "/liboplus_updater.so";
            if (!new File(binPath).exists()) return;

            String out = queryOplus(binPath, model, otaVer, zones, carrier);
            Matcher urlM = Pattern.compile("https?://[^\\s\"'<>]+\\.zip[^\\s\"'<>]*").matcher(out);
            if (!urlM.find() && forceLatest) {
                out = queryOplus(binPath, model, model + "_11.A.01_0001_202001010000", zones, carrier);
                urlM = Pattern.compile("https?://[^\\s\"'<>]+\\.zip[^\\s\"'<>]*").matcher(out);
                if (!urlM.find()) return;
            } else if (!urlM.reset().find()) {
                return;
            }

            Matcher verM = Pattern.compile("\"(?:otaVersion|versionName)\"\\s*:\\s*\"([^\"]+)\"").matcher(out);
            if (!verM.find()) {
                verM = Pattern.compile("(" + Pattern.quote(model) + "_[A-Za-z0-9._()]+)").matcher(out);
                if (!verM.find()) return;
            }

            String newVer = verM.group(1);
            String url = urlM.group(0);
            if (!newVer.toUpperCase().startsWith(model.toUpperCase())) return;
            if (!forceLatest && (newVer.equals(otaVer) || newVer.equals(dispVer) || newVer.equals(st.optString("last_found_version", "")))) {
                return;
            }

            st.put("last_found_version", newVer);
            st.put("last_found_url", url);
            saveTracker(st);

            boolean autoDl = st.optBoolean("auto_download", false);
            if (autoDl) enqueueDownload(url, newVer);
            postNotification(model, newVer, autoDl);
        } catch (Exception ignored) {}
    }

    private void enqueueDownload(String url, String newVer) {
        try {
            DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            if (dm == null) return;
            String safe = newVer.replaceAll("[^A-Za-z0-9._-]", "_") + ".zip";
            DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
            req.setTitle("OTA FW Merger: " + newVer);
            req.setDescription("Downloading incremental OTA");
            req.setAllowedNetworkTypes(DownloadManager.Request.NETWORK_WIFI);
            req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "OTAFirmwareMerger/incoming/" + safe);
            dm.enqueue(req);
        } catch (Exception ignored) {}
    }

    private void postNotification(String model, String newVer, boolean autoDl) {
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "Device OTA Updates", NotificationManager.IMPORTANCE_DEFAULT);
            nm.createNotificationChannel(ch);
        }
        Intent launch = getPackageManager().getLaunchIntentForPackage(getPackageName());
        PendingIntent pi = PendingIntent.getActivity(this, 0, launch != null ? launch : new Intent(), PendingIntent.FLAG_IMMUTABLE);
        String body = autoDl
                ? newVer + " detected — auto-downloading on Wi-Fi to Download/OTAFirmwareMerger/incoming/"
                : newVer + " is available for " + model + ". Tap to open OTA FW Merger.";
        Notification.Builder nb = (Build.VERSION.SDK_INT >= 26)
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        nb.setContentTitle("New OTA for " + model)
          .setContentText(body)
          .setSmallIcon(getApplicationInfo().icon)
          .setContentIntent(pi)
          .setAutoCancel(true);
        nm.notify(JOB_ID, nb.build());
    }
}
