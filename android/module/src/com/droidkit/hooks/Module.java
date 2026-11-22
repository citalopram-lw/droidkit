package com.droidkit.hooks;

import android.hardware.Sensor;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.location.Criteria;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.Looper;
import android.util.Log;

import java.io.File;
import java.lang.reflect.Member;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.function.Consumer;

import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.callbacks.XC_LoadPackage.LoadPackageParam;

/**
 * DroidKit injection entry point. Runs inside the target app process (Zygisk+Vector /
 * LSPosed scope). Provides:
 *   - synthetic GPS (LocationManager)
 *   - a full virtual sensor set (SensorManager): accelerometer waveform -> real cadence
 *   - Build fingerprint fields matching the host device profile
 *   - java.io.File hiding for root/container artifacts
 */
public final class Module implements IXposedHookLoadPackage {
    private static final String TAG = "DroidKit";
    private static Cfg cfg = new Cfg();
    private static long cfgMtime = 0;

    private static final Set<String> HIDE = new HashSet<>();

    static {
        HIDE.add("/system/bin/su");
        HIDE.add("/system/xbin/su");
        HIDE.add("/system/sbin/su");
        HIDE.add("/sbin/su");
        HIDE.add("/system/app/Superuser.apk");
        HIDE.add("/data/adb/magisk");
        HIDE.add("/data/adb/modules");
        HIDE.add("/data/adb/neozygisk");
        HIDE.add("/system/etc/init/magisk");
        HIDE.add("/debug_ramdisk");
        HIDE.add("/sbin/.magisk");
        HIDE.add("/system/lib64/libnb.so");
        HIDE.add("/system/lib/libnb.so");
        HIDE.add("/dev/qemu_pipe");
        HIDE.add("/dev/goldfish_pipe");
        HIDE.add("/.dockerenv");
        HIDE.add("/system/bin/frida-server");
        HIDE.add("/data/local/tmp/frida-server");
    }

    @Override
    public void handleLoadPackage(LoadPackageParam lp) {
        if (lp == null || lp.packageName == null) return;
        reloadCfg();
        if (!isTarget(lp.packageName)) return;

        Log.i(TAG, "injected pkg=" + lp.packageName + " process=" + lp.processName
                + " pid=" + android.os.Process.myPid() + " cls=" + lp.classLoader);

        try { spoofBuild(); } catch (Throwable t) { Log.e(TAG, "build spoof: " + t); }
        try { hookLocation(); Log.i(TAG, "location hooks installed"); } catch (Throwable t) { Log.e(TAG, "loc hooks: " + t); }
        try { hookSensors(); Log.i(TAG, "sensor hooks installed"); } catch (Throwable t) { Log.e(TAG, "sensor hooks: " + t); }
        if (cfg.hideArtifacts) {
            try { hookFiles(); Log.i(TAG, "file hide hooks installed"); } catch (Throwable t) { Log.e(TAG, "file hooks: " + t); }
        try { hookUname(); Log.i(TAG, "uname hooks installed"); } catch (Throwable t) { Log.e(TAG, "uname hooks: " + t); }
        reportIdentity();
        }
    }

    static boolean isTarget(String pkg) {
        try {
            File f = new File(Cfg.DIR + "/targets.txt");
            if (!f.canRead()) return true;                 // no list -> every app in scope
            java.io.BufferedReader r = new java.io.BufferedReader(new java.io.FileReader(f));
            String line;
            while ((line = r.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                if (line.equals("*") || line.equals(pkg)) { r.close(); return true; }
            }
            r.close();
            return false;
        } catch (Throwable t) {
            return true;
        }
    }

    static void reloadCfg() {
        try {
            File f = new File(Cfg.FILE);
            long m = f.lastModified();
            if (m != cfgMtime) {
                cfg = Cfg.load();
                cfgMtime = m;
                LocationFaker.configure(cfg);
                SensorFaker.setCadence(cfg.cadenceHz);
            }
        } catch (Throwable t) {
            Log.w(TAG, "reload: " + t);
        }
    }

    private static void spoofBuild() {
        if (cfg.bModel == null && cfg.bBrand == null) return;
        if (cfg.bModel != null) U.setStaticString(Build.class, "MODEL", cfg.bModel);
        if (cfg.bBrand != null) U.setStaticString(Build.class, "BRAND", cfg.bBrand);
        if (cfg.bManufacturer != null) U.setStaticString(Build.class, "MANUFACTURER", cfg.bManufacturer);
        if (cfg.bDevice != null) U.setStaticString(Build.class, "DEVICE", cfg.bDevice);
        if (cfg.bProduct != null) U.setStaticString(Build.class, "PRODUCT", cfg.bProduct);
        if (cfg.bHardware != null) U.setStaticString(Build.class, "HARDWARE", cfg.bHardware);
        if (cfg.bBoard != null) U.setStaticString(Build.class, "BOARD", cfg.bBoard);
        if (cfg.bFingerprint != null) U.setStaticString(Build.class, "FINGERPRINT", cfg.bFingerprint);
        if (cfg.bTags != null) U.setStaticString(Build.class, "TAGS", cfg.bTags);
        if (cfg.bType != null) U.setStaticString(Build.class, "TYPE", cfg.bType);
        if (cfg.bHost != null) U.setStaticString(Build.class, "HOST", cfg.bHost);
        if (cfg.bUser != null) U.setStaticString(Build.class, "USER", cfg.bUser);
        if (cfg.bId != null) U.setStaticString(Build.class, "ID", cfg.bId);
        if (cfg.bDisplay != null) U.setStaticString(Build.class, "DISPLAY", cfg.bDisplay);
        if (cfg.bHardware != null) U.setStaticString(Build.class, "HARDWARE", cfg.bHardware);
        U.setStaticObject(Build.class, "SUPPORTED_ABIS", new String[]{"arm64-v8a", "armeabi-v7a"});
        U.setStaticObject(Build.class, "SUPPORTED_64_BIT_ABIS", new String[]{"arm64-v8a"});
        U.setStaticObject(Build.class, "SUPPORTED_32_BIT_ABIS", new String[]{"armeabi-v7a"});
    }

    private static void hookLocation() {
        XposedBridge.hookAllMethods(LocationManager.class, "getLastKnownLocation", new XC_MethodHook() {
            @Override protected void afterHookedMethod(MethodHookParam p) {
                if (p.args == null || p.args.length < 1) return;
                String provider = (String) p.args[0];
                p.setResult(LocationFaker.current(provider));
            }
        });
        XposedBridge.hookAllMethods(LocationManager.class, "requestLocationUpdates", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                if (p.args == null) return;
                LocationListener l = null;
                Looper looper = null;
                for (Object a : p.args) {
                    if (a instanceof LocationListener) l = (LocationListener) a;
                    else if (a instanceof Looper) looper = (Looper) a;
                }
                if (l != null) {
                    LocationFaker.register(l, looper);
                    p.setResult(null);
                }
            }
        });
        XposedBridge.hookAllMethods(LocationManager.class, "getCurrentLocation", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                if (p.args == null) return;
                for (Object a : p.args) {
                    if (a instanceof Consumer) {
                        final Consumer c = (Consumer) a;
                        final Object loc = LocationFaker.current("gps");
                        new android.os.Handler(Looper.getMainLooper()).post(new Runnable() {
                            @Override public void run() { c.accept(loc); }
                        });
                        p.setResult(null);
                        return;
                    }
                }
            }
        });
        XposedBridge.hookAllMethods(LocationManager.class, "isProviderEnabled", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) { p.setResult(true); }
        });
        XposedBridge.hookAllMethods(LocationManager.class, "getProviders", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                p.setResult(new String[]{"gps", "network", "fused", "passive"});
            }
        });
        XposedBridge.hookAllMethods(LocationManager.class, "getAllProviders", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                java.util.List<String> l = new java.util.ArrayList<>();
                l.add("gps"); l.add("network"); l.add("fused"); l.add("passive");
                p.setResult(l);
            }
        });
        XposedBridge.hookAllMethods(LocationManager.class, "getBestProvider", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) { p.setResult("gps"); }
        });
    }

    private static void hookSensors() {
        Class<?> sm = SensorManager.class;
        XposedBridge.hookAllMethods(sm, "getDefaultSensor", new XC_MethodHook() {
            @Override protected void afterHookedMethod(MethodHookParam p) {
                if (p.getResult() == null && p.args != null && p.args.length >= 1 && p.args[0] instanceof Integer) {
                    p.setResult(SensorFaker.sensor((Integer) p.args[0]));
                }
            }
        });
        XC_MethodHook addFakes = new XC_MethodHook() {
            @Override protected void afterHookedMethod(MethodHookParam p) {
                Object r = p.getResult();
                if (!(r instanceof List)) return;
                int type = -1;
                for (Object a : p.args) if (a instanceof Integer) type = (Integer) a;
                @SuppressWarnings("unchecked") List<Sensor> list = (List<Sensor>) r;
                if (type < 0) {
                    for (Sensor f : SensorFaker.list()) if (!list.contains(f)) list.add(f);
                } else {
                    Sensor f = SensorFaker.sensor(type);
                    boolean has = false;
                    for (Sensor s : list) if (s.getType() == type) { has = true; break; }
                    if (!has && f != null) list.add(f);
                }
            }
        };
        XposedBridge.hookAllMethods(sm, "getSensorList", addFakes);
        try { XposedBridge.hookAllMethods(sm, "getFullSensorList", addFakes); } catch (Throwable ignored) {}
        try {
            Class<?> ssm = Class.forName("android.hardware.SystemSensorManager");
            XposedBridge.hookAllMethods(ssm, "getSensorList", addFakes);
            XposedBridge.hookAllMethods(ssm, "getFullSensorList", addFakes);
            XposedBridge.hookAllMethods(ssm, "getDefaultSensor", new XC_MethodHook() {
                @Override protected void afterHookedMethod(MethodHookParam p) {
                    if (p.getResult() == null && p.args != null && p.args.length >= 1 && p.args[0] instanceof Integer) {
                        p.setResult(SensorFaker.sensor((Integer) p.args[0]));
                    }
                }
            });
        } catch (Throwable ignored) {
        }

        try { XposedBridge.hookAllMethods(sm, "registerListener", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                if (p.args == null || p.args.length < 3) return;
                if (!(p.args[0] instanceof SensorEventListener) || !(p.args[1] instanceof Sensor)) return;
                Sensor s = (Sensor) p.args[1];
                if (!SensorFaker.isFake(s)) return;
                android.os.Handler h = null;
                for (Object a : p.args) if (a instanceof android.os.Handler) h = (android.os.Handler) a;
                SensorFaker.register((SensorEventListener) p.args[0], s, h);
                p.setResult(Boolean.TRUE);
            }
        }); } catch (Throwable ignored) {}
        try { XposedBridge.hookAllMethods(sm, "unregisterListener", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                if (p.args == null || p.args.length < 1 || !(p.args[0] instanceof SensorEventListener)) return;
                Sensor s = (p.args.length >= 2 && p.args[1] instanceof Sensor) ? (Sensor) p.args[1] : null;
                SensorFaker.unregister((SensorEventListener) p.args[0], s);
            }
        }); } catch (Throwable ignored) {}
        try { XposedBridge.hookAllMethods(sm, "flush", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                if (p.args != null && p.args.length >= 1 && p.args[0] instanceof SensorEventListener) {
                    p.setResult(Boolean.TRUE);
                }
            }
        }); } catch (Throwable ignored) {}
    }

    /** Measure what a native scanner would see in THIS process (the detector's ruler). */
    private static void reportIdentity() {
        // Split external signatures (what a packer greps) from our own renamed bridge,
        // which is necessarily mapped but is not a known name.
        String[] ext = {"/libnb.so", "libndk_translation", "libzygisk", "/lspd", "magisk", "frida",
                        "houdini", "lspatch", "npatch"};
        int hits = 0, self = 0;
        StringBuilder sb = new StringBuilder();
        try {
            java.io.BufferedReader r = new java.io.BufferedReader(new java.io.FileReader("/proc/self/maps"));
            String line;
            while ((line = r.readLine()) != null) {
                String l = line.toLowerCase();
                boolean e = false;
                for (String k : ext) if (l.contains(k)) { e = true; break; }
                if (e) {
                    hits++;
                    if (hits <= 3) sb.append(l.trim()).append(" || ");
                } else if (l.contains("libqc_platform")) {
                    self++;
                }
            }
            r.close();
        } catch (Throwable t) {
            sb.append("maps_err=").append(t);
        }
        Log.i(TAG, "maps_scan external=" + hits + " self=" + self + " sample=" + sb);
        // native stat: bypasses our own File.exists hook, this is what packers call
        String[] paths = {"/system/bin/su", "/data/adb/magisk", "/system/lib64/libnb.so",
                          "/system/lib64/libndk_translation.so", "/sbin/.magisk"};
        StringBuilder st = new StringBuilder();
        for (String p : paths) {
            try {
                android.system.Os.stat(p);
                st.append(p).append("=visible ");
            } catch (Throwable e) {
                st.append(p).append("=gone ");
            }
        }
        Log.i(TAG, "stat_scan " + st);
    }

    /** android.system.Os.uname() is the Java-visible kernel identity: fake it. */
    private static void hookUname() {
        XposedBridge.hookAllMethods(android.system.Os.class, "uname", new XC_MethodHook() {
            @Override protected void afterHookedMethod(MethodHookParam p) {
                Object u = p.getResult();
                if (u == null) return;
                Class<?> c = u.getClass();
                try {
                    U.setObj(u, U.off(c, "sysname"), "Linux");
                    U.setObj(u, U.off(c, "nodename"), "localhost");
                    U.setObj(u, U.off(c, "release"), "5.15.104-android13-8-00002-g3f1c2a7e5b1d-ab11074668");
                    U.setObj(u, U.off(c, "version"), "#1 SMP PREEMPT Wed Mar 6 10:00:00 UTC 2024");
                    U.setObj(u, U.off(c, "machine"), "aarch64");
                } catch (Throwable ignored) {}
            }
        });
    }

    private static void hookFiles() {
        XposedBridge.hookAllMethods(File.class, "exists", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                Object o = p.thisObject;
                if (!(o instanceof File)) return;
                String path = ((File) o).getAbsolutePath();
                if (HIDE.contains(path)) p.setResult(Boolean.FALSE);
            }
        });
    }
}
