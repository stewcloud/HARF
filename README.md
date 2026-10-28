<p align="center"><img src="custom_components/harf/frontend/icon.png" alt="HARF radio antenna icon" width="160"></p>

# HARF — 0.1 development preview

Local Home Assistant RF command manager, ESPHome CC1101 proxy and independently enabled MagicBand+ broadcaster. No MQTT required. This is an original integration inspired by the HAIR workflow, not a HAIR fork.

## Install

Requires Home Assistant **2026.10.4+**. The proxy firmware requires ESPHome **2026.10.0+**.

### Install from GitHub using HACS

1. Open **HACS** in Home Assistant.
2. Open the **⋮** menu and select **Custom repositories**.
3. Enter `https://github.com/stewcloud/HARF` and choose **Integration** as the category/type, then add it.
4. Find **HARF**, open it and choose **Download**. Use the default `main` branch if a version is requested; no release ZIP is needed.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration**, search **HARF**, and add it.

The **HARF** sidebar manages nodes, RF/MagicBand groups, learning, commands, device mappings and JSON backups. You can open and configure the panel before flashing your proxies.

HACS installs the Home Assistant integration only. Flash the ESPHome proxy firmware separately using the instructions below. HACS also manages subsequent integration updates from this repository.

**Development preview:** HACS packaging does not mean live HA setup or RF/BLE hardware operation has been validated. The project is not yet an event-ready release.

### Manual installation alternative

Copy only `custom_components/harf` into `/config/custom_components/harf`, restart HA, then add HARF through Devices & services.

### Flash each ESPHome proxy

Copy `esphome/secrets.example.yaml` to `esphome/secrets.yaml` and replace every placeholder, including a unique API key (`openssl rand -base64 32`). The YAML fetches the MagicBand component directly from GitHub; no local components folder is needed. Change node_name/friendly_name for each node. Validate and compile:

```
esphome config esphome/harf-c3.yaml
esphome compile esphome/harf-c3.yaml
```

GPIO mapping is provisional pending received-board verification: CC1101 CS=4, SCK=6, MOSI=10, MISO=7, GDO0/TX=3, GDO2/RX=1. CC1101 power is 3.3V, never 5V. No hardware tests have been performed.

Add the flashed node to HA through ESPHome. Enable **Allow the device to perform Home Assistant actions** in that ESPHome integration's configuration so capture events can reach HA. In HARF → Nodes select its native RF transmitter, enter the exact firmware node_name as receiver ID, and select its `esphome.<node>_magicband` action. Create separate RF and MagicBand groups. To use BLE, also turn on the physical node's **MagicBand Enabled** switch; it deliberately resets off at boot.

In Learn select a receiver, start listening, press the remote, use the captured signal, choose a group and save. Commands stay in HARF’s library; they do not automatically become HA entities or devices. Updating removes the old automatic command buttons, received-event entities and empty command device entries without deleting learned RF data. Only devices created under Devices appear as HARF devices in HA, with any explicitly assigned extra buttons grouped under them. Optionally map distinct On/Off commands to a switch or light. Under Devices, edit a light and select saved commands under **Light effect commands** (for example Smooth, Flash and Fade). They appear in the light entity’s effect selector and work with `light.turn_on` using `effect: Smooth`. Select any saved commands under **Additional command buttons** to create buttons grouped with that HA device. Hold Ctrl/Cmd to select multiple items. Saving an existing Stable ID updates it; unselected mappings are removed. Remove mappings before deleting a referenced command. Enable received-command events to emit `harf_received` bus events for automation triggers; no per-command event entities are created. Sniffer captures are bounded and temporary until saved.

### Captured colors

1. Learn a color button and use its capture, or edit a saved command in Learn.
2. Check **Assign this captured command to a color**, choose the swatch that represents the actual light output, and save. RF pulses do not identify a color by themselves; the swatch is your assignment.
3. In Devices, edit the light and select its commands under **Captured color commands**. Hold Ctrl/Cmd for multiple selections, then save.
4. Use the light's normal HA color picker or `light.turn_on` with `rgb_color`. HA converts other requested color formats to the light's RGB mode. HARF uses CIELAB Delta E 76 to choose the nearest assigned swatch and sends only that RF command through its saved group. The entity reports the selected swatch, rather than claiming an unavailable exact color.

Only a mapped light advertises color control. Existing On/Off lights remain On/Off. Mapping changes take effect on save. Distinct swatches are required within one light; remove a light's mapping before deleting or clearing a referenced command's color. Colors/effects are assumed, not confirmed by the fixture. Brightness has no RF mapping yet: HA's RGB color mode can show a brightness control, but requests below full brightness are rejected rather than pretending to dim the light.

## Behavior and limits

- Selected nodes submit commands concurrently by default. API calls are not clock- or RF-phase synchronized. Overlapping sub-GHz transmitters can interfere. The send action also accepts mode `staggered` and spacing_ms; choose spacing exceeding frame duration/repeats when nonoverlap is required.
- Commands marked repeat_sensitive require one physical transmitter and one total send. No automatic retry or failover can execute Toggle/Next twice.
- Shared-radio requests serialize; duplicate node aliases send only once. Disabled/offline/failed nodes are reported individually. Submitted is not acknowledgement from a fixture.
- RF learning/replay is initially fixed to 433.92 MHz OOK with bounded raw timings. Rolling-code/encrypted protocols are not generically replayable.
- Native stable HA RF is transmit-only; capture uses the ESPHome native API event `esphome.harf_received`. Duplicate reception and own-send echoes are filtered with bounded timing tolerance, not protocol decoding.
- Created switch/light entities and their explicitly mapped action buttons are added dynamically. Switch/light states are assumed. Lights support explicitly mapped effects and captured color swatches; brightness mapping is not implemented. Effects send only their selected command and use the saved command’s RF group. Extra command buttons do not infer or update the light/switch state. Existing library backups remain compatible; exports include the new mappings.
- MagicBand effects broadcast for 100–60000 ms plus optional 500 ms wake. Stop cancels advertising, not necessarily a band's already-running animation. No tight synchronization or radio/venue range is guaranteed. Baseline firmware reserves BLE advertising exclusively for MagicBand; general Bluetooth proxy duties are not enabled.
- Central versioned library, validated atomic import/replace, export, admin-only panel and WS management. Receivers must be explicitly registered; unrecognized nodes cannot populate the library. Backup files include commands and node identities; keep them private when appropriate.

## Automation actions

`harf.send`: command_id; optional group_id, mode (concurrent/staggered), spacing_ms.
`harf.magicband`: group_id, effect_id, optional duration_ms.
`harf.stop_magicband`: group_id.

Actions support optional responses with per-node submission results and can be called from HA automations or Node-RED. The bus event `harf_received` includes command_id/name/node and remains available for automations. Learned commands can still be sent with `harf.send` or from the HARF panel.

## Development

Pure engine tests: `pytest -q`. Lint: `ruff check custom_components components tests`. Frontend syntax: `node --check custom_components/harf/frontend/panel.js`. The HA adapter imports were checked against HA 2026.10.4. Full HA UI/setup, live proxies, RF captures and BLE reception still require integration/hardware testing. Do not treat this development preview as an event-ready release.

## References

- ESPHome: https://esphome.io/components/cc1101/ and https://esphome.io/components/ir_rf_proxy/
- Native HA RF: https://www.home-assistant.io/integrations/radio_frequency/
- MagicBand protocol/payload reference: https://github.com/haw8411/magic-band-plus-lights/blob/main/protocols/magicband.c . Included example effect bytes are protocol data, independently implemented broadcaster code.

