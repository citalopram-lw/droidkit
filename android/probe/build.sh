#!/usr/bin/env bash
# Build the sensor probe APK (pure Java, no native code -> runs as x86_64).
set -euo pipefail
cd "$(dirname "$0")"
SDK="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
BT="$SDK/build-tools/35.0.0"
AJ="$SDK/platforms/android-35/android.jar"
JDK="${DKIT_JDK:-$SDK/jdk-17.0.21+9}"
export JAVA_HOME="$JDK"; export PATH="$JDK/bin:$PATH"
OUT=build
rm -rf "$OUT"; mkdir -p "$OUT/classes" "$OUT/dex"
find src -name '*.java' > "$OUT/sources.txt"
javac -source 8 -target 8 -nowarn -bootclasspath "$AJ" -d "$OUT/classes" @"$OUT/sources.txt"
find "$OUT/classes" -name '*.class' > "$OUT/classes.txt"
"$BT/d8" --lib "$AJ" --min-api 26 --output "$OUT/dex" $(cat "$OUT/classes.txt")
"$BT/aapt2" link -o "$OUT/base.apk" --manifest AndroidManifest.xml -I "$AJ" \
  --min-sdk-version 26 --target-sdk-version 35 --version-code 1 --version-name 1.0
cp "$OUT/base.apk" "$OUT/app.apk"
( cd "$OUT" && zip -q -j app.apk dex/classes.dex )
"$BT/zipalign" -p -f 4 "$OUT/app.apk" "$OUT/aligned.apk"
KS=../module/keystore.jks
[ -f "$KS" ] || KS=keystore.jks
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:droidkit --key-pass pass:droidkit \
  --out droidkit-probe.apk "$OUT/aligned.apk"
ls -l droidkit-probe.apk
