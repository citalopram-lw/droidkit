#!/usr/bin/env bash
# Build droidkit/redroid:15-magisk31 — the base image plus a *bootless* Magisk 31.1.
#
# Why this exists: the erstt base ships Magisk 25.2, whose Zygisk predates the
# Android 15 Zygote signatures and resets the native bridge, so ARM-translated
# apps crash as soon as Zygisk is enabled. Magisk 27+ fixed both; this recipe is
# the redroid-script "bootless" layout (magisk + --setup-sbin in bootanim.rc).
#
# Requires: docker, curl, unzip, ~2 GB disk, and the droidkit base image.
set -euo pipefail
BASE="${BASE:-droidkit/redroid:15-magisk}"
TARGET="${TARGET:-droidkit/redroid:15-magisk31}"
APK_URL="${APK_URL:-https://gh-proxy.com/https://github.com/ayasa520/Magisk/releases/download/v31.1/Magisk-v31.1.apk}"
APK_MD5="10304bbeddb6e1bbc7040fc7ec133178"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cd "$WORK"
echo "[1/4] fetch Magisk 31.1 (redroid-compatible fork)"
curl -fL --retry 3 -o magisk.apk "$APK_URL"
echo "$APK_MD5  magisk.apk" | md5sum -c -

echo "[2/4] stage /system/etc/init/magisk"
mkdir -p stage/system/etc/init/magisk
mkdir -p x && unzip -q -o magisk.apk 'lib/x86_64/*' 'assets/*.sh' -d x
for f in x/lib/x86_64/*.so; do
  b=$(basename "$f" .so); b=${b#lib}
  cp "$f" "stage/system/etc/init/magisk/$b"
done
cp x/assets/*.sh stage/system/etc/init/magisk/
cp magisk.apk stage/system/etc/init/magisk/magisk.apk
chmod 755 stage/system/etc/init/magisk/*

echo "[3/4] bootanim.rc (must be 0644 root:root or init silently skips it)"
cat > stage/system/etc/init/bootanim.rc <<'RC'
service bootanim /system/bin/bootanimation
    class core animation
    user graphics
    group graphics audio
    disabled
    oneshot
    ioprio rt 0
    task_profiles MaxPerformance

on post-fs-data
    start logd
    exec u:r:su:s0 root root -- /system/etc/init/magisk/magiskpolicy --live --magisk
    exec u:r:su:s0 root root -- /system/etc/init/magisk/magisk --auto-selinux --setup-sbin /system/etc/init/magisk /sbin
    mkdir /data/adb 0700 root root
    mkdir /data/adb/magisk 0755 root root
    exec -- /system/bin/sh -c "cd /system/etc/init/magisk && cp -p busybox magisk magiskboot magiskinit magiskpolicy *.sh /data/adb/magisk/"
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --post-fs-data
on nonencrypted
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --service
on property:vold.decrypt=trigger_restart_framework
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --service
on property:sys.boot_completed=1
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --boot-complete
on property:init.svc.zygote=restarting
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --zygote-restart
on property:init.svc.zygote=stopped
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --zygote-restart
RC

echo "[4/4] commit image"
cid=$(docker create "$BASE")
docker cp stage/system/. "$cid:/system/"
docker commit -m "droidkit: Magisk 31.1 bootless" "$cid" "$TARGET" >/dev/null
docker rm "$cid" >/dev/null

# docker cp lands 0664; init refuses world/group-writable rc files ("Skipping insecure file").
tmp=$(docker run -d --privileged --entrypoint /system/bin/sh "$TARGET" -c 'chmod 644 /system/etc/init/bootanim.rc; sleep 30' || true)
echo "image: $TARGET"
echo "NOTE: if bootanim.rc permission needs fixing later: adb shell chmod 644 /system/etc/init/bootanim.rc && docker commit"
