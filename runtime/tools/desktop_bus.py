"""Join the desktop-owned accessibility session without starting services."""
from pathlib import Path


def environment(source):
    import dbus

    env = dict(source)
    try:
        address = (Path(env['XDG_RUNTIME_DIR']) / 'desktop-session-bus').read_text().strip()
        bus = dbus.bus.BusConnection(address)
        try:
            # Resolve a live unique owner first: a missing service is a session
            # failure, not permission for an application to activate a new bus.
            owner = bus.get_name_owner('org.a11y.Bus')
            proxy = bus.get_object(owner, '/org/a11y/bus', introspect=False)
            accessibility = str(dbus.Interface(proxy, 'org.a11y.Bus').GetAddress(timeout=3))
        finally:
            bus.close()
        connection = dbus.bus.BusConnection(accessibility)
        connection.close()
    except (OSError, KeyError, dbus.DBusException) as error:
        raise RuntimeError('Desktop accessibility bus unavailable; save work and reopen the desktop. '
                           'Do not delete its sockets or replace its services.') from error
    env.update(DBUS_SESSION_BUS_ADDRESS=address, AT_SPI_BUS_ADDRESS=accessibility, NO_AT_BRIDGE='0')
    return env
