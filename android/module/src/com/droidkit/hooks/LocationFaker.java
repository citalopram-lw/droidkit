package com.droidkit.hooks;

import android.location.Location;
import android.location.LocationListener;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import java.util.ArrayList;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Synthetic GPS. Two modes, both driven from the cmd file (@1 Hz):
 *   route mode  polyline + constant speed (config.json route)
 *   nav mode    walk straight to an arbitrary lat,lng, stop within N m  ("nav lat,lng [stop_m]")
 * The current position lives in {@link #pos} so mode switches never teleport the app.
 */
public final class LocationFaker {
    private static final String TAG = "DroidKit";
    private static final CopyOnWriteArrayList<Reg> REGS = new CopyOnWriteArrayList<>();
    private static ScheduledExecutorService exec;
    private static volatile Route route;
    private static volatile double speed = 2.8;
    private static volatile double travelled = 0;
    private static volatile boolean running = false;
    private static volatile boolean loop = true;
    private static volatile Location last;
    /** {lat, lng, bearing} — the one source of truth for "where am I". */
    private static volatile double[] pos;
    private static volatile double[] navTarget;
    private static volatile double navStop = 3.0;
    private static volatile long pushes = 0;
    private static volatile long lastPushMs = 0;
    private static volatile double[] shuffleCenter;
    private static volatile double shuffleR = 4.0;
    private static volatile double shuffleAng = 0;

    static final class Reg {
        final LocationListener l;
        final Handler h;
        Reg(LocationListener l, Handler h) { this.l = l; this.h = h; }
    }

    static synchronized void configure(Cfg c) {
        Route r = new Route(c.points);
        if (r.pts.size() >= 2) {
            route = r;
            Log.i(TAG, "route loaded: points=" + r.pts.size() + " length=" + Math.round(r.length) + "m speed=" + c.speed);
        } else {
            Log.w(TAG, "route empty (need >=2 points); GPS holds at last point");
        }
        speed = c.speed;
        loop = c.loop;
        if (c.autoStart) start();
    }

    static void setSpeed(double s) {
        speed = Math.max(0.5, Math.min(12.0, s));
        Log.i(TAG, "speed=" + speed);
    }

    static void start() {
        running = true;
        if (pos == null && route != null) pos = route.at(travelled);
        ensureTicker();
        Log.i(TAG, "route started");
        push();
    }

    static void stop() {
        running = false;
        navTarget = null;
        shuffleCenter = null;
        Log.i(TAG, "route stopped at " + Math.round(travelled) + "m");
    }

    static void hold() {
        running = false;
        navTarget = null;
        shuffleCenter = null;
        Log.i(TAG, "route hold");
    }

    /** Stay put but keep moving in a small circle so the App keeps its GPS lock. */
    static void startShuffle(double r) {
        double[] cur = pos != null ? pos : (route != null ? route.at(travelled) : null);
        if (cur == null) return;
        shuffleCenter = new double[]{cur[0], cur[1], 0};
        shuffleR = Math.max(2.0, Math.min(12.0, r));
        shuffleAng = 0;
        navTarget = null;
        running = true;
        ensureTicker();
        push();
        Log.i(TAG, "shuffle r=" + shuffleR + " at " + cur[0] + "," + cur[1]);
    }

    /** Absolute jump used only for setup (never while the app is recording a run). */
    static void seekTo(double lat, double lng) {
        navTarget = null;
        shuffleCenter = null;
        pos = new double[]{lat, lng, 0};
        travelled = 0;
        push();
        Log.i(TAG, "seek " + lat + "," + lng);
    }

    private static synchronized void ensureTicker() {
        if (exec != null) return;
        exec = Executors.newSingleThreadScheduledExecutor();
        exec.scheduleAtFixedRate(new Runnable() {
            @Override public void run() {
                try {
                    handleCmd();
                    if (running) {
                        step();
                    } else {
                        // keep the stream alive while holding: 小步点 turns the run
                        // page grey («正在获取GPS信号…») after ~10 s without a fix,
                        // even though the position itself is not changing
                        push();
                    }
                } catch (Throwable t) { Log.e(TAG, "tick: " + t); }
            }
        }, 1, 1, TimeUnit.SECONDS);
    }

    /** One second of movement. */
    private static void step() {
        double[] sc = shuffleCenter;
        if (sc != null) {
            // 静止会让 App 判「无法获取GPS定位」（实测 20-25 s）：原地绕 4 m 小圈，
            // 位置在动、又不会离开点位感应半径
            shuffleAng += Math.toDegrees(0.6 / Math.max(shuffleR, 1.0));
            if (shuffleAng > 360) shuffleAng -= 360;
            double ang = Math.toRadians(shuffleAng);
            double lat = sc[0] + (shuffleR * Math.cos(ang)) / 111320.0;
            double lng = sc[1] + (shuffleR * Math.sin(ang)) / (111320.0 * Math.cos(Math.toRadians(sc[0])));
            pos = new double[]{lat, lng, 0};
            push();
            return;
        }
        double[] target = navTarget;
        if (target != null) {
            double[] cur = pos != null ? pos : new double[]{target[0], target[1], 0};
            double d = Route.dist(cur, target);
            if (d <= navStop) {
                pos = new double[]{target[0], target[1], cur.length > 2 ? cur[2] : 0};
                running = false;
                navTarget = null;
                Log.i(TAG, "nav arrived, d=" + (int) d);
            } else {
                double brg = Route.bearing(cur, target);
                double step = Math.min(speed, d - navStop);
                pos = move(cur, brg, step);
            }
            push();
            return;
        }
        if (route == null) return;
        travelled += speed;
        if (travelled > route.length && !loop) { travelled = route.length; running = false; }
        pos = route.at(travelled);
        push();
    }

    /** Move from p by {@code m} metres along {@code bearingDeg}. */
    private static double[] move(double[] p, double bearingDeg, double m) {
        double R = 6371000.0, br = Math.toRadians(bearingDeg);
        double la = Math.toRadians(p[0]), lo = Math.toRadians(p[1]);
        double la2 = Math.asin(Math.sin(la) * Math.cos(m / R)
                + Math.cos(la) * Math.sin(m / R) * Math.cos(br));
        double lo2 = lo + Math.atan2(Math.sin(br) * Math.sin(m / R) * Math.cos(la),
                Math.cos(m / R) - Math.sin(la) * Math.sin(la2));
        return new double[]{Math.toDegrees(la2), Math.toDegrees(lo2), bearingDeg};
    }

    private static void handleCmd() {
        String cmd = Cfg.readCmd();
        if (cmd == null || cmd.isEmpty()) return;
        try {
            String[] w = cmd.split("\\s+");
            if (cmd.equals("start")) start();
            else if (cmd.equals("stop")) stop();
            else if (cmd.equals("hold")) hold();
            else if (cmd.equals("status")) {
                double[] e = pos != null ? pos : (route != null ? route.at(travelled) : null);
                Log.i(TAG, "state running=" + running + " travelled=" + Math.round(travelled) + " speed=" + speed
                        + " pos=" + (e == null ? "?" : e[0] + "," + e[1])
                        + " nav=" + (navTarget == null ? "-" : navTarget[0] + "," + navTarget[1])
                        + " listeners=" + REGS.size() + " pushes=" + pushes
                        + " age=" + (lastPushMs == 0 ? -1 : (android.os.SystemClock.elapsedRealtime() - lastPushMs))
                        + " gnss=" + Module.gnssCount());
            }
            else if (cmd.equals("shuffle")) startShuffle(4.0);
            else if (w[0].equals("shuffle") && w.length > 1) startShuffle(Double.parseDouble(w[1]));
            else if (w[0].equals("speed") && w.length > 1) setSpeed(Double.parseDouble(w[1]));
            else if (w[0].equals("cadence") && w.length > 1) SensorFaker.setCadence(Double.parseDouble(w[1]));
            else if (w[0].equals("nav") && w.length > 1) {
                String[] ll = w[1].split(",");
                double lat = Double.parseDouble(ll[0]), lng = Double.parseDouble(ll[1]);
                navTarget = new double[]{lat, lng};
                navStop = w.length > 2 ? Double.parseDouble(w[2]) : 3.0;
                shuffleCenter = null;
                if (pos == null) pos = new double[]{lat, lng, 0};
                running = true;
                ensureTicker();
                push();
                Log.i(TAG, "nav target=" + lat + "," + lng + " stop=" + navStop);
            }
            else if (w[0].equals("seek") && w.length > 1) {
                String[] ll = w[1].split(",");
                seekTo(Double.parseDouble(ll[0]), Double.parseDouble(ll[1]));
            }
        } catch (Throwable t) {
            Log.w(TAG, "cmd '" + cmd + "': " + t);
        }
    }

    static Location make(String provider) {
        Location l = new Location(provider == null ? "gps" : provider);
        double[] p = pos;
        if (p == null && route != null) p = route.at(travelled);
        if (p != null) {
            l.setLatitude(p[0]);
            l.setLongitude(p[1]);
            l.setBearing((float) p[2]);
        }
        l.setSpeed((float) (running ? speed : 0));
        l.setAccuracy(3.0f);
        l.setAltitude(18.0f);
        try {
            android.os.Bundle b = new android.os.Bundle();
            b.putInt("satellites", 13);
            b.putInt("satelliteCount", 13);
            b.putFloat("meanCn0", 36.5f);
            b.putFloat("maxCn0", 41.0f);
            l.setExtras(b);
        } catch (Throwable ignored) {
        }
        l.setTime(System.currentTimeMillis());
        l.setElapsedRealtimeNanos(SystemClock.elapsedRealtimeNanos());
        return l;
    }

    static Location current(String provider) {
        Location l = make(provider);
        if (l.getLatitude() == 0 && l.getLongitude() == 0 && last != null) return last;
        last = l;
        return l;
    }

    private static void push() {
        Location l = make("gps");
        last = l;
        pushes++;
        lastPushMs = android.os.SystemClock.elapsedRealtime();
        for (Reg r : REGS) {
            final LocationListener listener = r.l;
            final Location loc = new Location(l);
            try {
                if (r.h != null) r.h.post(new Runnable() {
                    @Override public void run() { listener.onLocationChanged(loc); }
                });
                else listener.onLocationChanged(loc);
            } catch (Throwable ignored) {
            }
        }
    }

    static void register(LocationListener l, Looper looper) {
        if (l == null) return;
        for (Reg r : REGS) if (r.l == l) { ensureTicker(); return; }
        REGS.add(new Reg(l, looper == null ? null : new Handler(looper)));
        // 高德每次重建地图都会 new 一个新的代理 listener；不设上限会一直涨
        while (REGS.size() > 24) REGS.remove(0);
        ensureTicker();
        Log.i(TAG, "location listener += " + l.getClass().getName() + " total=" + REGS.size());
        if (last != null) {
            try { l.onLocationChanged(new Location(last)); } catch (Throwable ignored) {
            }
        }
    }

    static void unregister(LocationListener l) {
        for (Reg r : new ArrayList<>(REGS)) if (r.l == l) REGS.remove(r);
    }
}
