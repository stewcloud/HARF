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

The **HARF** sidebar manages nodes, RF/MagicBand groups, learning, commands, On/Off devices and JSON backups. You can open and configure the panel before flashing your proxies.

HACS installs the Home Assistant integration only. Flash the ESPHome proxy firmware separately using the instructions below. HACS also manages subsequent integration updates from this repository.

**Development preview:** HACS packaging does not mean live HA setup or RF/BLE hardware operation has been validated. The project is not yet an event-ready release.

### Manual installation alternative

Copy only `custom_components/harf` into `/config/custom_components/harf`, restart HA, then add HARF through Devices & services.

### Flash each ESPHome proxy

Copy `esphome/secrets.example.yaml` to `esphome/secrets.yaml` and replace every placeholder, including a unique API key (`openssl rand -base64 32`). Keep the repository directory structure for local external components. Change node_name/friendly_name for each node. Validate and compile:

```
esphome config esphome/harf-c3.yaml
esphome compile esphome/harf-c3.yaml
```

GPIO mapping is provisional pending received-board verification: CC1101 CS=4, SCK=6, MOSI=10, MISO=7, GDO0/TX=3, GDO2/RX=1. CC1101 power is 3.3V, never 5V. No hardware tests have been performed.

Add the flashed node to HA through ESPHome. Enable **Allow the device to perform Home Assistant actions** in that ESPHome integration's configuration so capture events can reach HA. In HARF → Nodes select its native RF transmitter, enter the exact firmware node_name as receiver ID, and select its `esphome.<node>_magicband` action. Create separate RF and MagicBand groups. To use BLE, also turn on the physical node's **MagicBand Enabled** switch; it deliberately resets off at boot.

In Learn select a receiver, start listening, press the remote, use the captured signal, choose a group and save. Each command becomes a button. Optionally map distinct On/Off commands to a switch or On/Off light. Enable received-command events for automation triggers. Sniffer captures are bounded and temporary until saved.

## Behavior and limits

- Selected nodes submit commands concurrently by default. API calls are not clock- or RF-phase synchronized. Overlapping sub-GHz transmitters can interfere. The send action also accepts mode `staggered` and spacing_ms; choose spacing exceeding frame duration/repeats when nonoverlap is required.
- Commands marked repeat_sensitive require one physical transmitter and one total send. No automatic retry or failover can execute Toggle/Next twice.
- Shared-radio requests serialize; duplicate node aliases send only once. Disabled/offline/failed nodes are reported individually. Submitted is not acknowledgement from a fixture.
- RF learning/replay is initially fixed to 433.92 MHz OOK with bounded raw timings. Rolling-code/encrypted protocols are not generically replayable.
- Native stable HA RF is transmit-only; capture uses the ESPHome native API event `esphome.harf_received`. Duplicate reception and own-send echoes are filtered with bounded timing tolerance, not protocol decoding.
- Native buttons, switch/light entities and received event entities are created dynamically. Switch/light states are assumed. Light brightness/color mapping is not implemented in this first version.
- MagicBand effects broadcast for 100–60000 ms plus optional 500 ms wake. Stop cancels advertising, not necessarily a band's already-running animation. No tight synchronization or radio/venue range is guaranteed. Baseline firmware reserves BLE advertising exclusively for MagicBand; general Bluetooth proxy duties are not enabled.
- Central versioned library, validated atomic import/replace, export, admin-only panel and WS management. Receivers must be explicitly registered; unrecognized nodes cannot populate the library. Backup files include commands and node identities; keep them private when appropriate.

## Automation actions

`harf.send`: command_id; optional group_id, mode (concurrent/staggered), spacing_ms.
`harf.magicband`: group_id, effect_id, optional duration_ms.
`harf.stop_magicband`: group_id.

Actions support optional responses with per-node submission results and can be called from HA automations or Node-RED. Received command event entities expose event type `received`; bus event `harf_received` includes command_id/name/node.

## Development

Pure engine tests: `pytest -q`. Lint: `ruff check custom_components components tests`. Frontend syntax: `node --check custom_components/harf/frontend/panel.js`. The HA adapter imports were checked against HA 2026.10.4. Full HA UI/setup, live proxies, RF captures and BLE reception still require integration/hardware testing. Do not treat this development preview as an event-ready release.

## References

- ESPHome: https://esphome.io/components/cc1101/ and https://esphome.io/components/ir_rf_proxy/
- Native HA RF: https://www.home-assistant.io/integrations/radio_frequency/
- MagicBand protocol/payload reference: https://github.com/haw8411/magic-band-plus-lights/blob/main/protocols/magicband.c . Included example effect bytes are protocol data, independently implemented broadcaster code.
