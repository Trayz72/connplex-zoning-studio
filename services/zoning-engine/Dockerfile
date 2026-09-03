# DWG upload/export needs ODA File Converter, a Qt6 GUI application that
# requires a display server even for silent batch conversion — Render's
# native Python runtime has no such thing (see DEPLOYMENT.md §2c/§4 for the
# full reasoning). This image adds Xvfb (a virtual framebuffer) plus ODA File
# Converter itself, so the exact same services/cad-interop/convert.py that
# already works in local dev (which has a real X11 session) also works here.
#
# Build context is the REPO ROOT, not this directory — cad_extraction.py and
# export_dxf.py both reach across to services/cad-interop/convert.py and
# services/rules-config/registry/ via relative sys.path/file lookups (see
# their own `sys.path.insert(..., "..", "cad-interop", ...)` — this image has
# to reproduce that same sibling-directory layout, not flatten it.
FROM python:3.12-slim

# wget/ca-certificates: fetch the ODA installer below.
RUN apt-get update && apt-get install -y --no-install-recommends wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ODA File Converter — a free tool from the Open Design Alliance, downloaded
# fresh at build time rather than committed (253MB, and gitignored on
# purpose — see DEPLOYMENT.md §1). Verified directly (this session, not
# assumed): this URL 301-redirects straight to a presigned S3 object with no
# login or EULA click-through gate in front of it — a real, scriptable
# direct download. Pinned to 27.1, the exact version already vendored for
# local dev at services/cad-interop/oda/, so behavior matches what's already
# been tested against the real reference DWG files (see DEPLOYMENT.md §3's
# results table). `apt-get install ./oda.deb` (not `dpkg -i`) so apt resolves
# the package's own declared dependencies from Debian's repos.
#
# This is its own RUN step, ordered BEFORE the Xvfb/Qt-library step below,
# specifically so a future tweak to that library list (likely, per the
# comment there) invalidates only that cheap layer — not this 253MB one.
RUN wget -q -O /tmp/oda.deb "https://www.opendesign.com/guestfiles/get?filename=ODAFileConverter_QT6_lnxX64_8.3dll_27.1.deb" \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/oda.deb \
    && rm -f /tmp/oda.deb && rm -rf /var/lib/apt/lists/*

# xvfb: the virtual display ODA File Converter needs to run headless.
# libxcb-util1: modern Debian/Ubuntu ship this instead of the .so.0 name
# ODA's Qt6 build links against — ODA's own install notes (opendesign.com)
# call out this exact symlink fix for "modern Linux."
#
# Everything from libxkbcommon0 onward is NOT declared in the .deb's own
# Depends — the .deb only pulls in what ODAFileConverter's *main binary*
# links against; the Qt "xcb" platform plugin
# (plugins/platforms/libqxcb.so) is dlopen'd at runtime, so its own missing
# dependencies never show up until you actually try to run the thing. Found
# by getting exactly this failure — "qt.qpa.plugin: Could not load the Qt
# platform plugin 'xcb'" — then running `ldd` directly against libqxcb.so
# (not the main binary) inside a real container, which is the only way this
# list surfaces. Verified by then installing these into that same running
# container and successfully converting a real 2.1MB client DWG to a
# byte-for-byte-matching 5.1MB DXF before ever baking this into the image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    libxcb-util1 libxkbcommon0 libfontconfig1 \
    libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-render-util0 libxcb-render0 libxcb-shape0 libxcb-xkb1 \
    && ln -sf /usr/lib/x86_64-linux-gnu/libxcb-util.so.1 /usr/lib/x86_64-linux-gnu/libxcb-util.so.0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/zoning-engine/requirements.txt services/zoning-engine/requirements.txt
RUN pip install --no-cache-dir -r services/zoning-engine/requirements.txt

COPY services/cad-interop/convert.py services/cad-interop/convert.py
COPY services/rules-config/registry services/rules-config/registry
COPY services/zoning-engine services/zoning-engine

WORKDIR /app/services/zoning-engine

# ODA_PATH tells convert.py's find_oda_executable() exactly where to look
# instead of relying on its PATH-search fallbacks — the .deb installs here.
# DISPLAY points at the Xvfb instance the start command below launches.
ENV ODA_PATH=/usr/bin/ODAFileConverter
ENV DISPLAY=:99

EXPOSE 8000
# Starts a virtual display, waits for its X socket to actually exist (a
# fixed short sleep is a real race — Xvfb's own startup time varies), then
# runs the API. $PORT is Render's own convention (it assigns the port; a
# hardcoded 8000 would silently fail to bind what Render actually routes to).
CMD ["sh", "-c", "Xvfb :99 -screen 0 1024x768x16 & for i in $(seq 1 20); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.5; done; exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
