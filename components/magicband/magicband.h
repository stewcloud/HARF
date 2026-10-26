#pragma once
#include "esphome/core/component.h"
#include "esphome/core/log.h"
#include "esphome/components/api/custom_api_device.h"
#include "esphome/components/esp32_ble/ble.h"
#include <esp_gap_ble_api.h>
#include <string>
#include <vector>

namespace esphome::magicband {
class MagicBand : public Component, public api::CustomAPIDevice {
 public:
  void set_ble(esp32_ble::ESP32BLE *ble) { ble_ = ble; }
  void set_enabled(bool enabled) { enabled_ = enabled; if (!enabled) active_ = false; }
  bool is_broadcasting() const { return advertising_; }
  void setup() override {
    register_service(&MagicBand::request, "magicband", {"payload", "duration_ms", "wake", "stop"});
  }
  void on_shutdown() override { active_ = false; esp_ble_gap_stop_advertising(); }
  void request(std::string payload, int32_t duration_ms, bool wake, bool stop) {
    if (stop) { active_ = false; return; }
    if (!enabled_ || duration_ms < 100 || duration_ms > 60000 || payload.empty() || payload.size() > 48 || payload.size()%2) {
      ESP_LOGW("magicband", "Request rejected: disabled, invalid duration or payload"); return;
    }
    std::vector<uint8_t> decoded;
    for (size_t i=0; i<payload.size(); i+=2) {
      int hi=hex_(payload[i]), lo=hex_(payload[i+1]);
      if (hi<0 || lo<0) { ESP_LOGW("magicband", "Invalid hex payload"); return; }
      decoded.push_back((hi<<4)|lo);
    }
    effect_ = std::move(decoded);
    const auto now = millis();
    wake_until_ = now + (wake ? 500 : 0);
    deadline_ = now + duration_ms + (wake ? 500 : 0);
    generation_++;
    active_ = true;
  }
  void loop() override {
    if (ble_ == nullptr || !ble_->is_active()) return;
    const auto now = millis();
    if (active_ && static_cast<int32_t>(now-deadline_) >= 0) active_ = false;
    if (busy_) {
      if (now - busy_since_ > 3000) {
        active_ = false; busy_ = false; ready_ = false;
        esp_ble_gap_stop_advertising();
        ESP_LOGE("magicband", "BLE operation timed out; broadcasting cancelled");
      }
      return;
    }
    const bool phase = active_ && static_cast<int32_t>(wake_until_-now)>0;
    const bool changed = configured_generation_ != generation_ || phase != configured_wake_;
    if (advertising_) {
      if (!active_ || changed) {
        if (esp_ble_gap_stop_advertising() == ESP_OK) { busy_ = true; busy_since_ = now; }
        else { active_ = false; ESP_LOGW("magicband", "BLE stop request failed"); }
      }
      return;
    }
    if (!active_) { ready_ = false; return; }
    if (!ready_ || changed) {
      static const std::vector<uint8_t> wake{0xE1,0x00,0xCC,0x03,0x00,0x01,0x00};
      const auto &body = phase ? wake : effect_;
      packet_ = {0x02,0x01,0x06,static_cast<uint8_t>(body.size()+3),0xFF,0x83,0x01};
      packet_.insert(packet_.end(),body.begin(),body.end());
      configured_generation_ = generation_; configured_wake_ = phase; ready_ = false;
      if (esp_ble_gap_config_adv_data_raw(packet_.data(),packet_.size()) == ESP_OK) {
        busy_ = true; busy_since_ = now;
      } else { active_ = false; ESP_LOGW("magicband", "BLE data configuration failed"); }
      return;
    }
    esp_ble_adv_params_t params{};
    params.adv_int_min = 0xA0; params.adv_int_max = 0xF0;
    params.adv_type = ADV_TYPE_NONCONN_IND; params.own_addr_type = BLE_ADDR_TYPE_PUBLIC;
    params.channel_map = ADV_CHNL_ALL; params.adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY;
    if (esp_ble_gap_start_advertising(&params) == ESP_OK) { busy_ = true; busy_since_ = now; }
    else { active_ = false; ESP_LOGW("magicband", "BLE advertising start failed"); }
  }
  void gap_event_handler(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param) {
    if (event == ESP_GAP_BLE_ADV_DATA_RAW_SET_COMPLETE_EVT) {
      ready_ = param->adv_data_raw_cmpl.status == ESP_BT_STATUS_SUCCESS;
      busy_ = false; if (!ready_) active_ = false;
    } else if (event == ESP_GAP_BLE_ADV_START_COMPLETE_EVT) {
      advertising_ = param->adv_start_cmpl.status == ESP_BT_STATUS_SUCCESS;
      busy_ = false; if (!advertising_) active_ = false;
    } else if (event == ESP_GAP_BLE_ADV_STOP_COMPLETE_EVT) {
      busy_ = false;
      if (param->adv_stop_cmpl.status == ESP_BT_STATUS_SUCCESS) advertising_ = false;
      else { active_ = false; ESP_LOGW("magicband", "BLE controller could not stop advertising"); }
    }
  }
 protected:
  static int hex_(char c) {
    if (c>='0' && c<='9') return c-'0';
    if (c>='A' && c<='F') return c-'A'+10;
    if (c>='a' && c<='f') return c-'a'+10;
    return -1;
  }
  esp32_ble::ESP32BLE *ble_{};
  std::vector<uint8_t> effect_, packet_;
  uint32_t generation_{1}, configured_generation_{0}, deadline_{0}, wake_until_{0}, busy_since_{0};
  bool enabled_{false}, active_{false}, busy_{false}, ready_{false}, advertising_{false}, configured_wake_{false};
};
}
