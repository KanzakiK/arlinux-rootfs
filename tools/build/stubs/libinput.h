#ifndef ARLINUX_STUB_LIBINPUT_H
#define ARLINUX_STUB_LIBINPUT_H

#include <stdint.h>

struct libinput_device;
struct libinput_device_group;
struct libinput_tablet_tool;

enum libinput_config_status { LIBINPUT_CONFIG_STATUS_SUCCESS = 0 };
enum libinput_config_accel_profile {
	LIBINPUT_CONFIG_ACCEL_PROFILE_NONE = 0,
	LIBINPUT_CONFIG_ACCEL_PROFILE_FLAT = 1,
	LIBINPUT_CONFIG_ACCEL_PROFILE_ADAPTIVE = 2
};
enum libinput_config_scroll_method {
	LIBINPUT_CONFIG_SCROLL_NO_SCROLL = 0,
	LIBINPUT_CONFIG_SCROLL_2FG = 1,
	LIBINPUT_CONFIG_SCROLL_EDGE = 2,
	LIBINPUT_CONFIG_SCROLL_ON_BUTTON_DOWN = 4
};
enum libinput_config_tap_state { LIBINPUT_CONFIG_TAP_DISABLED = 0, LIBINPUT_CONFIG_TAP_ENABLED = 1 };
enum libinput_config_tap_button_map {
	LIBINPUT_CONFIG_TAP_MAP_LRM = 0,
	LIBINPUT_CONFIG_TAP_MAP_LMR = 1
};
enum libinput_config_drag_state { LIBINPUT_CONFIG_DRAG_DISABLED = 0, LIBINPUT_CONFIG_DRAG_ENABLED = 1 };
enum libinput_config_drag_lock_state {
	LIBINPUT_CONFIG_DRAG_LOCK_DISABLED = 0,
	LIBINPUT_CONFIG_DRAG_LOCK_ENABLED = 1,
	LIBINPUT_CONFIG_DRAG_LOCK_ENABLED_STICKY = 2
};
enum libinput_config_dwt_state { LIBINPUT_CONFIG_DWT_DISABLED = 0, LIBINPUT_CONFIG_DWT_ENABLED = 1 };
enum libinput_config_middle_emulation_state {
	LIBINPUT_CONFIG_MIDDLE_EMULATION_DISABLED = 0,
	LIBINPUT_CONFIG_MIDDLE_EMULATION_ENABLED = 1
};
enum libinput_config_click_method {
	LIBINPUT_CONFIG_CLICK_METHOD_NONE = 0,
	LIBINPUT_CONFIG_CLICK_METHOD_BUTTON_AREAS = 1,
	LIBINPUT_CONFIG_CLICK_METHOD_CLICKFINGER = 2
};
enum libinput_config_send_events_mode {
	LIBINPUT_CONFIG_SEND_EVENTS_ENABLED = 0,
	LIBINPUT_CONFIG_SEND_EVENTS_DISABLED = 1,
	LIBINPUT_CONFIG_SEND_EVENTS_DISABLED_ON_EXTERNAL_MOUSE = 2
};
enum libinput_config_3fg_drag_state {
	LIBINPUT_CONFIG_3FG_DRAG_DISABLED = 0,
	LIBINPUT_CONFIG_3FG_DRAG_ENABLED_3FG = 1,
	LIBINPUT_CONFIG_3FG_DRAG_ENABLED_4FG = 2,
	LIBINPUT_CONFIG_3FG_DRAG_ENABLED = 2
};

const char *libinput_device_get_name(struct libinput_device *d);
const char *libinput_device_get_sysname(struct libinput_device *d);
struct libinput_device_group *libinput_device_get_device_group(struct libinput_device *d);

uint32_t libinput_device_config_accel_get_profiles(struct libinput_device *d);
enum libinput_config_status libinput_device_config_accel_set_profile(struct libinput_device *d, enum libinput_config_accel_profile p);
enum libinput_config_status libinput_device_config_accel_set_speed(struct libinput_device *d, double s);
int libinput_device_config_accel_is_available(struct libinput_device *d);
double libinput_device_config_accel_get_default_speed(struct libinput_device *d);
enum libinput_config_accel_profile libinput_device_config_accel_get_default_profile(struct libinput_device *d);

int libinput_device_config_scroll_has_natural_scroll(struct libinput_device *d);
enum libinput_config_status libinput_device_config_scroll_set_natural_scroll_enabled(struct libinput_device *d, int e);
int libinput_device_config_scroll_get_natural_scroll_enabled(struct libinput_device *d);
int libinput_device_config_scroll_get_default_natural_scroll_enabled(struct libinput_device *d);
uint32_t libinput_device_config_scroll_get_methods(struct libinput_device *d);
enum libinput_config_status libinput_device_config_scroll_set_method(struct libinput_device *d, enum libinput_config_scroll_method m);
enum libinput_config_scroll_method libinput_device_config_scroll_get_default_method(struct libinput_device *d);
enum libinput_config_status libinput_device_config_scroll_set_button(struct libinput_device *d, uint32_t b);
uint32_t libinput_device_config_scroll_get_default_button(struct libinput_device *d);

int libinput_device_config_tap_get_finger_count(struct libinput_device *d);
enum libinput_config_status libinput_device_config_tap_set_enabled(struct libinput_device *d, enum libinput_config_tap_state s);
enum libinput_config_tap_state libinput_device_config_tap_get_default_enabled(struct libinput_device *d);
enum libinput_config_status libinput_device_config_tap_set_button_map(struct libinput_device *d, enum libinput_config_tap_button_map m);
enum libinput_config_tap_button_map libinput_device_config_tap_get_default_button_map(struct libinput_device *d);
enum libinput_config_status libinput_device_config_tap_set_drag_enabled(struct libinput_device *d, enum libinput_config_drag_state s);
enum libinput_config_drag_state libinput_device_config_tap_get_default_drag_enabled(struct libinput_device *d);
enum libinput_config_status libinput_device_config_tap_set_drag_lock_enabled(struct libinput_device *d, enum libinput_config_drag_lock_state s);
enum libinput_config_drag_lock_state libinput_device_config_tap_get_default_drag_lock_enabled(struct libinput_device *d);

enum libinput_config_status libinput_device_config_3fg_drag_set_enabled(struct libinput_device *d, enum libinput_config_3fg_drag_state s);
enum libinput_config_3fg_drag_state libinput_device_config_3fg_drag_get_default_enabled(struct libinput_device *d);

int libinput_device_config_dwt_is_available(struct libinput_device *d);
enum libinput_config_status libinput_device_config_dwt_set_enabled(struct libinput_device *d, enum libinput_config_dwt_state s);
enum libinput_config_dwt_state libinput_device_config_dwt_get_default_enabled(struct libinput_device *d);

int libinput_device_config_middle_emulation_is_available(struct libinput_device *d);
enum libinput_config_status libinput_device_config_middle_emulation_set_enabled(struct libinput_device *d, enum libinput_config_middle_emulation_state s);
enum libinput_config_middle_emulation_state libinput_device_config_middle_emulation_get_default_enabled(struct libinput_device *d);

int libinput_device_config_left_handed_is_available(struct libinput_device *d);
enum libinput_config_status libinput_device_config_left_handed_set(struct libinput_device *d, int v);
int libinput_device_config_left_handed_get_default(struct libinput_device *d);

int libinput_device_config_rotation_is_available(struct libinput_device *d);
enum libinput_config_status libinput_device_config_rotation_set_angle(struct libinput_device *d, unsigned int a);

enum libinput_config_status libinput_device_config_click_set_method(struct libinput_device *d, enum libinput_config_click_method m);
enum libinput_config_click_method libinput_device_config_click_get_default_method(struct libinput_device *d);
uint32_t libinput_device_config_click_get_methods(struct libinput_device *d);

enum libinput_config_status libinput_device_config_send_events_set_mode(struct libinput_device *d, enum libinput_config_send_events_mode m);
enum libinput_config_send_events_mode libinput_device_config_send_events_get_default_mode(struct libinput_device *d);
uint32_t libinput_device_config_send_events_get_modes(struct libinput_device *d);

int libinput_device_config_calibration_has_matrix(struct libinput_device *d);
int libinput_device_config_calibration_get_default_matrix(struct libinput_device *d, float matrix[6]);
enum libinput_config_status libinput_device_config_calibration_set_matrix(struct libinput_device *d, const float matrix[6]);

int libinput_tablet_tool_config_pressure_range_is_available(struct libinput_tablet_tool *t);
double libinput_tablet_tool_config_pressure_range_get_minimum(struct libinput_tablet_tool *t);
double libinput_tablet_tool_config_pressure_range_get_maximum(struct libinput_tablet_tool *t);
enum libinput_config_status libinput_tablet_tool_config_pressure_range_set(struct libinput_tablet_tool *t, double min, double max);

#endif
