[app]
title = WALIBRA
package.name = bluetoothsender
package.domain = org.bleremote
source.dir = .
source.include_exts = py,ttf,otf,json,png
version = 0.1
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #18332E
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0,pyjnius,android,six,arabic-reshaper==3.0.0,python-bidi==0.4.2
orientation = portrait
fullscreen = 1
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_SCAN,BLUETOOTH_CONNECT,ACCESS_FINE_LOCATION,INTERNET,ACCESS_WIFI_STATE,ACCESS_NETWORK_STATE
android.api = 34
android.minapi = 21
android.archs = arm64-v8a
android.add_src = java
android.accept_sdk_license = True
android.ndk = 25b
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
