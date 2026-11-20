#pragma once

#include <stdbool.h>
#include <stdint.h>

#define K94_VIA_SWITCH_PACKET_SIZE 32
#define K94_VIA_SWITCH_PROTOCOL_VERSION 0x01
#define K94_VIA_SWITCH_CHANNEL 0x00
#define K94_VIA_SWITCH_VALUE_ID 0xB1
#define K94_VIA_SWITCH_DELAY_MS 100
#define K94_VIA_SWITCH_PERSISTENCE_COOLDOWN_MS 3500

enum k94_via_switch_result {
    K94_VIA_SWITCH_OK = 0x00,
    K94_VIA_SWITCH_OK_DUPLICATE_PENDING = 0x01,
    K94_VIA_SWITCH_OK_ALREADY_CURRENT = 0x02,
    K94_VIA_SWITCH_OK_LOCAL_COMMIT = 0x03,
    K94_VIA_SWITCH_ERR_BAD_FRAME = 0x10,
    K94_VIA_SWITCH_ERR_BUSY = 0x11,
    K94_VIA_SWITCH_ERR_REQUEST_CONFLICT = 0x12,
    K94_VIA_SWITCH_ERR_SOURCE_BLOCKED = 0x13,
    K94_VIA_SWITCH_ERR_PERSISTENCE_COOLDOWN = 0x14,
};

typedef struct {
    uint8_t source_mode;
    uint8_t current_ble_channel;
    uint8_t raw_status_work_mode;
    uint8_t raw_status_work_channel;
    uint8_t raw_status_connect_status;
} k94_via_switch_device_state;

typedef struct {
    bool     pending;
    uint8_t  pending_target;
    uint8_t  pending_request_id;
    uint32_t pending_deadline;
    bool     has_last;
    bool     last_committed;
    uint8_t  last_target;
    uint8_t  last_request_id;
    uint32_t last_commit_time;
} k94_via_switch_state;

typedef void (*k94_via_switch_execute)(uint8_t target, bool pressed);

void k94_via_switch_init(k94_via_switch_state *state);
void k94_via_switch_handle_custom_value(k94_via_switch_state *state, const k94_via_switch_device_state *device, uint8_t *data, uint8_t length, uint32_t now);
bool k94_via_switch_task(k94_via_switch_state *state, const k94_via_switch_device_state *device, uint32_t now, k94_via_switch_execute execute);
