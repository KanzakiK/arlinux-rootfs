"""Join the desktop-owned accessibility session without starting services."""
from pathlib import Path
import sys
import time


def environment(source, *, timeout=10):
    import dbus

    env = dict(source)
    session = Path(env['XDG_RUNTIME_DIR']) / 'desktop-session-bus'
    deadline = time.monotonic() + timeout
    waiting = False

    def remaining():
        return max(0.001, deadline - time.monotonic())

    def owner(bus, name):
        # Do not activate services from an application. The desktop owns them.
        return bus.call_blocking('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                 'org.freedesktop.DBus', 'GetNameOwner', 's', (name,),
                                 timeout=remaining())

    while True:
        try:
            # A cold restart can leave the previous address until the new
            # desktop publishes its ready session. Re-read it on every attempt.
            address = session.read_text().strip()
            bus = dbus.bus.BusConnection(address)
            try:
                proxy = bus.get_object(owner(bus, 'org.a11y.Bus'), '/org/a11y/bus', introspect=False)
                accessibility = str(dbus.Interface(proxy, 'org.a11y.Bus').GetAddress(timeout=remaining()))
            finally:
                bus.close()
            connection = dbus.bus.BusConnection(accessibility)
            try:
                registry = connection.get_object(owner(connection, 'org.a11y.atspi.Registry'),
                                                 '/org/a11y/atspi/accessible/root', introspect=False)
                dbus.Interface(registry, 'org.freedesktop.DBus.Peer').Ping(timeout=remaining())
            finally:
                connection.close()
            break
        except (OSError, dbus.DBusException) as error:
            if time.monotonic() >= deadline:
                raise RuntimeError('Desktop accessibility bus unavailable; save work and reopen the desktop. '
                                   'Do not delete its sockets or replace its services.') from error
            if not waiting:
                print('Waiting for the desktop accessibility session...', file=sys.stderr, flush=True)
                waiting = True
            time.sleep(min(0.1, remaining()))
    env.update(DBUS_SESSION_BUS_ADDRESS=address, AT_SPI_BUS_ADDRESS=accessibility, NO_AT_BRIDGE='0')
    return env
