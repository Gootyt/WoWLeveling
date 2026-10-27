# A telefonos alkalmazás (Kivy) fordítása Buildozerrel: a GitHub Actions végzi
# (.github/workflows/android.yml), előtte az android/prepare.py bemásolja a közös modulokat.
# Kézzel, Linuxon: python android/prepare.py && cd android && buildozer android debug

[app]
title = WoW szintezés
package.name = wowszintezes
package.domain = io.github.gootyt
source.dir = app
source.include_exts = py,png,ttf,json
version = 1.0.0
requirements = python3,kivy,certifi,sqlite3,openssl
orientation = portrait
fullscreen = 0
android.permissions = android.permission.INTERNET
android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = True
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
