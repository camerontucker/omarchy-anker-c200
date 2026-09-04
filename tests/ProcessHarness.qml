import QtQuick
import Quickshell
import "../" as Plugin

ShellRoot {
  id: harness
  property int stage: 0
  Plugin.BoundedProcess {
    id: process
    command: ["/usr/bin/python3", "-I", "-S", "-c", "print('bounded-ok')"]
    running: true
    onCompleted: function(output, error, code) {
      if (harness.stage === 0) {
        if (code !== 0 || output !== "bounded-ok\n") { console.log("HARNESS_FAIL normal"); Qt.quit(); return }
        harness.stage = 1
        command = ["/usr/bin/python3", "-I", "-S", "-c", "import os,time;os.write(1,b'x'*20000);time.sleep(.1)"]
        Qt.callLater(function() { process.running = true })
      } else {
        if (code === 0 || output.length > 16384) console.log("HARNESS_FAIL flood")
        else console.log("HARNESS_PASS")
        Qt.quit()
      }
    }
  }
  Timer {
    interval: 5000
    running: true
    onTriggered: { console.log("HARNESS_FAIL timeout"); Qt.quit() }
  }
}
