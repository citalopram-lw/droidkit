package com.droidkit.probe;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.util.Log;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;

/**
 * Full-screen surface that logs every MotionEvent field an app can read.
 *
 * This is the verification half of the touch injector: the point of injecting
 * through uinput is that these fields look like a finger on a real panel, so
 * the probe prints them verbatim (deviceId, tool type, pressure, contact size,
 * inter-event timing, timeline history) instead of a pass/fail verdict.
 */
public class TouchProbeView extends View {
    private static final String T = "TouchProbe";

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private long lastEventTime = 0;
    private int count = 0;

    public TouchProbeView(Context c) {
        super(c);
        paint.setColor(0xFFE8E8E8);
        paint.setTextSize(28f);
        setBackgroundColor(0xFF101014);
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        int idx = e.getActionIndex();
        long dt = lastEventTime == 0 ? -1 : e.getEventTime() - lastEventTime;
        lastEventTime = e.getEventTime();
        count++;

        InputDevice dev = InputDevice.getDevice(e.getDeviceId());
        String devName = dev == null ? "null" : dev.getName();
        int devVendor = dev == null ? -1 : dev.getVendorId();
        int devProduct = dev == null ? -1 : dev.getProductId();

        Log.i(T, "action=" + MotionEvent.actionToString(e.getAction())
                + " deviceId=" + e.getDeviceId()
                + " devName=" + devName
                + " vendor=0x" + Integer.toHexString(devVendor)
                + " product=0x" + Integer.toHexString(devProduct)
                + " source=0x" + Integer.toHexString(e.getSource())
                + " toolType=" + e.getToolType(idx)
                + " pressure=" + round(e.getPressure(idx))
                + " size=" + round(e.getSize(idx))
                + " major=" + round(e.getTouchMajor(idx))
                + " minor=" + round(e.getTouchMinor(idx))
                + " x=" + round(e.getX(idx)) + " y=" + round(e.getY(idx))
                + " dt_ms=" + dt
                + " history=" + e.getHistorySize()
                + " sinceDown_ms=" + (e.getEventTime() - e.getDownTime())
                + " flags=0x" + Integer.toHexString(e.getFlags())
                + " precision=" + round(e.getXPrecision()) + "/" + round(e.getYPrecision()));

        invalidate();
        return true;
    }

    private static String round(float v) {
        return String.format("%.3f", v);
    }

    @Override
    protected void onDraw(Canvas c) {
        super.onDraw(c);
        c.drawText("DroidKit touch probe", 40, 80, paint);
        paint.setTextSize(22f);
        c.drawText("events logged: " + count, 40, 130, paint);
        c.drawText("tap/swipe anywhere; results go to logcat -s TouchProbe", 40, 170, paint);
    }
}
