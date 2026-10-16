/*
 * Gamepad support for Winlator
 *
 * Copyright 2026 BrunoSX
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301, USA
 */

/* Adapted from brunodev85/wine-10.10-custom bus_winlator.c (LGPL-2.1+).
 * ARLinux transport uses the existing same-UID Android gamepad broker rather
 * than Winlator's UDP WinHandler. Both screen and physical pads use it.
 */
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include "hidusage.h"
#define GAMEPAD_MAX_COUNT 4
#define GAMEPAD_GUID "arlinux-gamepad"
#define GAMEPAD_STATE_DISCONNECTED 0
#define GAMEPAD_STATE_CONNECTED 1
#define GAMEPAD_STATE_STARTED 2
#define AXIS_MODE_X_Y_Z_RZ 0
#define AXIS_MODE_X_Y_RX_RY_Z_RZ 1
struct android_pad_state { uint32_t magic, connected, buttons; int32_t axes[8]; };
struct gamepad {
    struct unix_device unix_device;
    uint8_t index, button_count, axis_mode, state;
    BOOL vibration, dirty;
    int fd;
    size_t pending;
    struct input_event event;
    struct android_pad_state snapshot;
};
static pthread_mutex_t gamepad_cs = PTHREAD_MUTEX_INITIALIZER;
static struct list event_queue = LIST_INIT(event_queue);
static struct list device_list = LIST_INIT(device_list);
static int android_control[2] = {-1, -1};
static inline struct gamepad *impl_from_unix_device(struct unix_device *iface)
{
    return CONTAINING_RECORD(iface, struct gamepad, unix_device);
}

static struct gamepad *find_device_from_index(int index)
{
    struct gamepad *impl;

    LIST_FOR_EACH_ENTRY(impl, &device_list, struct gamepad, unix_device.entry)
        if (impl->index == index) return impl;

    return NULL;
}

static void gamepad_destroy(struct unix_device *iface)
{
}

static NTSTATUS gamepad_start(struct unix_device *iface)
{
    struct gamepad *impl = impl_from_unix_device(iface);

    pthread_mutex_lock(&gamepad_cs);
    impl->state = GAMEPAD_STATE_STARTED;
    impl->dirty = TRUE;
    pthread_mutex_unlock(&gamepad_cs);
    return STATUS_SUCCESS;
}

static void gamepad_stop(struct unix_device *iface)
{
    struct gamepad *impl = impl_from_unix_device(iface);

    pthread_mutex_lock(&gamepad_cs);
    if (impl->fd >= 0) close(impl->fd);
    list_remove(&impl->unix_device.entry);
    pthread_mutex_unlock(&gamepad_cs);
}

static NTSTATUS gamepad_haptics_start(struct unix_device *iface, UINT duration_ms,
                                      USHORT rumble_intensity, USHORT buzz_intensity,
                                      USHORT left_intensity, USHORT right_intensity)
{
    struct gamepad *impl = impl_from_unix_device(iface);

    TRACE("iface %p, duration_ms %u, rumble_intensity %u, buzz_intensity %u, left_intensity %u, right_intensity %u.\n",
          iface, duration_ms, rumble_intensity, buzz_intensity, left_intensity, right_intensity);

    if (!impl->vibration) return STATUS_NOT_SUPPORTED;

    return STATUS_NOT_SUPPORTED;
}

static NTSTATUS gamepad_haptics_stop(struct unix_device *iface)
{
    struct gamepad *impl = impl_from_unix_device(iface);

    TRACE("iface %p.\n", iface);

    if (!impl->vibration) return STATUS_NOT_SUPPORTED;

    return STATUS_NOT_SUPPORTED;
}

static NTSTATUS gamepad_physical_device_control(struct unix_device *iface, USAGE control)
{
    return STATUS_NOT_SUPPORTED;
}

static NTSTATUS gamepad_physical_device_set_gain(struct unix_device *iface, BYTE percent)
{
    return STATUS_NOT_SUPPORTED;
}

static NTSTATUS gamepad_physical_effect_control(struct unix_device *iface, BYTE index,
                                                 USAGE control, BYTE iterations)
{
    return STATUS_NOT_SUPPORTED;
}

static NTSTATUS gamepad_physical_effect_update(struct unix_device *iface, BYTE index, struct effect_params *params)
{
    return STATUS_NOT_SUPPORTED;
}

static const struct hid_device_vtbl gamepad_vtbl =
{
    gamepad_destroy,
    gamepad_start,
    gamepad_stop,
    gamepad_haptics_start,
    gamepad_haptics_stop,
    gamepad_physical_device_control,
    gamepad_physical_device_set_gain,
    gamepad_physical_effect_control,
    gamepad_physical_effect_update,
};

static NTSTATUS build_gamepad_report_descriptor(struct unix_device *iface)
{
    const USAGE_AND_PAGE device_usage = {.UsagePage = HID_USAGE_PAGE_GENERIC, .Usage = HID_USAGE_GENERIC_GAMEPAD};
    const USAGE left_axis_usages[] = {HID_USAGE_GENERIC_X, HID_USAGE_GENERIC_Y};
    const USAGE right_axis_usages[] = {HID_USAGE_GENERIC_RX, HID_USAGE_GENERIC_RY};
    const USAGE trigger_axis_usages[] = {HID_USAGE_GENERIC_Z, HID_USAGE_GENERIC_RZ};
    struct gamepad *impl = impl_from_unix_device(iface);

    if (!hid_device_begin_report_descriptor(iface, &device_usage))
        return STATUS_NO_MEMORY;

    if (!hid_device_begin_input_report(iface, &device_usage))
        return STATUS_NO_MEMORY;

    if (impl->axis_mode == AXIS_MODE_X_Y_RX_RY_Z_RZ)
    {
        if (!hid_device_add_axes(iface, 2, HID_USAGE_PAGE_GENERIC, left_axis_usages,
                                 FALSE, -32768, 32767))
            return STATUS_NO_MEMORY;

        if (!hid_device_add_axes(iface, 2, HID_USAGE_PAGE_GENERIC, right_axis_usages,
                                 FALSE, -32768, 32767))
            return STATUS_NO_MEMORY;

        if (!hid_device_add_axes(iface, 2, HID_USAGE_PAGE_GENERIC, trigger_axis_usages,
                                 FALSE, 0, 32767))
            return STATUS_NO_MEMORY;
    }
    else if (impl->axis_mode == AXIS_MODE_X_Y_Z_RZ)
    {
        if (!hid_device_add_axes(iface, 2, HID_USAGE_PAGE_GENERIC, left_axis_usages,
                                 FALSE, -32768, 32767))
            return STATUS_NO_MEMORY;

        if (!hid_device_add_axes(iface, 2, HID_USAGE_PAGE_GENERIC, trigger_axis_usages,
                                 FALSE, -32768, 32767))
            return STATUS_NO_MEMORY;
    }

    if (!hid_device_add_hatswitch(iface, 1))
        return STATUS_NO_MEMORY;

    if (!hid_device_add_buttons(iface, HID_USAGE_PAGE_BUTTON, 1, impl->button_count))
        return STATUS_NO_MEMORY;

    if (!hid_device_end_input_report(iface))
        return STATUS_NO_MEMORY;

    if (impl->vibration)
    {
        if (!hid_device_add_haptics(&impl->unix_device))
            return FALSE;
    }

    if (!hid_device_end_report_descriptor(iface))
        return STATUS_NO_MEMORY;

    return STATUS_SUCCESS;
}

static void gamepad_create(int index, char *data)
{
    uint8_t button_count = data[0];
    uint8_t axis_mode = data[1];
    BOOL vibration = data[2] == 1 ? TRUE : FALSE;
    struct device_desc desc =
    {
        .interface = -1,
        .bus_id = -1,
        .manufacturer = {'A','R','L','i','n','u','x',0},
        .version = 0,
        .vid = (unsigned char)data[3] | ((unsigned char)data[4] << 8),
        .pid = (unsigned char)data[5] | ((unsigned char)data[6] << 8),
        .is_gamepad = FALSE,
    };
    int name_len = data[7];
    char* name = data + 8;
    char buffer[ARRAY_SIZE(desc.product)];
    struct gamepad *impl;

    snprintf(buffer, sizeof(buffer), "%s.%d", GAMEPAD_GUID, index);
    ntdll_umbstowcs(buffer, strlen(buffer) + 1, desc.serialnumber, ARRAY_SIZE(desc.serialnumber));
    ntdll_umbstowcs(name, name_len, desc.product, ARRAY_SIZE(desc.product));
    desc.product[name_len] = '\0';

    if (axis_mode == AXIS_MODE_X_Y_RX_RY_Z_RZ && button_count == 10)
        desc.is_gamepad = TRUE;

    TRACE("index %d, name %s, desc %s.\n", index, name, debugstr_device_desc(&desc));

    if (!(impl = hid_device_create(&gamepad_vtbl, sizeof(struct gamepad)))) return;
    list_add_tail(&device_list, &impl->unix_device.entry);
    impl->index = index;
    impl->fd = -1;
    impl->button_count = button_count;
    impl->axis_mode = axis_mode;
    impl->vibration = vibration;
    impl->state = GAMEPAD_STATE_CONNECTED;

    if (build_gamepad_report_descriptor(&impl->unix_device))
    {
        list_remove(&impl->unix_device.entry);
        impl->unix_device.vtbl->destroy(&impl->unix_device);
        return;
    }

    bus_event_queue_device_created(&event_queue, &impl->unix_device, &desc);
}

static void gamepad_set_state(int slot, char *data)
{
    int i, j, axis_count = 0;
    char dpad;
    BOOL pressed;
    unsigned short buttons;
    short axis_value;
    struct gamepad *impl = find_device_from_index(slot);
    struct unix_device *iface;
    struct hid_device_state *state;
    LONG dpad_x = 0, dpad_y = 0;
    if (!impl) return;
    iface = &impl->unix_device;
    state = &iface->hid_device_state;

    if (impl->state != GAMEPAD_STATE_STARTED)
    {
        WARN("Device %p with index %d is stopped, can't set state\n", impl, slot);
        return;
    }

    memcpy(&buttons, data, sizeof(buttons));
    dpad = data[2];

    for (i = 0; i < impl->button_count; i++)
    {
        pressed = (buttons & (1<<i)) ? TRUE : FALSE;
        hid_device_set_button(iface, i, pressed);
    }

    switch (dpad)
    {
    case 0: dpad_y = -1; break;
    case 1: dpad_x =  1; dpad_y = -1; break;
    case 2: dpad_x =  1; break;
    case 3: dpad_x =  1; dpad_y =  1; break;
    case 4: dpad_y =  1; break;
    case 5: dpad_x = -1; dpad_y =  1; break;
    case 6: dpad_x = -1; break;
    case 7: dpad_x = -1; dpad_y = -1; break;
    }

    hid_device_set_hatswitch_x(iface, 0, dpad_x);
    hid_device_set_hatswitch_y(iface, 0, dpad_y);

    if (impl->axis_mode == AXIS_MODE_X_Y_RX_RY_Z_RZ)
        axis_count = 6;
    else if (impl->axis_mode == AXIS_MODE_X_Y_Z_RZ)
        axis_count = 4;

    for (i = 0, j = 3; i < axis_count; i++, j += 2)
    {
        memcpy(&axis_value, data + j, sizeof(axis_value));
        hid_device_set_abs_axis(iface, i, axis_value);
    }

    bus_event_queue_input_report(&event_queue, iface, state->report_buf, state->report_len);
}



/* The protocol and evdev ordering are shared with Android's gamepad.c. */
static int android_connect(unsigned slot, unsigned query)
{
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    struct ucred peer;
    socklen_t length = sizeof(peer);
    uint32_t request[] = {0x41525047, slot, query};
    struct timeval timeout = {.tv_usec = 200000};
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    snprintf(address.sun_path + 1, sizeof(address.sun_path) - 1, "arlinux-gamepad-%u-0", (unsigned)getuid());
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) ||
        getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &length) || peer.uid != getuid() ||
        send(fd, request, sizeof(request), MSG_NOSIGNAL) != sizeof(request))
    { close(fd); return -1; }
    return fd;
}

static BOOL android_snapshot(unsigned slot, struct android_pad_state *state)
{
    int fd = android_connect(slot, 1);
    ssize_t size;
    if (fd < 0) return FALSE;
    size = recv(fd, state, sizeof(*state), MSG_WAITALL);
    close(fd);
    return size == sizeof(*state) && state->magic == 0x41525047 && state->connected;
}

static void android_remove(struct gamepad *impl)
{
    if (impl->state == GAMEPAD_STATE_DISCONNECTED) return;
    impl->state = GAMEPAD_STATE_DISCONNECTED;
    if (impl->fd >= 0) close(impl->fd);
    impl->fd = -1;
    bus_event_queue_device_removed(&event_queue, &impl->unix_device);
}

static void android_discover(void)
{
    unsigned slot;
    for (slot = 0; slot < GAMEPAD_MAX_COUNT; ++slot)
    {
        struct android_pad_state state;
        struct gamepad *impl = find_device_from_index(slot);
        if (!android_snapshot(slot, &state)) { if (impl) android_remove(impl); continue; }
        if (!impl)
        {
            char desc[59] = {10, AXIS_MODE_X_Y_RX_RY_Z_RZ, 0, 0x5e, 0x04, (char)0x8e, 0x02, 27};
            memcpy(desc + 8, "ARLinux Xbox 360 Controller", 27);
            gamepad_create(slot, desc);
            impl = find_device_from_index(slot);
        }
        if (!impl || impl->state == GAMEPAD_STATE_DISCONNECTED) continue;
        impl->snapshot = state;
        impl->dirty = TRUE;
        if (impl->fd < 0)
        {
            impl->fd = android_connect(slot, 0);
            if (impl->fd >= 0) fcntl(impl->fd, F_SETFL, O_NONBLOCK);
        }
    }
}

static void android_input(struct gamepad *impl)
{
    static const int keys[] = {BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST, BTN_TL, BTN_TR,
        BTN_SELECT, BTN_START, BTN_MODE, BTN_THUMBL, BTN_THUMBR};
    static const int axes[] = {ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_HAT0X, ABS_HAT0Y};
    for (;;)
    {
        struct input_event *event = &impl->event;
        ssize_t size = recv(impl->fd, (char *)event + impl->pending,
                            sizeof(*event) - impl->pending, MSG_DONTWAIT);
        unsigned i;
        if (!size) { android_remove(impl); return; }
        if (size < 0) { if (errno != EAGAIN && errno != EINTR) android_remove(impl); return; }
        impl->pending += size;
        if (impl->pending != sizeof(*event)) continue;
        impl->pending = 0;
        if (event->type == EV_KEY)
            for (i = 0; i < ARRAY_SIZE(keys); ++i) if (keys[i] == event->code)
            {
                impl->snapshot.buttons &= ~(1u << i);
                if (event->value) impl->snapshot.buttons |= 1u << i;
            }
        if (event->type == EV_ABS)
            for (i = 0; i < ARRAY_SIZE(axes); ++i) if (axes[i] == event->code)
                impl->snapshot.axes[i] = event->value;
        if (event->type == EV_SYN && event->code == SYN_REPORT) { impl->dirty = TRUE; return; }
    }
}

static void android_report(struct gamepad *impl)
{
    const struct android_pad_state *state = &impl->snapshot;
    /* Winlator HID packet: ten buttons, clockwise POV, LX/LY/RX/RY/LT/RT. */
    static const signed char hats[3][3] = {{7, 0, 1}, {6, -1, 2}, {5, 4, 3}};
    unsigned short buttons = (state->buttons & 0xff) | ((state->buttons >> 1) & 0x300);
    short axes[] = {state->axes[0], -state->axes[1] - 1, state->axes[3],
                    -state->axes[4] - 1, state->axes[2], state->axes[5]};
    char packet[15];
    int x = state->axes[6], y = state->axes[7];
    if (!impl->dirty || impl->state != GAMEPAD_STATE_STARTED) return;
    memcpy(packet, &buttons, 2);
    packet[2] = hats[(y > 0) - (y < 0) + 1][(x > 0) - (x < 0) + 1];
    memcpy(packet + 3, axes, sizeof(axes));
    gamepad_set_state(impl->index, packet);
    impl->dirty = FALSE;
}

NTSTATUS udev_bus_init(void *args)
{
    return pipe2(android_control, O_CLOEXEC | O_NONBLOCK) ? STATUS_UNSUCCESSFUL : STATUS_SUCCESS;
}

NTSTATUS udev_bus_wait(void *args)
{
    struct bus_event *result = args;
    struct timespec now;
    static uint64_t next_discovery;
    bus_event_cleanup(result);
    for (;;)
    {
        struct pollfd fds[GAMEPAD_MAX_COUNT + 1] = {{.fd = android_control[0], .events = POLLIN}};
        struct gamepad *impl;
        unsigned i;
        uint64_t millis;
        pthread_mutex_lock(&gamepad_cs);
        clock_gettime(CLOCK_MONOTONIC, &now);
        millis = (uint64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
        if (millis >= next_discovery) { android_discover(); next_discovery = millis + 500; }
        LIST_FOR_EACH_ENTRY(impl, &device_list, struct gamepad, unix_device.entry) android_report(impl);
        if (bus_event_queue_pop(&event_queue, result))
        { pthread_mutex_unlock(&gamepad_cs); return STATUS_PENDING; }
        for (i = 0; i < GAMEPAD_MAX_COUNT; ++i)
        {
            impl = find_device_from_index(i);
            fds[i + 1].fd = impl ? impl->fd : -1;
            fds[i + 1].events = POLLIN;
        }
        pthread_mutex_unlock(&gamepad_cs);
        if (poll(fds, ARRAY_SIZE(fds), 50) < 0 && errno != EINTR) break;
        if (fds[0].revents) break;
        pthread_mutex_lock(&gamepad_cs);
        for (i = 0; i < GAMEPAD_MAX_COUNT; ++i)
        {
            impl = find_device_from_index(i);
            if (!impl || impl->fd < 0 || impl->fd != fds[i + 1].fd || !fds[i + 1].revents) continue;
            android_input(impl);
            android_report(impl);
        }
        pthread_mutex_unlock(&gamepad_cs);
    }
    bus_event_queue_destroy(&event_queue);
    close(android_control[0]); close(android_control[1]);
    android_control[0] = android_control[1] = -1;
    return STATUS_SUCCESS;
}

NTSTATUS udev_bus_stop(void *args)
{
    if (android_control[1] >= 0) write(android_control[1], "q", 1);
    return STATUS_SUCCESS;
}
