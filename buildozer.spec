[app]
title = OTA FW Merger
package.name = otafwmerger
package.domain = com.jkurtz
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,key,pem,pk8,zip
version = 1.9.5
requirements = python3,shiboken6,PySide6
orientation = portrait
osx.kivy_version = 2.2.0
fullscreen = 0
android.archs = arm64-v8a
android.allow_backup = True
ios.kivy_ios_url = https://github.com/kivy/kivy-ios
ios.kivy_ios_branch = master
ios.ios_deploy_url = https://github.com/phonegap/ios-deploy
ios.ios_deploy_branch = 1.12.2
ios.codesign.allowed = false
android.ndk_path = /root/android/ndk/android-ndk-r29
android.sdk_path = /root/android/sdk
android.api = 35
android.minapi = 28
android.ndk_api = 28
android.no-byte-compile-python = True
p4a.bootstrap = qt
p4a.local_recipes = /root/build/OTAFirmwareMerger/deployment/recipes
p4a.branch = master
p4a.commit = 58d21141f17c889bf8585f5665921d72028f8831
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED
android.add_jars = /root/build/OTAFirmwareMerger/deployment/jar/PySide6/jar/Qt6AndroidBindings.jar,/root/build/OTAFirmwareMerger/deployment/jar/PySide6/jar/Qt6Android.jar
p4a.extra_args = --qt-libs=Widgets,Gui,Core --load-local-libs=plugins_platforms_qtforandroid --init-classes=
icon.filename = %(source.dir)s/icon.png

[buildozer]
log_level = 2
warn_on_root = 1
bin_dir = /root/build/OTAFirmwareMerger

android.add_libs_arm64_v8a = libs/arm64-v8a/*.so
android.skip_update = True
android.accept_sdk_license = True
