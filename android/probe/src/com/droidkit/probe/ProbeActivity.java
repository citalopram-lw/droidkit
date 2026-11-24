package com.droidkit.probe;

import android.app.Activity;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.location.Location;
import android.location.LocationManager;
import android.os.Bundle;
import android.util.Log;

import java.util.List;

/** Minimal probe: prints the sensor list, a few accel/step samples and GPS. */
public class ProbeActivity extends Activity implements SensorEventListener {
    private static final String T = "SensorProbe";
    private final int[] counts = new int[64];

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setContentView(new TouchProbeView(this));

        SensorManager sm = (SensorManager) getSystemService(SENSOR_SERVICE);
        List<Sensor> all = sm.getSensorList(Sensor.TYPE_ALL);
        Log.i(T, "sensor_count=" + all.size());
        for (Sensor s : all) {
            Log.i(T, "SENSOR type=" + s.getType() + " name=" + s.getName()
                    + " vendor=" + s.getVendor() + " maxRange=" + s.getMaximumRange()
                    + " resolution=" + s.getResolution());
        }
        Sensor acc = sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
        Log.i(T, "accel=" + (acc == null ? "null" : acc.getName()));
        if (acc != null) sm.registerListener(this, acc, SensorManager.SENSOR_DELAY_GAME);
        Sensor step = sm.getDefaultSensor(Sensor.TYPE_STEP_COUNTER);
        Log.i(T, "step_counter=" + (step == null ? "null" : step.getName()));
        if (step != null) sm.registerListener(this, step, SensorManager.SENSOR_DELAY_NORMAL);
        Sensor det = sm.getDefaultSensor(Sensor.TYPE_STEP_DETECTOR);
        Log.i(T, "step_detector=" + (det == null ? "null" : det.getName()));
        if (det != null) sm.registerListener(this, det, SensorManager.SENSOR_DELAY_NORMAL);

        try {
            LocationManager lm = (LocationManager) getSystemService(LOCATION_SERVICE);
            Location l = lm.getLastKnownLocation("gps");
            Log.i(T, "gps=" + (l == null ? "null" :
                    l.getLatitude() + "," + l.getLongitude() + " acc=" + l.getAccuracy()
                            + " speed=" + l.getSpeed() + " bearing=" + l.getBearing()));
        } catch (Throwable t) {
            Log.e(T, "gps_err=" + t);
        }
    }

    @Override
    public void onSensorChanged(SensorEvent e) {
        int type = e.sensor.getType();
        if (type >= 0 && type < counts.length && counts[type] < 5) {
            counts[type]++;
            StringBuilder sb = new StringBuilder("EVENT type=").append(type)
                    .append(" values=");
            for (float v : e.values) sb.append(String.format("%.3f ", v));
            sb.append("ts=").append(e.timestamp);
            Log.i(T, sb.toString());
        }
    }

    @Override
    public void onAccuracyChanged(Sensor s, int accuracy) {
        Log.i(T, "ACCURACY type=" + s.getType() + " acc=" + accuracy);
    }
}
