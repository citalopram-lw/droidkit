package com.droidkit.hooks;

import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** Runtime configuration pushed by the host (droidkit CLI / MCP). */
public final class Cfg {
    public static final String DIR = "/data/local/tmp/droidkit";
    public static final String FILE = DIR + "/config.json";
    public static final String CMD = DIR + "/cmd";

    public List<double[]> points = new ArrayList<>();
    public double speed = 2.8;           // m/s
    public double cadenceHz = 3.34;      // steps per second
    public boolean loop = true;
    public boolean autoStart = true;
    public boolean hideArtifacts = true;
    public boolean diag = false;
    public long mtime = 0L;

    public String bModel, bBrand, bManufacturer, bDevice, bProduct, bHardware,
            bBoard, bFingerprint, bTags, bType, bHost, bUser, bId, bDisplay;

    public static Cfg load() {
        Cfg c = new Cfg();
        try {
            File f = new File(FILE);
            if (!f.canRead()) return c;
            byte[] buf = new byte[(int) f.length()];
            FileInputStream in = new FileInputStream(f);
            int n = in.read(buf);
            in.close();
            String s = new String(buf, 0, Math.max(n, 0), StandardCharsets.UTF_8);
            JSONObject o = new JSONObject(s);
            JSONArray arr = o.optJSONArray("route");
            if (arr != null) {
                for (int i = 0; i < arr.length(); i++) {
                    JSONArray p = arr.optJSONArray(i);
                    if (p != null && p.length() >= 2) {
                        c.points.add(new double[]{p.getDouble(0), p.getDouble(1)});
                    }
                }
            }
            c.speed = o.optDouble("speed", c.speed);
            c.cadenceHz = o.optDouble("cadence_hz", c.cadenceHz);
            c.loop = o.optBoolean("loop", c.loop);
            c.autoStart = o.optBoolean("auto_start", c.autoStart);
            c.hideArtifacts = o.optBoolean("hide_artifacts", c.hideArtifacts);
            c.diag = o.optBoolean("diag", c.diag);
            JSONObject b = o.optJSONObject("build");
            if (b != null) {
                c.bModel = b.optString("model", null);
                c.bBrand = b.optString("brand", null);
                c.bManufacturer = b.optString("manufacturer", null);
                c.bDevice = b.optString("device", null);
                c.bProduct = b.optString("product", null);
                c.bHardware = b.optString("hardware", null);
                c.bBoard = b.optString("board", null);
                c.bFingerprint = b.optString("fingerprint", null);
                c.bTags = b.optString("tags", null);
                c.bType = b.optString("type", null);
                c.bHost = b.optString("host", null);
                c.bUser = b.optString("user", null);
                c.bId = b.optString("id", null);
                c.bDisplay = b.optString("display", null);
            }
            c.mtime = f.lastModified();
        } catch (Throwable t) {
            Log.w("DroidKit", "config parse failed: " + t);
        }
        return c;
    }

    /** Read a one-shot command file, return "" when absent. */
    public static String readCmd() {
        try {
            File f = new File(CMD);
            if (!f.canRead()) return "";
            byte[] buf = new byte[(int) f.length()];
            FileInputStream in = new FileInputStream(f);
            int n = in.read(buf);
            in.close();
            f.delete();
            return new String(buf, 0, Math.max(n, 0), StandardCharsets.UTF_8).trim();
        } catch (Throwable t) {
            return "";
        }
    }
}
