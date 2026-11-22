#!/usr/bin/env bash
# Build the DroidKit Xposed/LSPosed module APK.
# Requires: android-sdk build-tools 35.0.0, platforms/android-35, JDK 17.
set -euo pipefail
cd "$(dirname "$0")"

SDK="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
BT="$SDK/build-tools/35.0.0"
AJ="$SDK/platforms/android-35/android.jar"
JDK="${DKIT_JDK:-$SDK/jdk-17.0.21+9}"
export JAVA_HOME="$JDK"
export PATH="$JDK/bin:$PATH"

OUT=build
rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/dex"

echo "[1/5] javac"
# The Xposed API must be a compile-time dependency only: LSPosed/Vector refuses
# modules whose APK bundles de.robv.android.xposed.* classes.
mkdir -p "$OUT/stub"
javac -source 8 -target 8 -nowarn -bootclasspath "$AJ" -d "$OUT/stub" $(find xposed_stub -name '*.java')
( cd "$OUT/stub" && jar cf "../xposed-api-stub.jar" . )
find src -name '*.java' > "$OUT/sources.txt"
javac -source 8 -target 8 -nowarn -bootclasspath "$AJ" -cp "$OUT/xposed-api-stub.jar" \
  -d "$OUT/classes" @"$OUT/sources.txt" 2>&1 | grep -v 'bootstrap class path' || true

echo "[2/5] d8"
find "$OUT/classes" -name '*.class' > "$OUT/classes.txt"
"$BT/d8" --lib "$AJ" --min-api 26 --output "$OUT/dex" $(cat "$OUT/classes.txt")

echo "[3/5] aapt2 link"
"$BT/aapt2" link -o "$OUT/base.apk" --manifest AndroidManifest.xml \
  -I "$AJ" --min-sdk-version 26 --target-sdk-version 35 \
  --version-code 1 --version-name 1.0

echo "[4/5] package"
cp "$OUT/base.apk" "$OUT/app.apk"
( cd "$OUT" && zip -q -j app.apk dex/classes.dex )
python3 - "$OUT/app.apk" <<'PY'
import sys, zipfile
apk = sys.argv[1]
with zipfile.ZipFile(apk, 'a', zipfile.ZIP_DEFLATED) as z:
    z.writestr('assets/xposed_init', 'com.droidkit.hooks.Module\n')
PY
"$BT/zipalign" -p -f 4 "$OUT/app.apk" "$OUT/aligned.apk"

echo "[5/5] sign"
KS=keystore.jks
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" -alias droidkit -keyalg RSA -keysize 2048 \
    -validity 10000 -storepass droidkit -keypass droidkit \
    -dname "CN=DroidKit, O=DroidKit, C=CN" >/dev/null 2>&1
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:droidkit --key-pass pass:droidkit \
  --out droidkit-hooks.apk "$OUT/aligned.apk"
"$BT/apksigner" verify --print-certs droidkit-hooks.apk | head -3
ls -l droidkit-hooks.apk
echo "built: $(pwd)/droidkit-hooks.apk"
