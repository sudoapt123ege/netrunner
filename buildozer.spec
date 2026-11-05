
[app]
title = Netrunner
package.name = netrunner
package.domain = org.sudoapt
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,wav,ogg,mp3
version = 0.1

requirements = python3,pygame-ce

orientation = landscape
fullscreen = 1

android.api = 34
android.minapi = 21
android.ndk_api = 21
android.accept_sdk_license = True
android.archs = armeabi-v7a
android.permissions = INTERNET

p4a.local_recipes = p4a-recipes

[buildozer]
log_level = 2
warn_on_root = 0
