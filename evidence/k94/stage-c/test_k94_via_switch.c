#include "../../research/k94/8r101_k94/k94_via_switch.c"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t executed_targets[16];
static bool executed_presses[16];
static uint8_t execute_count;

static void execute(uint8_t target, bool pressed) {
    execute_count++;
    assert(execute_count <= sizeof(executed_targets) / sizeof(executed_targets[0]));
    executed_targets[execute_count - 1] = target;
    executed_presses[execute_count - 1] = pressed;
}

static uint8_t *status_frame(void) {
    static uint8_t frame[32];
    memset(frame, 0, sizeof(frame));
    frame[0] = 0x08;
    frame[1] = 0x00;
    frame[2] = 0xB1;
    frame[3] = 0x01;
    return frame;
}

static uint8_t *switch_frame(uint8_t target, uint8_t request_id) {
    static uint8_t frame[32];
    memset(frame, 0, sizeof(frame));
    frame[0] = 0x07;
    frame[1] = 0x00;
    frame[2] = 0xB1;
    frame[3] = 0x01;
    frame[4] = target;
    frame[5] = request_id;
    return frame;
}

static void set_device(k94_via_switch_device_state *device, uint8_t mode, uint8_t channel) {
    memset(device, 0, sizeof(*device));
    device->source_mode = mode;
    device->current_ble_channel = channel;
    device->raw_status_work_mode = 0x55;
    device->raw_status_work_channel = 0x66;
    device->raw_status_connect_status = 0x77;
}

static void dispatch_mock(k94_via_switch_state *state, const k94_via_switch_device_state *device, uint8_t *data, uint32_t now) {
    if (data[0] == 0x01) {
        data[1] = 0x00;
        data[2] = 0x0C;
        return;
    }
    if (data[0] == 0x07 || data[0] == 0x08 || data[0] == 0x09) {
        k94_via_switch_handle_custom_value(state, device, data, 32, now);
    }
}

int main(void) {
    k94_via_switch_state state;
    k94_via_switch_device_state device;
    k94_via_switch_init(&state);
    set_device(&device, 0, 1);

    uint8_t *frame = status_frame();
    dispatch_mock(&state, &device, frame, 100);
    assert(frame[0] == 0x08 && frame[4] == K94_VIA_SWITCH_OK);
    assert(frame[6] == 0 && frame[7] == 1 && frame[13] == 0x55 && frame[15] == 0x77);

    frame = switch_frame(2, 0x41);
    k94_via_switch_handle_custom_value(&state, &device, frame, 32, 100);
    assert(frame[4] == K94_VIA_SWITCH_OK && frame[8] == 2 && frame[9] == 0x41);
    assert(!k94_via_switch_task(&state, &device, 199, execute) && execute_count == 0);
    assert(k94_via_switch_task(&state, &device, 200, execute) && execute_count == 2);
    assert(executed_targets[0] == 2 && executed_presses[0] && executed_targets[1] == 2 && !executed_presses[1]);

    frame = switch_frame(2, 0x41);
    k94_via_switch_handle_custom_value(&state, &device, frame, 32, 201);
    assert(frame[4] == K94_VIA_SWITCH_OK_LOCAL_COMMIT);

    frame = switch_frame(3, 0x41);
    k94_via_switch_handle_custom_value(&state, &device, frame, 32, 202);
    assert(frame[4] == K94_VIA_SWITCH_ERR_REQUEST_CONFLICT);

    frame = switch_frame(3, 0x42);
    k94_via_switch_handle_custom_value(&state, &device, frame, 32, 202);
    assert(frame[4] == K94_VIA_SWITCH_ERR_PERSISTENCE_COOLDOWN);

    frame = switch_frame(3, 0x42);
    k94_via_switch_handle_custom_value(&state, &device, frame, 32, 3800);
    assert(frame[4] == K94_VIA_SWITCH_OK && frame[8] == 3);

    frame = switch_frame(1, 0x43);
    k94_via_switch_handle_custom_value(&state, &device, frame, 32, 3801);
    assert(frame[4] == K94_VIA_SWITCH_ERR_BUSY);
    frame = switch_frame(3, 0x42);
    k94_via_switch_handle_custom_value(&state, &device, frame, 32, 3801);
    assert(frame[4] == K94_VIA_SWITCH_OK_DUPLICATE_PENDING);
    frame = switch_frame(1, 0x42);
    k94_via_switch_handle_custom_value(&state, &device, frame, 32, 3801);
    assert(frame[4] == K94_VIA_SWITCH_ERR_REQUEST_CONFLICT);
    assert(!k94_via_switch_task(&state, &device, 3899, execute) && execute_count == 2);
    assert(k94_via_switch_task(&state, &device, 3900, execute) && execute_count == 4);
    assert(executed_targets[2] == 3 && executed_presses[2] && executed_targets[3] == 3 && !executed_presses[3]);

    set_device(&device, 2, 1);
    frame = switch_frame(2, 0x80);
    k94_via_switch_handle_custom_value(&state, &device, frame, 32, 4000);
    assert(frame[4] == K94_VIA_SWITCH_ERR_SOURCE_BLOCKED && frame[8] == 0);
    assert(!k94_via_switch_task(&state, &device, 5000, execute) && execute_count == 4);

    set_device(&device, 0, 1);
    struct bad_case {
        uint8_t command;
        uint8_t channel;
        uint8_t value;
        uint8_t version;
        uint8_t target;
        uint8_t request;
        uint8_t tail;
    } const bad_cases[] = {
        {0x07, 0x00, 0xB1, 0x02, 2, 0x90, 0},
        {0x07, 0x00, 0xB1, 0x01, 0, 0x90, 0},
        {0x07, 0x00, 0xB1, 0x01, 4, 0x90, 0},
        {0x07, 0x00, 0xB1, 0x01, 2, 0, 0},
        {0x07, 0x00, 0xB1, 0x01, 2, 0x91, 1},
        {0x07, 0x01, 0xB1, 0x01, 2, 0x92, 0},
        {0x07, 0x00, 0xB2, 0x01, 2, 0x93, 0},
        {0x09, 0x00, 0xB1, 0x01, 2, 0x94, 0},
    };
    for (size_t index = 0; index < sizeof(bad_cases) / sizeof(bad_cases[0]); index++) {
        const struct bad_case *bad = &bad_cases[index];
        uint8_t bad_frame[32] = {0};
        bad_frame[0] = bad->command;
        bad_frame[1] = bad->channel;
        bad_frame[2] = bad->value;
        bad_frame[3] = bad->version;
        bad_frame[4] = bad->target;
        bad_frame[5] = bad->request;
        bad_frame[8] = bad->tail;
        k94_via_switch_handle_custom_value(&state, &device, bad_frame, 32, 4100);
        assert(bad_frame[0] == 0xFF || bad_frame[4] == K94_VIA_SWITCH_ERR_BAD_FRAME);
        assert(!state.pending);
    }

    for (uint8_t offset = 4; offset < 8; offset++) {
        uint8_t bad_frame[32] = {0};
        bad_frame[0] = 0x08;
        bad_frame[1] = 0x00;
        bad_frame[2] = 0xB1;
        bad_frame[3] = 0x01;
        bad_frame[offset] = 1;
        k94_via_switch_handle_custom_value(&state, &device, bad_frame, 32, 4110);
        assert(bad_frame[4] == K94_VIA_SWITCH_ERR_BAD_FRAME);
    }
    for (uint8_t offset = 6; offset < 8; offset++) {
        uint8_t bad_frame[32] = {0};
        bad_frame[0] = 0x07;
        bad_frame[1] = 0x00;
        bad_frame[2] = 0xB1;
        bad_frame[3] = 0x01;
        bad_frame[4] = 2;
        bad_frame[5] = 0x95;
        bad_frame[offset] = 1;
        k94_via_switch_handle_custom_value(&state, &device, bad_frame, 32, 4110);
        assert(bad_frame[4] == K94_VIA_SWITCH_ERR_BAD_FRAME);
    }

    uint8_t short_frame[31] = {0};
    short_frame[0] = 0x08;
    short_frame[1] = 0x00;
    short_frame[2] = 0xB1;
    k94_via_switch_handle_custom_value(&state, &device, short_frame, sizeof(short_frame), 4200);
    assert(short_frame[0] == 0xFF);

    uint8_t empty_frame = 0xA5;
    k94_via_switch_handle_custom_value(&state, &device, &empty_frame, 0, 4250);
    assert(empty_frame == 0xA5 && !state.pending);

    uint8_t normal_via[32] = {0};
    normal_via[0] = 0x01;
    dispatch_mock(&state, &device, normal_via, 4300);
    assert(normal_via[0] == 0x01 && normal_via[1] == 0x00 && normal_via[2] == 0x0C);

    printf("k94_via_switch host tests passed\n");
    return 0;
}
