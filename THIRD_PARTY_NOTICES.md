# Third-party notices

No third-party binaries or libraries are copied into this repository. The
projects below provide the host platform, vendored source, optional external
tools, or runtime interfaces used by Anker C200 Controls.

## Omarchy

- Upstream: <https://github.com/omacom/omarchy>
- License: MIT
- Role: host plugin platform, QML components, and panel design language

The `WheelSafeSlider` component in `Panel.qml` is adapted from Omarchy's
`Ui/PanelSlider.qml` so mouse-wheel events can be passed to the surrounding
scroll view.

> Copyright (c) David Heinemeier Hansson
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## anker-powerconf-c200-linux-tools

- Upstream: <https://github.com/erans/anker-powerconf-c200-linux-tools>
- License: MIT
- Copyright: Copyright (c) 2026 Eran Sandler
- Role: bundled `anker-c200` controller source and reverse-engineered Anker
  PowerConf C200 control protocol

Unmodified source from upstream commit
`1912f8690802346557f6bc1d1024e31dec1c7273` is included beneath
`vendor/anker-powerconf-c200-linux-tools` and compiled locally on first use.
Its complete MIT license is included beside the source.
No prebuilt controller binary is distributed.

## Quickshell

- Upstream: <https://github.com/quickshell-mirror/quickshell>
- License: LGPL-3.0-only
- Role: system-provided QML shell runtime

The plugin uses the Quickshell installation supplied by Omarchy and does not
bundle or modify Quickshell.

## OBS Studio and obs-websocket

- Upstream: <https://github.com/obsproject/obs-studio>
- License: GPL-2.0-only
- Role: optional external virtual-camera pipeline and loopback WebSocket API

OBS Studio is installed and run separately. This plugin implements its own
small standard-library WebSocket client and does not copy or link OBS code.
