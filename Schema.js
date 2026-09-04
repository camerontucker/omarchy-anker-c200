.pragma library

const ranges = {
  brightness: [0, 100], contrast: [0, 100], saturation: [0, 100],
  white_balance_temperature: [2300, 6500], gamma: [0, 800],
  power_line_frequency: [0, 2], sharpness: [0, 100], zoom_absolute: [100, 400]
}
const booleans = ["horizontal_flip", "white_balance_automatic", "focus_automatic_continuous"]
const controls = Object.keys(ranges).concat(booleans, ["fov"])
function object(value, maximum) {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length > maximum)
    throw new Error("Invalid object")
}
function text(value, maximum) {
  if (typeof value !== "string" || value.length > maximum || /[\x00-\x1f]/.test(value))
    throw new Error("Invalid text")
}
function boolean(value) { if (typeof value !== "boolean") throw new Error("Invalid boolean") }
function number(value, low, high, integer) {
  if (typeof value !== "number" || !isFinite(value) || value < low || value > high || (integer && Math.floor(value) !== value))
    throw new Error("Invalid number")
}
function control(name, value) {
  if (booleans.indexOf(name) >= 0) boolean(value)
  else if (name === "fov") { if (["narrow", "medium", "wide"].indexOf(value) < 0) throw new Error("Invalid FOV") }
  else if (ranges[name]) number(value, ranges[name][0], ranges[name][1], true)
  else throw new Error("Unknown control")
}
function controlMap(value) {
  object(value, controls.length)
  Object.keys(value).forEach(function(name) { control(name, value[name]) })
}
function state(data) {
  object(data, 32)
  const flags = ["connected", "controller_available", "obs_running", "readback_available", "profile_applied"]
  flags.forEach(function(name) { boolean(data[name]) })
  text(data.controller_setup_error, 256)
  text(data.controller_path, 4096)
  text(data.device, 4096)
  controls.forEach(function(name) { control(name, data[name]) })
  controlMap(data.profile)
  controlMap(data.driver_defaults)
  object(data.readback_errors, controls.length)
  Object.keys(data.readback_errors).forEach(function(name) {
    if (controls.indexOf(name) < 0) throw new Error("Unknown readback control")
    text(data.readback_errors[name], 256)
  })
  if (!Array.isArray(data.profile_drift) || data.profile_drift.length > controls.length) throw new Error("Invalid drift array")
  data.profile_drift.forEach(function(name) { if (controls.indexOf(name) < 0) throw new Error("Invalid drift control") })
  if (!Array.isArray(data.busy_processes) || data.busy_processes.length > 16) throw new Error("Invalid process array")
  data.busy_processes.forEach(function(process) {
    object(process, 2); text(process.name, 64); number(process.pid, 1, 2147483647, true)
  })
  return data
}
function obs(data) {
  object(data, 20)
  boolean(data.connected)
  if (data.sequence !== undefined) number(data.sequence, 0, 2147483647, true)
  if (!data.connected) { text(data.error, 256); return data }
  boolean(data.virtual_camera_active)
  text(data.scene, 256); text(data.source_name, 256)
  number(data.item_id, 0, 2147483647, true)
  const geometry = ["source_width", "source_height", "output_width", "output_height", "base_width", "base_height",
                    "crop_left", "crop_right", "crop_top", "crop_bottom"]
  geometry.forEach(function(name) { number(data[name], 0, 32768, true) })
  number(data.fps, 0, 1000, false)
  return data
}
function temperature(data) {
  object(data, 1)
  control("white_balance_temperature", data.white_balance_temperature)
  return data.white_balance_temperature
}
function label(value) {
  // Also safe for older host PanelHero components that use AutoText.
  return String(value).slice(0, 512).replace(/</g, "＜").replace(/>/g, "＞").replace(/&/g, "＆")
}
