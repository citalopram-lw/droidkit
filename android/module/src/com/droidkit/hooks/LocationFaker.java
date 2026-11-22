package com.droidkit.hooks;

import android.location.Location;
import android.location.LocationListener;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** Synthetic GPS: feeds a polyline route at constant speed to registered listeners. */
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
        ensureTicker();
        Log.i(TAG, "route started");
        push();
    }

    static void stop() {
        running = false;
        Log.i(TAG, "route stopped at " + Math.round(travelled) + "m");
    }

    static void hold() {
        running = false;
        Log.i(TAG, "route hold");
    }

    static void seekTo(double lat, double lng) {
        // Inject an ad-hoc two-point route so the app jumps there.
        List<double[]> p = new ArrayList<>();
        p.add(new double[]{lat, lng});
        p.add(new double[]{lat + 0.001, lng});
        route = new Route(p);
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
                    if (running && route != null) {
                        travelled += speed;
                        if (travelled > route.length && !loop) { travelled = route.length; running = false; }
                        push();
                    }
                } catch (Throwable t) { Log.e(TAG, "tick: " + t); }
            }
        }, 1, 1, TimeUnit.SECONDS);
    }

    private static void handleCmd() {
        String cmd = Cfg.readCmd();
        if (cmd == null || cmd.isEmpty()) return;
        try {
            String[] w = cmd.split("\\s+");
            if (cmd.equals("start")) start();
            else if (cmd.equals("stop")) stop();
            else if (cmd.equals("hold")) hold();
            else if (cmd.equals("status")) Log.i(TAG, "state running=" + running + " travelled="
                    + Math.round(travelled) + " speed=" + speed);
            else if (w[0].equals("speed") && w.length > 1) setSpeed(Double.parseDouble(w[1]));
            else if (w[0].equals("cadence") && w.length > 1) SensorFaker.setCadence(Double.parseDouble(w[1]));
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
        double[] p = route == null ? null : route.at(travelled);
        if (p != null) {
            l.setLatitude(p[0]);
            l.setLongitude(p[1]);
            l.setBearing((float) p[2]);
        }
        l.setSpeed((float) (running ? speed : 0));
        l.setAccuracy(3.0f);
        l.setAltitude(18.0f);
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
