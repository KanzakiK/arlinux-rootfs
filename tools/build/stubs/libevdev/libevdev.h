#ifndef ARLINUX_STUB_LIBEVDEV_H
#define ARLINUX_STUB_LIBEVDEV_H

#define EV_KEY 0x01

int libevdev_event_code_from_name(unsigned int type, const char *name);

#endif
