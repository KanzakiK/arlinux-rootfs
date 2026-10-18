#include "libinput.h"

const char *libinput_device_get_name(struct libinput_device *d) { (void)d; return "stub"; }
const char *libinput_device_get_sysname(struct libinput_device *d) { (void)d; return "stub"; }
struct libinput_device_group *libinput_device_get_device_group(struct libinput_device *d) { (void)d; return NULL; }

uint32_t libinput_device_config_accel_get_profiles(struct libinput_device *d) { (void)d; return 0; }
enum libinput_config_status libinput_device_config_accel_set_profile(struct libinput_device *d, enum libinput_config_accel_profile p) { (void)d; (void)p; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_status libinput_device_config_accel_set_speed(struct libinput_device *d, double s) { (void)d; (void)s; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
int libinput_device_config_accel_is_available(struct libinput_device *d) { (void)d; return 0; }
double libinput_device_config_accel_get_default_speed(struct libinput_device *d) { (void)d; return 0; }
enum libinput_config_accel_profile libinput_device_config_accel_get_default_profile(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_ACCEL_PROFILE_NONE; }

int libinput_device_config_scroll_has_natural_scroll(struct libinput_device *d) { (void)d; return 0; }
enum libinput_config_status libinput_device_config_scroll_set_natural_scroll_enabled(struct libinput_device *d, int e) { (void)d; (void)e; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
int libinput_device_config_scroll_get_natural_scroll_enabled(struct libinput_device *d) { (void)d; return 0; }
int libinput_device_config_scroll_get_default_natural_scroll_enabled(struct libinput_device *d) { (void)d; return 0; }
uint32_t libinput_device_config_scroll_get_methods(struct libinput_device *d) { (void)d; return 0; }
enum libinput_config_status libinput_device_config_scroll_set_method(struct libinput_device *d, enum libinput_config_scroll_method m) { (void)d; (void)m; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_scroll_method libinput_device_config_scroll_get_default_method(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_SCROLL_NO_SCROLL; }
enum libinput_config_status libinput_device_config_scroll_set_button(struct libinput_device *d, uint32_t b) { (void)d; (void)b; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
uint32_t libinput_device_config_scroll_get_default_button(struct libinput_device *d) { (void)d; return 0; }

int libinput_device_config_tap_get_finger_count(struct libinput_device *d) { (void)d; return 0; }
enum libinput_config_status libinput_device_config_tap_set_enabled(struct libinput_device *d, enum libinput_config_tap_state s) { (void)d; (void)s; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_tap_state libinput_device_config_tap_get_default_enabled(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_TAP_DISABLED; }
enum libinput_config_status libinput_device_config_tap_set_button_map(struct libinput_device *d, enum libinput_config_tap_button_map m) { (void)d; (void)m; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_tap_button_map libinput_device_config_tap_get_default_button_map(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_TAP_MAP_LRM; }
enum libinput_config_status libinput_device_config_tap_set_drag_enabled(struct libinput_device *d, enum libinput_config_drag_state s) { (void)d; (void)s; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_drag_state libinput_device_config_tap_get_default_drag_enabled(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_DRAG_DISABLED; }
enum libinput_config_status libinput_device_config_tap_set_drag_lock_enabled(struct libinput_device *d, enum libinput_config_drag_lock_state s) { (void)d; (void)s; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_drag_lock_state libinput_device_config_tap_get_default_drag_lock_enabled(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_DRAG_LOCK_DISABLED; }

enum libinput_config_status libinput_device_config_3fg_drag_set_enabled(struct libinput_device *d, enum libinput_config_3fg_drag_state s) { (void)d; (void)s; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_3fg_drag_state libinput_device_config_3fg_drag_get_default_enabled(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_3FG_DRAG_DISABLED; }

int libinput_device_config_dwt_is_available(struct libinput_device *d) { (void)d; return 0; }
enum libinput_config_status libinput_device_config_dwt_set_enabled(struct libinput_device *d, enum libinput_config_dwt_state s) { (void)d; (void)s; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_dwt_state libinput_device_config_dwt_get_default_enabled(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_DWT_DISABLED; }

int libinput_device_config_middle_emulation_is_available(struct libinput_device *d) { (void)d; return 0; }
enum libinput_config_status libinput_device_config_middle_emulation_set_enabled(struct libinput_device *d, enum libinput_config_middle_emulation_state s) { (void)d; (void)s; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_middle_emulation_state libinput_device_config_middle_emulation_get_default_enabled(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_MIDDLE_EMULATION_DISABLED; }

int libinput_device_config_left_handed_is_available(struct libinput_device *d) { (void)d; return 0; }
enum libinput_config_status libinput_device_config_left_handed_set(struct libinput_device *d, int v) { (void)d; (void)v; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
int libinput_device_config_left_handed_get_default(struct libinput_device *d) { (void)d; return 0; }

int libinput_device_config_rotation_is_available(struct libinput_device *d) { (void)d; return 0; }
enum libinput_config_status libinput_device_config_rotation_set_angle(struct libinput_device *d, unsigned int a) { (void)d; (void)a; return LIBINPUT_CONFIG_STATUS_SUCCESS; }

enum libinput_config_status libinput_device_config_click_set_method(struct libinput_device *d, enum libinput_config_click_method m) { (void)d; (void)m; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_click_method libinput_device_config_click_get_default_method(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_CLICK_METHOD_NONE; }
uint32_t libinput_device_config_click_get_methods(struct libinput_device *d) { (void)d; return 0; }

enum libinput_config_status libinput_device_config_send_events_set_mode(struct libinput_device *d, enum libinput_config_send_events_mode m) { (void)d; (void)m; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
enum libinput_config_send_events_mode libinput_device_config_send_events_get_default_mode(struct libinput_device *d) { (void)d; return LIBINPUT_CONFIG_SEND_EVENTS_ENABLED; }
uint32_t libinput_device_config_send_events_get_modes(struct libinput_device *d) { (void)d; return 0; }

int libinput_device_config_calibration_has_matrix(struct libinput_device *d) { (void)d; return 0; }
int libinput_device_config_calibration_get_default_matrix(struct libinput_device *d, float matrix[6]) {
	(void)d;
	if (matrix) {
		matrix[0] = 1; matrix[1] = 0; matrix[2] = 0;
		matrix[3] = 0; matrix[4] = 1; matrix[5] = 0;
	}
	return 0;
}
enum libinput_config_status libinput_device_config_calibration_set_matrix(struct libinput_device *d, const float matrix[6]) { (void)d; (void)matrix; return LIBINPUT_CONFIG_STATUS_SUCCESS; }

int libinput_tablet_tool_config_pressure_range_is_available(struct libinput_tablet_tool *t) { (void)t; return 0; }
double libinput_tablet_tool_config_pressure_range_get_minimum(struct libinput_tablet_tool *t) { (void)t; return 0; }
double libinput_tablet_tool_config_pressure_range_get_maximum(struct libinput_tablet_tool *t) { (void)t; return 1; }
enum libinput_config_status libinput_tablet_tool_config_pressure_range_set(struct libinput_tablet_tool *t, double min, double max) { (void)t; (void)min; (void)max; return LIBINPUT_CONFIG_STATUS_SUCCESS; }
