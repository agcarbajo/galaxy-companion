FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-gi python3-gi-cairo python3-dbus python3-markdown-it \
    gir1.2-gtk-4.0 gir1.2-adw-1 libglib2.0-bin libglib2.0-dev-bin dconf-gsettings-backend \
    desktop-file-utils appstream dpkg-dev dbus dbus-x11 xvfb xauth \
    mutter weston adwaita-icon-theme fonts-cantarell librsvg2-common gettext ca-certificates systemd \
    && rm -rf /var/lib/apt/lists/*
