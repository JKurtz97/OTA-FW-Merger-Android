=== 1. PATCH main.py (UNIVERSAL COLOROS/OOS REGIONALHYBRID & SUPERHYBRID + LIVE ROOT META + FULL DUMP + SHA-256) ===
Patched main.py: Universal ColorOS/OOS RegionalHybrid & SuperHybrid + Live Root META-INF + Full System Dump + SHA-256 checks.
=== 2. BUMP VERSION TO 1.6 (versionCode 1060000), REPACK DIST BUNDLE & BUMP private_version ===
/root/build/OTAFirmwareMerger/main.py:1056: SyntaxWarning: "\." is an invalid escape sequence. Such sequences will not work in the future. Did you mean "\\."? A raw string is also an option.
  "grep -rhoE 'https?://(android\.googleapis\.com/packages/ota-api/package/[^<>[:space:]&]+|[^<>[:space:]&]*allawn[^<>[:space:]&]*\.zip[^<>[:space:]&]*)' "
/root/build/OTAFirmwareMerger/main.py:1060: SyntaxWarning: "\." is an invalid escape sequence. Such sequences will not work in the future. Did you mean "\\."? A raw string is also an option.
  "logcat -d 2>/dev/null | grep -oE 'https?://(android\.googleapis\.com/packages/ota-api/package/[^<>[:space:]&]+|[^<>[:space:]&]*allawn[^<>[:space:]&]*\.zip[^<>[:space:]&]*)' | tail -n 30; "
Updated build.gradle -> versionName 1.6 / versionCode 1060000
Updated buildozer.spec -> version = 1.6
Updated bundle: private.tar ['main.py']
Bumped private_version -> 1795595137
=== 3. GRADLE ASSEMBLE (v1.6 Universal ColorOS / OOS) ===
To honour the JVM settings for this build a single-use Daemon process will be forked. For more on this, please refer to https://docs.gradle.org/8.14.3/userguide/gradle_daemon.html#sec:disabling_the_daemon in the Gradle documentation.
Daemon will be stopped at the end of the build 

> Configure project :
WARNING: The option setting 'android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2' is experimental.
Warning: SDK processing. This version only understands SDK XML versions up to 3 but an SDK XML file of version 4 was encountered. This can happen if you use versions of Android Studio and the command-line tools that were released at different times.

> Task :preBuild UP-TO-DATE
> Task :preDebugBuild UP-TO-DATE
> Task :mergeDebugNativeDebugMetadata NO-SOURCE
> Task :javaPreCompileDebug UP-TO-DATE
> Task :checkDebugAarMetadata UP-TO-DATE
> Task :generateDebugResValues UP-TO-DATE
> Task :mapDebugSourceSetPaths
> Task :generateDebugResources
> Task :mergeDebugResources
> Task :packageDebugResources
> Task :parseDebugLocalResources
> Task :createDebugCompatibleScreenManifests UP-TO-DATE
> Task :extractDeepLinksDebug UP-TO-DATE
> Task :processDebugMainManifest UP-TO-DATE
> Task :processDebugManifest UP-TO-DATE
> Task :processDebugManifestForPackage UP-TO-DATE
> Task :processDebugResources
> Task :compileDebugJavaWithJavac UP-TO-DATE
> Task :mergeDebugShaders UP-TO-DATE
> Task :compileDebugShaders NO-SOURCE
> Task :generateDebugAssets UP-TO-DATE
> Task :mergeDebugAssets
> Task :compressDebugAssets
> Task :processDebugJavaRes NO-SOURCE
> Task :mergeDebugJavaResource UP-TO-DATE
> Task :checkDebugDuplicateClasses UP-TO-DATE
> Task :desugarDebugFileDependencies UP-TO-DATE
> Task :mergeExtDexDebug UP-TO-DATE
> Task :mergeLibDexDebug UP-TO-DATE
> Task :dexBuilderDebug UP-TO-DATE
> Task :mergeProjectDexDebug UP-TO-DATE
> Task :mergeDebugJniLibFolders UP-TO-DATE
> Task :mergeDebugNativeLibs UP-TO-DATE
> Task :stripDebugDebugSymbols UP-TO-DATE
> Task :validateSigningDebug UP-TO-DATE
> Task :writeDebugAppMetadata UP-TO-DATE
> Task :writeDebugSigningConfigVersions UP-TO-DATE
> Task :packageDebug
> Task :createDebugApkListingFileRedirect UP-TO-DATE
> Task :assembleDebug

[Incubating] Problems report is available at: file:///root/build/OTAFirmwareMerger/.buildozer/android/platform/build-arm64-v8a/dists/otafwmerger/build/reports/problems/problems-report.html

Deprecated Gradle features were used in this build, making it incompatible with Gradle 9.0.

You can use '--warning-mode all' to show the individual deprecation warnings and determine if they come from your own scripts or plugins.

For more on this, please refer to https://docs.gradle.org/8.14.3/userguide/command_line_interface.html#sec:command_line_warnings in the Gradle documentation.

BUILD SUCCESSFUL in 19s
33 actionable tasks: 9 executed, 24 up-to-date
'.buildozer/android/platform/build-arm64-v8a/dists/otafwmerger/build/outputs/apk/debug/otafwmerger-debug.apk' -> '/sdcard/Download/OTAFWMerger-v1.6-JKurtz-arm64-v8a.apk'
-rw-rw---- 1 10389 1023 195M Nov 24 23:25 /sdcard/Download/OTAFWMerger-v1.6-JKurtz-arm64-v8a.apk
SUCCESS! Ready to install: /sdcard/Download/OTAFWMerger-v1.6-JKurtz-arm64-v8a.apk
