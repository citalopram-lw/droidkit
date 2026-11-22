package com.droidkit.hooks;

import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Virtual sensor set: fabricates Sensor objects for a device that has no sensor HAL
 * (redroid reports "No Sensors on the device") and streams synthetic samples to the
 * listeners the app registers. Steps come from the accelerometer waveform itself, so
 * the app's own pedometer produces a self-consistent cadence/step count.
 */
public final class SensorFaker {
    private static final String TAG = "DroidKit";
    private static final ConcurrentHashMap<Integer, Sensor> FAKE = new ConcurrentHashMap<>();
    private static final CopyOnWriteArrayList<Reg> REGS = new CopyOnWriteArrayList<>();
    private static final ScheduledExecutorService EXEC = Executors.newSingleThreadScheduledExecutor();
    private static volatile boolean running = false;
    private static double cadenceHz = 3.34;
    private static long t0 = SystemClock.elapsedRealtime();
    private static final Random RND = new Random();
    private static long lastStep = -1;

    static final int ACCEL = Sensor.TYPE_ACCELEROMETER;
    static final int GYRO = Sensor.TYPE_GYROSCOPE;
    static final int MAG = Sensor.TYPE_MAGNETIC_FIELD;
    static final int LIGHT = Sensor.TYPE_LIGHT;
    static final int PROX = Sensor.TYPE_PROXIMITY;
    static final int PRESS = Sensor.TYPE_PRESSURE;
    static final int GRAV = Sensor.TYPE_GRAVITY;
    static final int LIN = Sensor.TYPE_LINEAR_ACCELERATION;
    static final int ROT = Sensor.TYPE_ROTATION_VECTOR;
    static final int STEP_DET = Sensor.TYPE_STEP_DETECTOR;
    static final int STEP_CNT = Sensor.TYPE_STEP_COUNTER;

    static final int[] TYPES = {ACCEL, GYRO, MAG, LIGHT, PROX, PRESS, GRAV, LIN, ROT, STEP_DET, STEP_CNT};

    static final class Reg {
        final SensorEventListener listener;
        final Sensor sensor;
        final int type;
        final Handler handler;
        Reg(SensorEventListener l, Sensor s, int t, Handler h) { listener = l; sensor = s; type = t; handler = h; }
    }

    static void setCadence(double hz) {
        cadenceHz = Math.max(0.5, Math.min(5.0, hz));
    }

    static Sensor sensor(int type) {
        Sensor s = FAKE.get(type);
        if (s != null) return s;
        try {
            s = build(type);
            if (s != null) FAKE.put(type, s);
        } catch (Throwable t) {
            Log.e(TAG, "sensor build " + type + ": " + t);
        }
        return s;
    }

    static boolean isFake(Sensor s) {
        if (s == null) return false;
        for (Sensor f : FAKE.values()) if (f == s) return true;
        return false;
    }

    private static Sensor build(int type) throws Exception {
        Sensor s = (Sensor) U.alloc(Sensor.class);
        String name, vendor;
        float maxRange, resolution, power;
        int minDelay, fifoMax;
        switch (type) {
            case ACCEL: name = "LSM6DSO Accelerometer"; vendor = "STMicroelectronics";
                maxRange = 39.2f; resolution = 0.0012f; power = 0.15f; minDelay = 5000; fifoMax = 0; break;
            case GYRO: name = "LSM6DSO Gyroscope"; vendor = "STMicroelectronics";
                maxRange = 34.9f; resolution = 0.001f; power = 0.5f; minDelay = 5000; fifoMax = 0; break;
            case MAG: name = "AK09918 Magnetometer"; vendor = "AKM";
                maxRange = 4900f; resolution = 0.15f; power = 0.5f; minDelay = 10000; fifoMax = 0; break;
            case LIGHT: name = "TMD3702 Light"; vendor = "AMS";
                maxRange = 1000f; resolution = 1f; power = 0.1f; minDelay = 100000; fifoMax = 0; break;
            case PROX: name = "TMD3702 Proximity"; vendor = "AMS";
                maxRange = 5f; resolution = 5f; power = 0.1f; minDelay = 0; fifoMax = 0; break;
            case PRESS: name = "BMP390 Pressure"; vendor = "Bosch";
                maxRange = 1100f; resolution = 0.01f; power = 0.1f; minDelay = 100000; fifoMax = 0; break;
            case GRAV: name = "LSM6DSO Gravity"; vendor = "STMicroelectronics";
                maxRange = 39.2f; resolution = 0.0012f; power = 0.15f; minDelay = 5000; fifoMax = 0; break;
            case LIN: name = "LSM6DSO Linear Acceleration"; vendor = "STMicroelectronics";
                maxRange = 39.2f; resolution = 0.0012f; power = 0.15f; minDelay = 5000; fifoMax = 0; break;
            case ROT: name = "LSM6DSO Rotation Vector"; vendor = "STMicroelectronics";
                maxRange = 1f; resolution = 1f; power = 0.15f; minDelay = 5000; fifoMax = 0; break;
            case STEP_DET: name = "LSM6DSO Step Detector"; vendor = "STMicroelectronics";
                maxRange = 1f; resolution = 1f; power = 0.15f; minDelay = 0; fifoMax = 0; break;
            case STEP_CNT: name = "LSM6DSO Step Counter"; vendor = "STMicroelectronics";
                maxRange = 65536f; resolution = 1f; power = 0.15f; minDelay = 0; fifoMax = 0; break;
            default: return null;
        }
        U.setObj(s, U.off(Sensor.class, "mName"), name);
        U.setObj(s, U.off(Sensor.class, "mVendor"), vendor);
        U.setInt(s, U.off(Sensor.class, "mVersion"), 1);
        U.setInt(s, U.off(Sensor.class, "mHandle"), 100 + type);
        U.setInt(s, U.off(Sensor.class, "mType"), type);
        U.setFloat(s, U.off(Sensor.class, "mMaxRange"), maxRange);
        U.setFloat(s, U.off(Sensor.class, "mResolution"), resolution);
        U.setFloat(s, U.off(Sensor.class, "mPower"), power);
        U.setInt(s, U.off(Sensor.class, "mMinDelay"), minDelay);
        U.setInt(s, U.off(Sensor.class, "mMaxDelay"), 200000);
        U.setInt(s, U.off(Sensor.class, "mFifoMaxEventCount"), fifoMax);
        U.setInt(s, U.off(Sensor.class, "mFifoReservedEventCount"), 0);
        try { U.setObj(s, U.off(Sensor.class, "mStringType"), "android.sensor." + type); } catch (Throwable ignored) {}
        try { U.setObj(s, U.off(Sensor.class, "mRequiredPermission"), ""); } catch (Throwable ignored) {}
        return s;
    }

    static void register(SensorEventListener l, Sensor s, Handler h) {
        if (l == null || s == null) return;
        for (Reg r : REGS) if (r.listener == l && r.sensor == s) return;
        REGS.add(new Reg(l, s, s.getType(), h));
        start();
        Log.i(TAG, "sensor listener += type=" + s.getType() + " total=" + REGS.size());
    }

    static void unregister(SensorEventListener l, Sensor s) {
        for (Reg r : new ArrayList<>(REGS)) {
            if (r.listener == l && (s == null || r.sensor == s)) REGS.remove(r);
        }
    }

    static synchronized void start() {
        if (running) return;
        running = true;
        t0 = SystemClock.elapsedRealtime();
        EXEC.scheduleAtFixedRate(new Runnable() {
            long tick = 0;
            @Override public void run() {
                try { emitAll(tick++); } catch (Throwable t) { Log.e(TAG, "emit: " + t); }
            }
        }, 0, 20, TimeUnit.MILLISECONDS);
    }

    private static SensorEvent event(Sensor s, float[] v) {
        try {
            SensorEvent e = (SensorEvent) U.alloc(SensorEvent.class);
            U.setObj(e, U.off(SensorEvent.class, "sensor"), s);
            U.setObj(e, U.off(SensorEvent.class, "values"), v);
            U.setInt(e, U.off(SensorEvent.class, "accuracy"), 3);
            U.setLong(e, U.off(SensorEvent.class, "timestamp"), System.nanoTime());
            return e;
        } catch (Throwable t) {
            return null;
        }
    }

    private static void emitAll(long tick) {
        if (REGS.isEmpty()) return;
        double t = (SystemClock.elapsedRealtime() - t0) / 1000.0;
        double ph = 2 * Math.PI * cadenceHz * t;
        float ax = (float) (0.35 * Math.sin(ph * 0.5) + RND.nextGaussian() * 0.02);
        float ay = (float) (0.25 * Math.cos(ph * 0.7) + RND.nextGaussian() * 0.02);
        float az = (float) (9.81 + 1.9 * Math.sin(ph) + RND.nextGaussian() * 0.05);
        long steps = (long) Math.floor(t * cadenceHz);

        for (Reg r : REGS) {
            SensorEvent e = null;
            switch (r.type) {
                case ACCEL:
                    e = event(r.sensor, new float[]{ax, ay, az});
                    break;
                case GRAV:
                    e = event(r.sensor, new float[]{0f, 0f, 9.81f});
                    break;
                case LIN:
                    e = event(r.sensor, new float[]{ax, ay, az - 9.81f});
                    break;
                case GYRO:
                    e = event(r.sensor, new float[]{
                            (float) (0.02 * Math.sin(t)), (float) (0.02 * Math.cos(t)),
                            (float) (0.01 + RND.nextGaussian() * 0.002)});
                    break;
                case MAG:
                    e = event(r.sensor, new float[]{28.4f, -12.1f, 41.7f});
                    break;
                case LIGHT:
                    e = event(r.sensor, new float[]{320f});
                    break;
                case PROX:
                    e = event(r.sensor, new float[]{5f});
                    break;
                case PRESS:
                    e = event(r.sensor, new float[]{1010.2f});
                    break;
                case ROT:
                    e = event(r.sensor, new float[]{0f, 0f, 0f, 1f, 0f});
                    break;
                case STEP_CNT:
                    e = event(r.sensor, new float[]{(float) steps});
                    break;
                case STEP_DET:
                    if (steps != lastStep) e = event(r.sensor, new float[]{1f});
                    break;
                default:
                    break;
            }
            if (e == null) continue;
            if (r.type == STEP_DET) lastStep = steps;
            final SensorEvent ev = e;
            final SensorEventListener l = r.listener;
            try {
                if (r.handler != null) r.handler.post(new Runnable() {
                    @Override public void run() { l.onSensorChanged(ev); }
                });
                else l.onSensorChanged(ev);
            } catch (Throwable ignored) {
            }
        }
    }

    static List<Sensor> list() {
        List<Sensor> out = new ArrayList<>();
        for (int t : TYPES) {
            Sensor s = sensor(t);
            if (s != null) out.add(s);
        }
        return out;
    }
}
