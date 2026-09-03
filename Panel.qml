pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  // Injected by omarchy-shell for third-party plugins.
  property var manifest: null
  moduleName: "io.github.camerontucker.anker-c200"
  ipcTarget: "anker.c200"
  manageIpc: false

  readonly property string backend: Qt.resolvedUrl("anker_c200_backend.py").toString().replace("file://", "")
  readonly property string obsBackend: Qt.resolvedUrl("obs_control.py").toString().replace("file://", "")
  readonly property var obsCameraDevice: {
    const inputs = mediaDevices.videoInputs
    for (let index = 0; index < inputs.length; index += 1) {
      if (String(inputs[index].description).toLowerCase().indexOf("obs virtual camera") >= 0)
        return inputs[index]
    }
    return mediaDevices.defaultVideoInput
  }
  readonly property bool obsCameraAvailable:
    String(obsCameraDevice.description || "").toLowerCase().indexOf("obs virtual camera") >= 0
  readonly property var directCameraDevice: {
    const inputs = mediaDevices.videoInputs
    for (let index = 0; index < inputs.length; index += 1) {
      const name = String(inputs[index].description).toLowerCase()
      if (name.indexOf("anker powerconf c200") >= 0 || name.indexOf("powerconf c200") >= 0)
        return inputs[index]
    }
    return mediaDevices.defaultVideoInput
  }
  readonly property bool directCameraAvailable: {
    const name = String(directCameraDevice.description || "").toLowerCase()
    return name.indexOf("anker powerconf c200") >= 0 || name.indexOf("powerconf c200") >= 0
  }
  readonly property bool useObsPreview: statusReady && obsRunning && obsCameraAvailable
  readonly property bool useDirectPreview: statusReady && !obsRunning && directCameraAvailable
  readonly property bool previewAvailable: useObsPreview || useDirectPreview
  readonly property var previewCameraDevice: useObsPreview ? obsCameraDevice : directCameraDevice
  property bool connected: false
  property bool controllerAvailable: false
  property string controllerSetupError: ""
  property bool obsRunning: false
  property bool statusReady: false
  // Track preview ownership separately from Panel.opened so an IPC close can
  // release the physical camera immediately, even while the panel animates.
  property bool previewActive: false
  property bool readbackAvailable: false
  property bool profileApplied: false
  property var profileDrift: []
  property var driverDefaults: ({})
  property var busyProcesses: []
  property string previewErrorText: ""
  property bool obsConnected: false
  property bool virtualCameraActive: false
  property int obsSourceWidth: 0
  property int obsSourceHeight: 0
  property int obsOutputWidth: 0
  property int obsOutputHeight: 0
  property real obsFps: 0
  property int cropLeft: 0
  property int cropRight: 0
  property int cropTop: 0
  property int cropBottom: 0
  property int directPreviewWidth: 0
  property int directPreviewHeight: 0
  property string statusText: "Checking camera…"
  property string fov: "narrow"
  property bool autoWhiteBalance: false
  property bool autofocus: true
  property int brightness: 50
  property int contrast: 50
  property int saturation: 54
  property int temperature: 5500
  property int sharpness: 42
  property int zoom: 122
  property int disconnectRetries: 0
  property real pendingPanX: 0
  property real pendingPanY: 0
  property real panPreviewWidth: 1
  property real panPreviewHeight: 1
  property bool framingReady: false
  property bool framingBusy: false
  property int framingSequence: 0
  property string framingStatus: "DRAG THE PREVIEW TO REFRAME"
  readonly property string modeDetails: {
    if (useObsPreview) {
      const input = obsSourceWidth > 0 ? obsSourceWidth + "×" + obsSourceHeight : "INPUT UNKNOWN"
      const output = obsOutputWidth > 0 ? obsOutputWidth + "×" + obsOutputHeight : "OUTPUT UNKNOWN"
      const fps = obsFps > 0 ? " · " + obsFps + " FPS" : ""
      const virtualCamera = virtualCameraActive ? "" : " · VIRTUAL CAMERA STOPPED"
      return "OBS · " + input + " → " + output + fps + virtualCamera
    }
    if (useDirectPreview) {
      if (directPreviewWidth > 0)
        return "DIRECT · " + directPreviewWidth + "×" + directPreviewHeight
      return "DIRECT · ANKER C200"
    }
    return obsRunning ? "OBS · VIRTUAL CAMERA UNAVAILABLE" : "CAMERA PREVIEW UNAVAILABLE"
  }
  readonly property string cropDetails: useObsPreview
    ? "CROP · L " + cropLeft + "  R " + cropRight + "  T " + cropTop + "  B " + cropBottom
    : ""

  function refresh() {
    if (backend !== "" && !stateProc.running && !actionProc.running) stateProc.running = true
  }

  function refreshObsState() {
    if (obsBackend !== "" && obsRunning && !obsStateProc.running) {
      obsStateProc.command = ["python3", obsBackend, "state"]
      obsStateProc.running = true
    }
  }

  function refreshAutoTemperature() {
    if (backend !== "" && opened && connected && autoWhiteBalance
        && !actionProc.running && !autoTemperatureProc.running)
      autoTemperatureProc.running = true
  }

  function openPanel() {
    statusReady = false
    previewActive = true
    root.open()
    refresh()
  }

  function closePanel() {
    previewActive = false
    root.close()
  }

  function setControl(name, value) {
    if (!controllerAvailable) {
      statusText = controllerSetupError !== ""
        ? "CONTROLLER SETUP FAILED · " + controllerSetupError.toUpperCase()
        : "PREVIEW ONLY · CONTROLLER UNAVAILABLE"
      return
    }
    if (actionProc.running) return
    if (stateProc.running) stateProc.running = false
    if (name === "fov") fov = String(value)
    else if (name === "white_balance_automatic")
      autoWhiteBalance = value === true || value === "on" || value === "true" || value === "1"
    else if (name === "focus_automatic_continuous")
      autofocus = value === true || value === "on" || value === "true" || value === "1"
    else if (name === "brightness") brightness = Number(value)
    else if (name === "contrast") contrast = Number(value)
    else if (name === "saturation") saturation = Number(value)
    else if (name === "white_balance_temperature") temperature = Number(value)
    else if (name === "sharpness") sharpness = Number(value)
    else if (name === "zoom_absolute") zoom = Number(value)
    statusText = "Applying…"
    actionProc.command = ["python3", backend, "set", name, String(value)]
    actionProc.running = true
  }

  function resetControl(name) {
    if (!controllerAvailable || !hasDriverDefault(name) || actionProc.running) return
    statusText = "RESETTING " + String(name).replace(/_/g, " ").toUpperCase() + "…"
    actionProc.command = ["python3", backend, "reset", name]
    actionProc.running = true
  }

  function hasDriverDefault(name) {
    return driverDefaults && driverDefaults[name] !== undefined
  }

  function startObs() {
    if (!obsRunning) Quickshell.execDetached(["obs", "--startvirtualcam"])
  }

  function applySavedSettings() {
    if (!controllerAvailable || !connected || actionProc.running) return
    statusText = "APPLYING SAVED SETTINGS…"
    actionProc.command = ["python3", backend, "apply"]
    actionProc.running = true
  }

  function queuePan(dx, dy, previewWidth, previewHeight) {
    pendingPanX += dx
    pendingPanY += dy
    panPreviewWidth = Math.max(1, previewWidth)
    panPreviewHeight = Math.max(1, previewHeight)
    panTimer.restart()
  }

  function flushPan() {
    if (framingBusy || !framingReady || !framingProc.running
        || (Math.abs(pendingPanX) < 0.5 && Math.abs(pendingPanY) < 0.5)) return
    const dx = pendingPanX
    const dy = pendingPanY
    pendingPanX = 0
    pendingPanY = 0
    framingStatus = "MOVING SHOT…"
    framingBusy = true
    framingSequence += 1
    framingProc.write(JSON.stringify({
      command: "pan",
      sequence: framingSequence,
      arguments: [dx, dy, panPreviewWidth, panPreviewHeight]
    }) + "\n")
  }

  function centerFraming() {
    if (!framingReady || framingBusy) return
    pendingPanX = 0
    pendingPanY = 0
    framingStatus = "CENTERING SHOT…"
    framingBusy = true
    framingSequence += 1
    framingProc.write(JSON.stringify({
      command: "center",
      sequence: framingSequence,
      arguments: []
    }) + "\n")
  }

  function handleFramingResponse(line) {
    const output = String(line || "").trim()
    if (output === "") return
    framingBusy = false
    try {
      const data = JSON.parse(output)
      framingReady = Boolean(data.connected)
      if (framingReady) {
        updateObsState(data)
        framingStatus = "DRAG THE PREVIEW TO REFRAME"
        if (Math.abs(pendingPanX) >= 0.5 || Math.abs(pendingPanY) >= 0.5)
          panTimer.restart()
      } else {
        framingStatus = String(data.error || "OBS CONTROL UNAVAILABLE").toUpperCase()
        framingReconnectTimer.restart()
      }
    } catch (error) {
      framingReady = false
      framingStatus = "OBS CONTROL UNAVAILABLE"
      framingReconnectTimer.restart()
    }
  }

  function requestFramingState() {
    if (!framingProc.running || framingBusy) return
    framingBusy = true
    framingSequence += 1
    framingProc.write(JSON.stringify({
      command: "state",
      sequence: framingSequence,
      arguments: []
    }) + "\n")
  }

  function updateObsState(data) {
    obsConnected = Boolean(data.connected)
    if (!obsConnected) {
      virtualCameraActive = false
      return
    }
    virtualCameraActive = Boolean(data.virtual_camera_active)
    obsSourceWidth = Number(data.source_width || 0)
    obsSourceHeight = Number(data.source_height || 0)
    obsOutputWidth = Number(data.output_width || 0)
    obsOutputHeight = Number(data.output_height || 0)
    obsFps = Number(data.fps || 0)
    cropLeft = Number(data.crop_left || 0)
    cropRight = Number(data.crop_right || 0)
    cropTop = Number(data.crop_top || 0)
    cropBottom = Number(data.crop_bottom || 0)
  }

  function updateState(data) {
    const nextConnected = Boolean(data.connected)
    const nextObsRunning = Boolean(data.obs_running)
    const obsJustStarted = !obsRunning && nextObsRunning
    const shouldApply = nextConnected && !connected && Boolean(data.controller_available)
    if (!nextConnected && connected && disconnectRetries < 3) {
      disconnectRetries += 1
      statusText = "RECONNECTING CAMERA…"
      reconnectDelay.restart()
      return
    }
    disconnectRetries = 0
    statusReady = true
    connected = nextConnected
    controllerAvailable = Boolean(data.controller_available)
    controllerSetupError = String(data.controller_setup_error || "")
    obsRunning = nextObsRunning
    readbackAvailable = Boolean(data.readback_available)
    profileApplied = Boolean(data.profile_applied)
    profileDrift = Array.isArray(data.profile_drift) ? data.profile_drift : []
    driverDefaults = data.driver_defaults || ({})
    busyProcesses = Array.isArray(data.busy_processes) ? data.busy_processes : []
    fov = String(data.fov || "narrow")
    autoWhiteBalance = Boolean(data.white_balance_automatic)
    autofocus = Boolean(data.focus_automatic_continuous)
    brightness = Number(data.brightness)
    contrast = Number(data.contrast)
    saturation = Number(data.saturation)
    temperature = Number(data.white_balance_temperature)
    sharpness = Number(data.sharpness)
    zoom = Number(data.zoom_absolute)
    if (!connected) statusText = "DISCONNECTED · CHANGES WILL BE SAVED"
    else if (!controllerAvailable)
      statusText = controllerSetupError !== ""
        ? "CONTROLLER SETUP FAILED · " + controllerSetupError.toUpperCase()
        : "PREVIEW ONLY · CONTROLLER UNAVAILABLE"
    else if (!obsRunning && busyProcesses.length > 0)
      statusText = "CAMERA IN USE BY " + String(busyProcesses[0].name).toUpperCase()
    else if (readbackAvailable && profileDrift.length > 0)
      statusText = "PROFILE DRIFT · " + profileDrift.map(function(name) {
        return String(name).replace(/_/g, " ").toUpperCase()
      }).join(", ")
    else if (!readbackAvailable) statusText = "CONNECTED · HARDWARE READBACK UNAVAILABLE"
    else statusText = "CONNECTED · SETTINGS SAVE AUTOMATICALLY"
    if (shouldApply) Qt.callLater(root.applySavedSettings)
    if (obsJustStarted) obsProfileDelay.restart()
    if (obsRunning) root.refreshObsState()
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.openPanel() }
    function close(): void { root.closePanel() }
    function toggle(): void {
      if (root.opened) root.closePanel()
      else root.openPanel()
    }
    function refresh(): string { root.refresh(); return "ok" }
    function apply(): string { root.applySavedSettings(); return "ok" }
    function startObs(): string { root.startObs(); return "ok" }
    function diagnostics(): string {
      return JSON.stringify({
        opened: root.opened,
        previewActive: root.previewActive,
        obsRunning: root.obsRunning,
        useObsPreview: root.useObsPreview,
        framingProcess: framingProc.running,
        framingReady: root.framingReady,
        framingBusy: root.framingBusy,
        autoWhiteBalance: root.autoWhiteBalance,
        whiteBalanceTemperature: root.temperature
      })
    }
  }

  Process {
    id: stateProc
    command: ["python3", root.backend, "state"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        const output = String(text || "").trim()
        if (output === "") {
          root.statusText = "RETRYING CAMERA STATUS…"
          reconnectDelay.restart()
          return
        }
        try { root.updateState(JSON.parse(output)) }
        catch (error) {
          root.statusText = "COULD NOT READ CAMERA STATE"
          reconnectDelay.restart()
        }
      }
    }
  }

  Process {
    id: framingProc
    command: ["python3", root.obsBackend, "serve"]
    stdinEnabled: true
    running: root.previewActive && root.obsRunning
    stdout: SplitParser {
      onRead: function(line) { root.handleFramingResponse(line) }
    }
    onStarted: {
      root.framingReady = false
      root.framingBusy = false
    }
    onExited: {
      root.framingReady = false
      root.framingBusy = false
      root.pendingPanX = 0
      root.pendingPanY = 0
    }
  }

  Process {
    id: obsStateProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        const output = String(text || "").trim()
        if (output === "") return
        try { root.updateObsState(JSON.parse(output)) }
        catch (error) { root.obsConnected = false }
      }
    }
  }

  Timer {
    id: panTimer
    interval: 24
    repeat: false
    onTriggered: root.flushPan()
  }

  Timer {
    id: framingReconnectTimer
    interval: 600
    repeat: false
    onTriggered: root.requestFramingState()
  }

  MediaDevices { id: mediaDevices }

  Loader {
    id: previewCaptureLoader
    active: root.previewActive && root.previewAvailable
    onActiveChanged: {
      if (active) root.previewErrorText = ""
      else {
        root.directPreviewWidth = 0
        root.directPreviewHeight = 0
      }
    }
    sourceComponent: Component {
      CaptureSession {
        camera: Camera {
          id: previewCamera
          cameraDevice: root.previewCameraDevice
          active: true
          onCameraFormatChanged: {
            const resolution = cameraFormat.resolution
            root.directPreviewWidth = Number(resolution.width || 0)
            root.directPreviewHeight = Number(resolution.height || 0)
          }
          onErrorOccurred: function(error, errorString) {
            root.previewErrorText = error === Camera.NoError ? "" : String(errorString || "Camera preview unavailable")
          }
        }
        videoOutput: previewOutput
      }
    }
  }

  Process {
    id: actionProc
    stdout: StdioCollector { waitForEnd: true }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var message = String(text || "").trim()
        if (message !== "") root.statusText = message.toUpperCase()
      }
    }
    onRunningChanged: if (!running) refreshDelay.restart()
  }

  Process {
    id: autoTemperatureProc
    command: ["python3", root.backend, "read", "white_balance_temperature"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        const output = String(text || "").trim()
        if (output === "") return
        try {
          const data = JSON.parse(output)
          if (data.white_balance_temperature !== undefined)
            root.temperature = Number(data.white_balance_temperature)
        } catch (error) {}
      }
    }
  }

  Timer {
    id: refreshDelay
    interval: 180
    repeat: false
    onTriggered: root.refresh()
  }

  Timer {
    id: reconnectDelay
    interval: 400
    repeat: false
    onTriggered: root.refresh()
  }

  Timer {
    id: obsProfileDelay
    interval: 1200
    repeat: false
    onTriggered: if (root.profileDrift.length > 0) root.applySavedSettings()
  }

  Timer {
    interval: 4000
    running: root.opened
    repeat: true
    onTriggered: root.refresh()
  }

  Timer {
    interval: 1000
    running: root.opened && root.connected && root.autoWhiteBalance
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refreshAutoTemperature()
  }

  Component.onCompleted: refresh()
  onOpenedChanged: root.previewActive = root.opened

  // Expose the bar slot size to Omarchy's widget loader. Without these
  // implicit dimensions the panel works over IPC, but its icon collapses to
  // zero width in the bar.
  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰄀"
    opacity: root.connected ? 1.0 : 0.5
    tooltipText: root.connected ? "Anker C200 controls" : "Anker C200 disconnected"
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) root.refresh()
      else if (buttonCode === Qt.RightButton) root.applySavedSettings()
      else if (root.opened) root.closePanel()
      else root.openPanel()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(390))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight, Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.closePanel()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      ScrollView {
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        Column {
          id: contentColumn
          width: parent.width
          spacing: Style.space(13)

          PanelHero {
            width: parent.width
            title: "Anker PowerConf C200"
            meta: root.statusText
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            iconOpacity: root.connected ? 1.0 : 0.45
            iconComponent: Component {
              Text {
                text: "󰄀"
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.display
              }
            }
          }


          RowLayout {
            width: parent.width
            spacing: Style.space(7)
            Button {
              text: root.profileApplied ? "Profile applied" : "Apply saved profile"
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              enabled: root.controllerAvailable && root.connected && !actionProc.running
              Layout.fillWidth: true
              onClicked: root.applySavedSettings()
            }
            Button {
              visible: !root.obsRunning
              text: "Start OBS"
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              enabled: root.connected
              onClicked: root.startObs()
            }
          }

          PanelSeparator { foreground: root.bar.foreground }

          Column {
            width: parent.width
            spacing: Style.space(7)

            RowLayout {
              width: parent.width
              PanelSectionHeader {
                text: "SHOT ALIGNMENT"
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                Layout.fillWidth: true
              }
              Button {
                text: "Center"
                fontSize: Style.font.caption
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                bordered: true
                enabled: root.useObsPreview && root.framingReady && !root.framingBusy
                onClicked: root.centerFraming()
              }
            }

            Rectangle {
              id: previewFrame
              width: parent.width
              height: width * 9 / 16
              radius: Style.cornerRadius
              color: Qt.rgba(0, 0, 0, 0.72)
              border.width: 1
              border.color: Qt.rgba(root.bar.foreground.r, root.bar.foreground.g, root.bar.foreground.b, 0.28)
              clip: true

              VideoOutput {
                id: previewOutput
                anchors.fill: parent
                fillMode: VideoOutput.PreserveAspectCrop
                visible: root.previewAvailable && root.previewErrorText === ""
              }

              Text {
                anchors.centerIn: parent
                visible: !root.previewAvailable || root.previewErrorText !== ""
                text: root.previewErrorText !== "" ? root.previewErrorText.toUpperCase()
                  : (root.obsRunning ? "START OBS VIRTUAL CAMERA" : "ANKER CAMERA NOT FOUND")
                color: root.bar.foreground
                opacity: 0.7
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
              }

              Rectangle {
                anchors.fill: parent
                color: "transparent"
                border.width: panArea.pressed ? 2 : 1
                border.color: panArea.pressed ? root.bar.foreground : Qt.rgba(1, 1, 1, 0.18)
                radius: parent.radius
              }

              MouseArea {
                id: panArea
                anchors.fill: parent
                enabled: root.useObsPreview
                preventStealing: true
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                property real previousX: 0
                property real previousY: 0
                onPressed: function(mouse) {
                  previousX = mouse.x
                  previousY = mouse.y
                }
                onPositionChanged: function(mouse) {
                  if (!pressed) return
                  root.queuePan(mouse.x - previousX, mouse.y - previousY, width, height)
                  previousX = mouse.x
                  previousY = mouse.y
                }
                onReleased: root.flushPan()
                onCanceled: root.flushPan()
              }
            }

            SettingSlider {
              label: "ZOOM"
              suffix: "%"
              minimum: 100
              maximum: 250
              step: 1
              currentValue: root.zoom
              controlName: "zoom_absolute"
            }

            Text {
              width: parent.width
              text: root.useDirectPreview ? "DIRECT PREVIEW · START OBS TO REFRAME" : root.framingStatus
              color: Qt.darker(root.bar.foreground, 1.35)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignHCenter
            }

            Text {
              width: parent.width
              text: root.modeDetails
              color: Qt.darker(root.bar.foreground, 1.35)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignHCenter
            }

            Text {
              visible: text !== ""
              width: parent.width
              text: root.cropDetails
              color: Qt.darker(root.bar.foreground, 1.35)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignHCenter
            }

            Text {
              visible: root.busyProcesses.length > 0 && !root.obsRunning
              width: parent.width
              text: root.busyProcesses.length > 0
                ? "PHYSICAL CAMERA HELD BY " + String(root.busyProcesses[0].name).toUpperCase()
                : ""
              color: Color.urgent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignHCenter
            }
          }

          PanelSeparator { foreground: root.bar.foreground }

          Column {
            width: parent.width
            spacing: Style.space(7)
            PanelSectionHeader { text: "FIELD OF VIEW"; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily }
            RowLayout {
              width: parent.width
              spacing: Style.space(7)
              ChoiceButton { label: "Narrow · 65°"; value: "narrow" }
              ChoiceButton { label: "Medium · 78°"; value: "medium" }
              ChoiceButton { label: "Wide · 95°"; value: "wide" }
            }
          }

          RowLayout {
            width: parent.width
            Text { text: "Auto white balance"; color: root.bar.foreground; font.family: root.bar.fontFamily; font.pixelSize: Style.font.body; Layout.fillWidth: true }
            PanelActionButton {
              visible: root.hasDriverDefault("white_balance_automatic")
              iconText: "󰑐"
              tooltipText: "Reset to the camera-reported default"
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              enabled: root.controllerAvailable && !actionProc.running
              onClicked: root.resetControl("white_balance_automatic")
            }
            ToggleSwitch {
              checked: root.autoWhiteBalance
              busy: actionProc.running
              enabled: root.controllerAvailable
              foreground: root.bar.foreground
              onToggled: root.setControl("white_balance_automatic", checked ? "off" : "on")
            }
          }

          SettingSlider {
            label: root.autoWhiteBalance ? "TEMPERATURE · AUTO" : "TEMPERATURE"
            suffix: " K"
            minimum: 2300
            maximum: 6500
            step: 100
            currentValue: root.temperature
            controlName: "white_balance_temperature"
          }

          PanelSeparator { foreground: root.bar.foreground }

          SettingSlider { label: "BRIGHTNESS"; suffix: "%"; minimum: 0; maximum: 100; step: 1; currentValue: root.brightness; controlName: "brightness" }
          SettingSlider { label: "CONTRAST"; suffix: "%"; minimum: 0; maximum: 100; step: 1; currentValue: root.contrast; controlName: "contrast" }
          SettingSlider { label: "SATURATION"; suffix: "%"; minimum: 0; maximum: 100; step: 1; currentValue: root.saturation; controlName: "saturation" }
          SettingSlider { label: "SHARPNESS"; suffix: "%"; minimum: 0; maximum: 100; step: 1; currentValue: root.sharpness; controlName: "sharpness" }

          PanelSeparator { foreground: root.bar.foreground }

          RowLayout {
            width: parent.width
            Text { text: "Continuous autofocus"; color: root.bar.foreground; font.family: root.bar.fontFamily; font.pixelSize: Style.font.body; Layout.fillWidth: true }
            PanelActionButton {
              visible: root.hasDriverDefault("focus_automatic_continuous")
              iconText: "󰑐"
              tooltipText: "Reset to the camera-reported default"
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              enabled: root.controllerAvailable && !actionProc.running
              onClicked: root.resetControl("focus_automatic_continuous")
            }
            ToggleSwitch {
              checked: root.autofocus
              busy: actionProc.running
              enabled: root.controllerAvailable
              foreground: root.bar.foreground
              onToggled: root.setControl("focus_automatic_continuous", checked ? "off" : "on")
            }
          }
        }
      }
    }
  }

  component ChoiceButton: Button {
    required property string label
    required property string value
    text: label
    fontSize: Style.font.caption
    foreground: root.bar.foreground
    fontFamily: root.bar.fontFamily
    bordered: true
    active: root.fov === value
    enabled: root.controllerAvailable
    Layout.fillWidth: true
    onClicked: root.setControl("fov", value)
  }

  // Omarchy's stock PanelSlider maps wheel movement to value changes. Camera
  // panels are long enough to scroll, so this local variant deliberately
  // rejects wheel events and lets the surrounding ScrollView consume them.
  component WheelSafeSlider: Item {
    id: wheelSliderRoot
    property QtObject bar: null
    property real value: 0
    property real minimum: 0
    property real maximum: 1
    property real step: 0.05
    property bool integer: false
    property bool dragging: false
    property real liveValue: value
    property real trackHeight: Math.max(4, Math.round(Style.spacing.controlHeight * 0.11))
    property real knobSize: Math.max(14, Math.round(Style.spacing.controlHeight * 0.38))
    readonly property real range: Math.max(0.0001, maximum - minimum)
    readonly property real progress: Math.max(0, Math.min(1, (liveValue - minimum) / range))
    readonly property bool hot: wheelSafeMouse.containsMouse || dragging

    signal moved(real value)
    signal released(real value)

    implicitWidth: Style.space(200)
    implicitHeight: Math.max(Style.space(22), knobSize + Style.spacing.md)
    onValueChanged: if (!dragging) liveValue = value

    Rectangle {
      id: wheelSafeTrack
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      height: wheelSliderRoot.trackHeight
      radius: height / 2
      color: wheelSliderRoot.bar
        ? Style.selectedFillFor(wheelSliderRoot.bar.foreground, Color.accent)
        : "#333"
    }

    Rectangle {
      anchors.left: wheelSafeTrack.left
      anchors.verticalCenter: wheelSafeTrack.verticalCenter
      width: wheelSafeTrack.width * wheelSliderRoot.progress
      height: wheelSafeTrack.height
      radius: wheelSafeTrack.radius
      color: wheelSliderRoot.bar ? wheelSliderRoot.bar.foreground : Color.foreground
      Behavior on width {
        enabled: !wheelSliderRoot.dragging
        NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
      }
    }

    BorderSurface {
      width: wheelSliderRoot.knobSize
      height: wheelSliderRoot.knobSize
      radius: wheelSliderRoot.knobSize / 2
      color: wheelSliderRoot.bar ? wheelSliderRoot.bar.foreground : Color.foreground
      borderSpec: Border.flat(
        wheelSliderRoot.bar ? wheelSliderRoot.bar.background : "#101315",
        Math.max(1, Style.space(2))
      )
      anchors.verticalCenter: wheelSafeTrack.verticalCenter
      x: Math.max(0, Math.min(
        wheelSafeTrack.width - width,
        wheelSafeTrack.width * wheelSliderRoot.progress - width / 2
      ))
      scale: wheelSliderRoot.hot ? 1.15 : 1.0
      Behavior on x {
        enabled: !wheelSliderRoot.dragging
        NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
      }
      Behavior on scale {
        NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
      }
    }

    MouseArea {
      id: wheelSafeMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      acceptedButtons: Qt.LeftButton

      function valueFromX(x) {
        const clamped = Math.max(0, Math.min(wheelSafeTrack.width, x))
        let next = wheelSliderRoot.minimum
          + (clamped / wheelSafeTrack.width) * wheelSliderRoot.range
        if (wheelSliderRoot.integer) next = Math.round(next)
        return Math.max(wheelSliderRoot.minimum, Math.min(wheelSliderRoot.maximum, next))
      }

      onPressed: function(mouse) {
        wheelSliderRoot.dragging = true
        const next = valueFromX(mouse.x)
        wheelSliderRoot.liveValue = next
        wheelSliderRoot.moved(next)
      }
      onPositionChanged: function(mouse) {
        if (!wheelSliderRoot.dragging) return
        const next = valueFromX(mouse.x)
        wheelSliderRoot.liveValue = next
        wheelSliderRoot.moved(next)
      }
      onReleased: function(mouse) {
        wheelSliderRoot.dragging = false
        wheelSliderRoot.released(wheelSliderRoot.liveValue)
        wheelSliderRoot.liveValue = wheelSliderRoot.value
      }
      onWheel: function(wheel) { wheel.accepted = false }
    }
  }

  component SettingSlider: Column {
    id: settingRoot
    required property string label
    required property string suffix
    required property real minimum
    required property real maximum
    required property real step
    required property real currentValue
    required property string controlName
    width: parent.width
    enabled: root.controllerAvailable && (controlName !== "white_balance_temperature" || !root.autoWhiteBalance)
    spacing: Style.space(4)

    RowLayout {
      width: parent.width
      PanelSectionHeader { text: settingRoot.label; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily; Layout.fillWidth: true }
      PanelActionButton {
        visible: root.hasDriverDefault(settingRoot.controlName)
        iconText: "󰑐"
        tooltipText: "Reset to camera default " + String(root.driverDefaults[settingRoot.controlName])
        foreground: root.bar.foreground
        fontFamily: root.bar.fontFamily
        enabled: root.controllerAvailable && !actionProc.running
        onClicked: root.resetControl(settingRoot.controlName)
      }
      Text {
        text: Math.round(slider.dragging ? slider.liveValue : settingRoot.currentValue) + settingRoot.suffix
        color: Qt.darker(root.bar.foreground, 1.35)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    WheelSafeSlider {
      id: slider
      width: parent.width
      bar: root.bar
      minimum: parent.minimum
      maximum: parent.maximum
      step: parent.step
      integer: true
      value: parent.currentValue
      onReleased: function(v) { root.setControl(parent.controlName, Math.round(v)) }
    }
  }
}
