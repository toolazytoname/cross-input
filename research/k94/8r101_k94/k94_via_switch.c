#include "k94_via_switch.h"

#include <string.h>

static bool time_reached(uint32_t now, uint32_t deadline) {
    return ((int32_t)(now - deadline)) >= 0;
}

static bool persistence_cooldown_active(const k94_via_switch_state *state, uint32_t now) {
    return state->has_last && state->last_committed && ((int32_t)(now - state->last_commit_time)) < K94_VIA_SWITCH_PERSISTENCE_COOLDOWN_MS;
}

static bool frame_tail_is_zero(const uint8_t *data) {
    for (uint8_t index = 8; index < K94_VIA_SWITCH_PACKET_SIZE; index++) {
        if (data[index] != 0) {
            return false;
        }
    }
    return true;
}

static bool request_frame_is_valid(const uint8_t *data, bool set_command) {
    if (data[3] != K94_VIA_SWITCH_PROTOCOL_VERSION) {
        return false;
    }
    if (data[6] != 0 || data[7] != 0) {
        return false;
    }
    if (set_command && (data[4] < 1 || data[4] > 3 || data[5] == 0)) {
        return false;
    }
    if (!set_command && (data[4] != 0 || data[5] != 0)) {
        return false;
    }
    return frame_tail_is_zero(data);
}

static void fill_response(uint8_t command_id, uint8_t result, uint8_t request_id, const k94_via_switch_state *state, const k94_via_switch_device_state *device, uint8_t *data) {
    memset(data, 0, K94_VIA_SWITCH_PACKET_SIZE);
    data[0]  = command_id;
    data[1]  = K94_VIA_SWITCH_CHANNEL;
    data[2]  = K94_VIA_SWITCH_VALUE_ID;
    data[3]  = K94_VIA_SWITCH_PROTOCOL_VERSION;
    data[4]  = result;
    data[5]  = request_id;
    data[6]  = device->source_mode;
    data[7]  = device->current_ble_channel;
    data[8]  = state->pending ? state->pending_target : 0;
    data[9]  = state->pending ? state->pending_request_id : 0;
    data[10] = state->has_last ? state->last_target : 0;
    data[11] = state->has_last ? state->last_request_id : 0;
    data[12] = state->has_last && state->last_committed ? 1 : 0;
    data[13] = device->raw_status_work_mode;
    data[14] = device->raw_status_work_channel;
    data[15] = device->raw_status_connect_status;
}

void k94_via_switch_init(k94_via_switch_state *state) {
    memset(state, 0, sizeof(*state));
}

void k94_via_switch_handle_custom_value(k94_via_switch_state *state, const k94_via_switch_device_state *device, uint8_t *data, uint8_t length, uint32_t now) {
    if (length == 0) {
        return;
    }

    const uint8_t command_id = data[0];
    const bool    set_command = command_id == 0x07;

    if (length != K94_VIA_SWITCH_PACKET_SIZE || data[1] != K94_VIA_SWITCH_CHANNEL || data[2] != K94_VIA_SWITCH_VALUE_ID || (command_id != 0x07 && command_id != 0x08)) {
        data[0] = 0xFF;
        return;
    }

    if (!request_frame_is_valid(data, set_command)) {
        fill_response(command_id, K94_VIA_SWITCH_ERR_BAD_FRAME, set_command ? data[5] : 0, state, device, data);
        return;
    }

    if (!set_command) {
        fill_response(command_id, K94_VIA_SWITCH_OK, 0, state, device, data);
        return;
    }

    const uint8_t target     = data[4];
    const uint8_t request_id = data[5];

    if (device->source_mode != 0) {
        fill_response(command_id, K94_VIA_SWITCH_ERR_SOURCE_BLOCKED, request_id, state, device, data);
        return;
    }

    if (state->pending) {
        if (state->pending_request_id == request_id) {
            const uint8_t result = state->pending_target == target ? K94_VIA_SWITCH_OK_DUPLICATE_PENDING : K94_VIA_SWITCH_ERR_REQUEST_CONFLICT;
            fill_response(command_id, result, request_id, state, device, data);
            return;
        }
        fill_response(command_id, K94_VIA_SWITCH_ERR_BUSY, request_id, state, device, data);
        return;
    }

    if (state->has_last && state->last_request_id == request_id) {
        const uint8_t result = state->last_target == target && state->last_committed ? K94_VIA_SWITCH_OK_LOCAL_COMMIT : K94_VIA_SWITCH_ERR_REQUEST_CONFLICT;
        fill_response(command_id, result, request_id, state, device, data);
        return;
    }

    if (target == device->current_ble_channel) {
        fill_response(command_id, K94_VIA_SWITCH_OK_ALREADY_CURRENT, request_id, state, device, data);
        return;
    }

    if (persistence_cooldown_active(state, now)) {
        fill_response(command_id, K94_VIA_SWITCH_ERR_PERSISTENCE_COOLDOWN, request_id, state, device, data);
        return;
    }

    state->pending            = true;
    state->pending_target     = target;
    state->pending_request_id = request_id;
    state->pending_deadline   = now + K94_VIA_SWITCH_DELAY_MS;
    fill_response(command_id, K94_VIA_SWITCH_OK, request_id, state, device, data);
}

bool k94_via_switch_task(k94_via_switch_state *state, const k94_via_switch_device_state *device, uint32_t now, k94_via_switch_execute execute) {
    if (!state->pending || !time_reached(now, state->pending_deadline)) {
        return false;
    }

    const uint8_t target     = state->pending_target;
    const uint8_t request_id = state->pending_request_id;
    state->pending = false;

    if (device->source_mode != 0) {
        state->has_last       = true;
        state->last_committed = false;
        state->last_target    = 0;
        state->last_request_id = request_id;
        return false;
    }

    execute(target, true);
    execute(target, false);
    state->has_last           = true;
    state->last_committed     = true;
    state->last_target        = target;
    state->last_request_id    = request_id;
    state->last_commit_time   = now;
    return true;
}
