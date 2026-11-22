package com.droidkit.hooks;

import java.lang.reflect.Field;

/** Small reflection helper: Unsafe field access (ART final fields) + allocation. */
final class U {
    static final Object UNSAFE;
    static final Class<?> UC;

    static {
        Object u = null;
        Class<?> c = null;
        try {
            c = Class.forName("sun.misc.Unsafe");
            Field f = c.getDeclaredField("theUnsafe");
            f.setAccessible(true);
            u = f.get(null);
        } catch (Throwable t) {
            u = null;
        }
        UNSAFE = u;
        UC = c;
    }

    static long off(Class<?> c, String name) throws Exception {
        Field f = c.getDeclaredField(name);
        f.setAccessible(true);
        return (Long) UC.getMethod("objectFieldOffset", Field.class).invoke(UNSAFE, f);
    }

    static void setObj(Object o, long off, Object v) throws Exception {
        UC.getMethod("putObject", Object.class, long.class, Object.class).invoke(UNSAFE, o, off, v);
    }

    static void setInt(Object o, long off, int v) throws Exception {
        UC.getMethod("putInt", Object.class, long.class, int.class).invoke(UNSAFE, o, off, v);
    }

    static void setLong(Object o, long off, long v) throws Exception {
        UC.getMethod("putLong", Object.class, long.class, long.class).invoke(UNSAFE, o, off, v);
    }

    static void setFloat(Object o, long off, float v) throws Exception {
        UC.getMethod("putFloat", Object.class, long.class, float.class).invoke(UNSAFE, o, off, v);
    }

    static void setBool(Object o, long off, boolean v) throws Exception {
        UC.getMethod("putBoolean", Object.class, long.class, boolean.class).invoke(UNSAFE, o, off, v);
    }

    static Object alloc(Class<?> c) throws Exception {
        return UC.getMethod("allocateInstance", Class.class).invoke(UNSAFE, c);
    }

    static void setStaticString(Class<?> c, String name, String value) {
        try {
            Field f = c.getDeclaredField(name);
            f.setAccessible(true);
            if (UNSAFE != null) {
                Object base = UC.getMethod("staticFieldBase", Field.class).invoke(UNSAFE, f);
                long off = (Long) UC.getMethod("staticFieldOffset", Field.class).invoke(UNSAFE, f);
                UC.getMethod("putObject", Object.class, long.class, Object.class)
                        .invoke(UNSAFE, base, off, value);
            } else {
                f.set(null, value);
            }
        } catch (Throwable ignored) {
        }
    }

    static void setStaticObject(Class<?> c, String name, Object value) {
        try {
            Field f = c.getDeclaredField(name);
            f.setAccessible(true);
            if (UNSAFE != null) {
                Object base = UC.getMethod("staticFieldBase", Field.class).invoke(UNSAFE, f);
                long off = (Long) UC.getMethod("staticFieldOffset", Field.class).invoke(UNSAFE, f);
                UC.getMethod("putObject", Object.class, long.class, Object.class)
                        .invoke(UNSAFE, base, off, value);
            } else {
                f.set(null, value);
            }
        } catch (Throwable ignored) {
        }
    }
}
