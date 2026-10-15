# Building the native helper

The checked-in `globalPlugins/wetypeCandidates/wetypeTsfBridge64.dll` is a convenience build for 64-bit Windows. The source is `source/wetypeTsfBridge.cpp`.

With the official Zig Windows x86_64 toolchain:

```powershell
zig c++ source/wetypeTsfBridge.cpp -target x86_64-windows-gnu -shared -O2 -o globalPlugins/wetypeCandidates/wetypeTsfBridge64.dll -luser32 -loleaut32 -luuid
```

The helper is loaded by the Python bridge only for the focused editor thread and only while the WeType candidate window is visible.
