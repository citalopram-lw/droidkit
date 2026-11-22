#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Rebuild the device image with the ARM-translation bridge renamed and the old
# copies hidden from native scanners (maps + stat).
set -euo pipefail
BASE="${BASE:-droidkit/redroid:15-magisk31}"
TARGET="${TARGET:-droidkit/redroid:15-magisk31-stealth}"
NEW=libqc_platform.so
PREFIX_OLD=libndk_translation_proxy_
PREFIX_NEW=libqc_platform_proxy_lib_
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

cid=$(docker create "$BASE")
echo "[1/5] patch bridge binary"
docker cp "$cid:/system/lib64/libnb.so" "$TMP/$NEW"
python3 - "$TMP/$NEW" <<PY
import sys
p=sys.argv[1]; b=open(p,'rb').read()
n=b.count(b"$PREFIX_OLD")
b=b.replace(b"$PREFIX_OLD", b"$PREFIX_NEW")
open(p,'wb').write(b)
print("  proxy prefix replaced:", n)
PY
docker cp "$TMP/$NEW" "$cid:/system/lib64/$NEW"

echo "[2/5] rename proxy libs (${PREFIX_OLD}* -> ${PREFIX_NEW}*)"
n=0
for f in $(docker cp "$cid:/system/lib64" "$TMP/l64" >/dev/null 2>&1; ls "$TMP/l64" | grep "^${PREFIX_OLD}.*\.so$"); do
  docker cp "$TMP/l64/$f" "$cid:/system/lib64/${PREFIX_NEW}${f#${PREFIX_OLD}}" >/dev/null
  n=$((n+1))
done
echo "  proxies copied: $n"

echo "[3/5] point both prop sources at the new name"
for p in /system/build.prop /vendor/build.prop; do
  docker cp "$cid:$p" "$TMP/$(basename $(dirname $p)).prop"
  sed -i "s|^ro.dalvik.vm.native.bridge=.*|ro.dalvik.vm.native.bridge=$NEW|" "$TMP/$(basename $(dirname $p)).prop"
  docker cp "$TMP/$(basename $(dirname $p)).prop" "$cid:$p"
done

echo "[4/5] whiteout the old bridge copies (overlayfs char 0:0)"
upper=$(docker inspect -f '{{.GraphDriver.Data.UpperDir}}' "$cid")
docker run --rm --privileged -v /:/host alpine chroot /host sh -c "
  mkdir -p '$upper/system/lib64'
  for f in libnb.so libndk_translation.so; do
    rm -f '$upper/system/lib64/'\$f
    mknod '$upper/system/lib64/'\$f c 0 0
  done
  # /.dockerenv lives in the container root; / is mounted ro at runtime so the
  # only way to remove it is a whiteout here (docker recreates it per container).
  rm -f '$upper/.dockerenv'; mknod '$upper/.dockerenv' c 0 0
  echo '  whiteouts created (libnb, libndk_translation, .dockerenv)'" || echo "  whiteout failed"

echo "[5/5] commit"
docker commit -m "droidkit: bridge renamed, old copies whited out" "$cid" "$TARGET" >/dev/null
docker rm "$cid" >/dev/null
echo "image: $TARGET"
