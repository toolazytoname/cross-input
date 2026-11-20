/* Copyright 2023 Finalkey
 * Copyright 2023 LiWenLiu <https://github.com/LiuLiuQMK>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include "../../lib/rdr_lib/rdr_common.h"

#include "k94_via_switch.h"

static k94_via_switch_state via_switch_state;

static void k94_via_switch_execute_request(uint8_t target, bool pressed);

void matrix_io_delay(void) {
}

void matrix_output_select_delay(void) {
}

void matrix_output_unselect_delay(uint8_t line, bool key_pressed) {
}

led_config_t g_led_config = { {
    { 0        , 1        , 2        , 3        , 4        , 5        , 6        , 7        , 8        , 9        , 10       , 11       , 12       , 13       , NO_LED   , NO_LED   },
	{ 14       , 15       , 16       , 17       , 18       , 19       , 20       , 21       , 22       , 23       , 24       , 25       , 26       , 27       , NO_LED   , NO_LED   },
	{ 32       , 33       , 34       , 35       , 36       , 37       , 38       , 39       , 40       , 41       , 42       , 43       , 44       , 45       , NO_LED   , NO_LED   },
	{ 49       , 50       , 51       , 52       , 53       , 54       , 55       , 56       , 57       , 58       , 59       , 60       , NO_LED   , 61       , NO_LED   , NO_LED   },
	{ 66       , NO_LED   , 67       , 68       , 69       , 70       , 71       , 72       , 73       , 74       , 75       , 76       , NO_LED   , 77       , 78       , 79       },
	{ 82       , 83       , 84       , NO_LED   , NO_LED   , 85       , NO_LED   , NO_LED   , NO_LED   , 86       , NO_LED   , 87       , NO_LED   , 88       , 89       , 90       },
    { 28       , 29       , 30       , 31       , 46       , 47       , 48       , 62       , 63       , 64       , 65       , 80       , 81       , 91       , 92       , 93       }
},{
    { 0,  10 }, { 15, 10 }, { 27, 10 }, { 39, 10 }, { 51, 10 }, { 66, 10 }, { 78, 10 }, { 90, 10 }, { 102, 10 }, { 117, 10 }, { 129, 10 }, { 141, 10 }, { 153, 10 }, { 168, 10 },
    { 0,  20 }, { 12, 20 }, { 24, 20 }, { 36, 20 }, { 48, 20 }, { 60, 20 }, { 72, 20 }, { 84, 20 }, { 96,  20 }, { 108, 20 }, { 120, 20 }, { 132, 20 }, { 144, 20 }, { 162, 20 }, { 188, 20 }, { 200, 20 }, { 212, 20 }, { 224, 20 },
    { 3,  30 }, { 18, 30 }, { 30, 30 }, { 42, 30 }, { 54, 30 }, { 66, 30 }, { 78, 30 }, { 90, 30 }, { 102, 30 }, { 114, 30 }, { 126, 30 }, { 138, 30 }, { 150, 30 }, { 165, 30 }, { 188, 30 }, { 200, 30 }, { 212, 30 },
    { 4,  40 }, { 20, 40 }, { 32, 40 }, { 44, 40 }, { 56, 40 }, { 68, 40 }, { 80, 40 }, { 92, 40 }, { 104, 40 }, { 116, 40 }, { 128, 40 }, { 140, 40 },              { 161, 40 }, { 188, 40 }, { 200, 40 }, { 212, 40 }, { 224, 35 },
    { 6,  50 },             { 26, 50 }, { 38, 50 }, { 50, 50 }, { 62, 50 }, { 74, 50 }, { 86, 50 }, { 98,  50 }, { 110, 50 }, { 122, 50 }, { 134, 50 }, { 152, 50 }, { 173, 50 }, { 188, 50 }, { 200, 50 }, { 212, 50 },
    { 0,  60 }, { 15, 60 }, { 30, 60 },                         { 76, 60 },                                      { 120, 60 }, { 135, 60 },              { 161, 60 }, { 173, 60 }, { 180, 60 }, { 200, 60 }, { 212, 60 }, { 224, 55 }
}, {
    1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,
    1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,
    1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,
    1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,      1,  1,  1,  1,  1,
    1,      1,  1,  1,  1,  1,  1,  1,  1,  1,  1,      1,  1,  1,  1,  1,
    1,  1,  1,          1,              1,  1,          1,  1,  1,  1,  1,  1
} };

bool rgb_matrix_indicators_advanced_user(uint8_t led_min, uint8_t led_max) {
    User_Led_Show();
    return false;
}

void notify_usb_device_state_change_user(enum usb_device_state usb_device_state)  {
    if (Keyboard_Info.Key_Mode == QMK_USB_MODE) {
        if(usb_device_state == USB_DEVICE_STATE_CONFIGURED) {
            Usb_If_Ok = true;
            Usb_If_Ok_Led = true;
            Usb_If_Ok_Delay = 0;
        } else {
            Usb_If_Ok = false;
		    Usb_If_Ok_Led = false;
        }
    } else {
        Usb_If_Ok = false;
	    Usb_If_Ok_Led = false;
    }
}

void housekeeping_task_user(void) {
    es_chibios_user_idle_loop_hook();
    User_Keyboard_Reset();
    k94_via_switch_device_state device_state = {
        .source_mode               = Keyboard_Info.Key_Mode,
        .current_ble_channel       = Keyboard_Info.Ble_Channel,
        .raw_status_work_mode      = Keyboard_Status.System_Work_Mode,
        .raw_status_work_channel   = Keyboard_Status.System_Work_Channel,
        .raw_status_connect_status = Keyboard_Status.System_Connect_Status,
    };
    k94_via_switch_task(&via_switch_state, &device_state, timer_read32(), k94_via_switch_execute_request);
}

void board_init(void) {
    k94_via_switch_init(&via_switch_state);
    User_Keyboard_Init();
}

void keyboard_post_init_user(void) {
    User_Keyboard_Post_Init();
}

bool process_record_user(uint16_t keycode, keyrecord_t *record) {
    Usb_Change_Mode_Delay = 0;
    Usb_Change_Mode_Wakeup = false;

    if (User_Power_Shut && (record->event.pressed)) {
        User_Power_Shut_Flag = false;
        return false;
    }

    Uart_Key_Mode_Key_Scan(keycode, record->event.pressed);

    if (Test_Led) {
        if ((keycode != KC_SPC) && (keycode != MO(2)) && (keycode != MO(3)) && (keycode != KC_LCTL)) {
            Test_Led = false;
        }
    }

    return User_process_record_user(keycode, record);
}

static void k94_via_switch_execute_request(uint8_t target, bool pressed) {
    keyrecord_t record = {0};
    record.event.pressed = pressed;
    uint16_t keycode = MD_BLE3;
    if (target == 1) {
        keycode = MD_BLE1;
    } else if (target == 2) {
        keycode = MD_BLE2;
    }
    (void)process_record_user(keycode, &record);
}

void via_custom_value_command_kb(uint8_t *data, uint8_t length) {
    k94_via_switch_device_state device_state = {
        .source_mode               = Keyboard_Info.Key_Mode,
        .current_ble_channel       = Keyboard_Info.Ble_Channel,
        .raw_status_work_mode      = Keyboard_Status.System_Work_Mode,
        .raw_status_work_channel   = Keyboard_Status.System_Work_Channel,
        .raw_status_connect_status = Keyboard_Status.System_Connect_Status,
    };
    k94_via_switch_handle_custom_value(&via_switch_state, &device_state, data, length, timer_read32());
}
