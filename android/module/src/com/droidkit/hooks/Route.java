package com.droidkit.hooks;

import java.util.ArrayList;
import java.util.List;

/** Polyline route with constant-speed interpolation. */
public final class Route {
    public final List<double[]> pts = new ArrayList<>();
    public final double[] cum;      // cumulative metres at each vertex
    public final double length;

    public Route(List<double[]> points) {
        if (points == null) points = new ArrayList<>();
        if (points.size() == 1) pts.add(points.get(0));
        else pts.addAll(points);
        cum = new double[pts.size()];
        double total = 0;
        for (int i = 1; i < pts.size(); i++) {
            total += dist(pts.get(i - 1), pts.get(i));
            cum[i] = total;
        }
        length = total;
    }

    static double dist(double[] a, double[] b) {
        double R = 6371000.0;
        double la1 = Math.toRadians(a[0]), la2 = Math.toRadians(b[0]);
        double dla = la2 - la1;
        double dlo = Math.toRadians(b[1] - a[1]);
        double h = Math.sin(dla / 2) * Math.sin(dla / 2)
                + Math.cos(la1) * Math.cos(la2) * Math.sin(dlo / 2) * Math.sin(dlo / 2);
        return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
    }

    static double bearing(double[] a, double[] b) {
        double la1 = Math.toRadians(a[0]), la2 = Math.toRadians(b[0]);
        double dlo = Math.toRadians(b[1] - a[1]);
        double y = Math.sin(dlo) * Math.cos(la2);
        double x = Math.cos(la1) * Math.sin(la2) - Math.sin(la1) * Math.cos(la2) * Math.cos(dlo);
        double deg = Math.toDegrees(Math.atan2(y, x));
        return (deg + 360.0) % 360.0;
    }

    /** @return {lat, lng, bearingDeg} at arc-length s (loops when modified). */
    public double[] at(double s) {
        if (pts.isEmpty()) return null;
        if (pts.size() == 1) return new double[]{pts.get(0)[0], pts.get(0)[1], 0};
        if (length <= 0) return new double[]{pts.get(0)[0], pts.get(0)[1], 0};
        double d = s;
        while (d > length) d -= length;
        while (d < 0) d += length;
        int i = 1;
        while (i < cum.length - 1 && cum[i] < d) i++;
        double seg = cum[i] - cum[i - 1];
        double f = seg <= 0 ? 0 : (d - cum[i - 1]) / seg;
        double[] a = pts.get(i - 1), b = pts.get(i);
        return new double[]{
                a[0] + (b[0] - a[0]) * f,
                a[1] + (b[1] - a[1]) * f,
                bearing(a, b)
        };
    }
}
