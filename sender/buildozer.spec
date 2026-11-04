[app]
title = BLE Receiver
package.name = blereceiver
package.domain = org.bleremote
source.dir = .
source.include_exts = py,ttf,json
version = 0.1
requirements = hostpython3==3.11.5,python3==3.11.5,kivy==2.3.0,pyjnius,android,six,arabic-reshaper==3.0.0,python-bidi==0.4.2
orientation = portrait
fullscreen = 1
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_SCAN,BLUETOOTH_CONNECT,BLUETOOTH_ADVERTISE,ACCESS_FINE_LOCATION,INTERNET,ACCESS_WIFI_STATE,ACCESS_NETWORK_STATE,READ_EXTERNAL_STORAGE,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_MEDIA_AUDIO
android.api = 34
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a
android.add_src = java
android.accept_sdk_license = True
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
