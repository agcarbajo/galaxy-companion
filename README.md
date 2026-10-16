# Galaxy Companion

Native GNOME settings companion for Samsung Galaxy devices running mainline Linux
(Ubuntu + GNOME first).

This repository starts as the extraction of **Tab Companion** from
[ubuntu-galaxy-tab-s9-ultra](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra),
with its full git history. The goal is one application that keeps every Tab
Companion feature and works on any Samsung device with a mainline kernel, enabling
each page only when the hardware behind it is present.

The extracted tree keeps its original layout in this first commit:

- `packaging/ubuntu-gts9u-companion/` — the Debian package tree (app, backend, services)
- `scripts/` — package build, tests and previews
- `docs/` — design and behaviour notes
