"""Expose an existing Wine prefix's Windows MSAA controls on the desktop AT-SPI bus.

The Windows observer uses documented accessibility objects and control messages.
Consumers use ordinary pyatspi interfaces; unsupported operations return false.
Visibility and coordinates describe the Wine desktop, as reported by MSAA.
Host compositor occlusion and screenshot-coordinate translation are not exposed.
"""
from pathlib import Path
import argparse
import fcntl
import hashlib
import json
import os
import selectors
import subprocess
import sys
import time

ROOT = '/org/a11y/atspi/accessible/root'
PREFIX = '/org/a11y/atspi/accessible'
NULL = '/org/a11y/atspi/null'
MSAA_INVISIBLE = 0x8000
MSAA_OFFSCREEN = 0x10000


def ensure(root, prefix, name, env):
    """Start one accessibility adapter per prefix and desktop session."""
    if not env.get('AT_SPI_BUS_ADDRESS'):
        raise RuntimeError('Windows accessibility requires the active desktop accessibility session')
    state = Path(env['XDG_RUNTIME_DIR']) / 'windows-accessibility'
    state.mkdir(mode=0o700, exist_ok=True)
    key = hashlib.sha256(os.fsencode(prefix) + env['AT_SPI_BUS_ADDRESS'].encode()).hexdigest()[:24]
    lock = state / (key + '.lock')
    with lock.open('a') as marker:
        try:
            fcntl.flock(marker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with (state / (key + '.log')).open('ab') as log:
            process = subprocess.Popen([sys.executable, __file__, '--prefix', str(prefix),
                                        '--name', name, '--lock', str(lock), '--lock-fd', str(marker.fileno())],
                                       env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, start_new_session=True,
                                       pass_fds=(marker.fileno(),))
    return process.pid


class Observer:
    def __init__(self, env):
        import windows
        self.response, self.socket = windows.request(
            windows.runtime(env['ARLINUX_WINDOWS_RUNTIME']),
            Path(env['ARLINUX_WINDOWS_PREFIX']),
            windows.runtime(env['ARLINUX_WINDOWS_RUNTIME']) / 'files/lib/arlinux/windows-accessibility.exe',
            stdio=True, task=False)
        self.stdin = self.socket.makefile('wb', buffering=0)
        self.stdout = self.socket.makefile('rb', buffering=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.stdout, selectors.EVENT_READ)
        self.buffer = bytearray()

    def close(self):
        import socket
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.stdin.close()
        self.stdout.close()
        self.socket.close()
        self.selector.close()

    def call(self, command):
        self.stdin.write((command + '\n').encode())
        deadline = time.monotonic() + 15
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                self.close()
                raise RuntimeError('Windows accessibility provider timed out')
            data = os.read(self.stdout.fileno(), 65536)
            if not data:
                raise RuntimeError('Windows accessibility observer exited')
            self.buffer.extend(data)
        line, _, rest = self.buffer.partition(b'\n')
        self.buffer = bytearray(rest)
        result = json.loads(line)
        if isinstance(result, dict) and 'error' in result:
            raise LookupError(result['error'])
        return result


def serve(prefix, name, lock, lock_fd=None):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import GLib, Atspi
    import windows

    marker = os.fdopen(lock_fd, 'a') if lock_fd is not None else lock.open('a')
    try:
        fcntl.flock(marker, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    env = windows.environment(windows.runtime(os.environ['ARLINUX_WINDOWS_RUNTIME']), prefix)
    DBusGMainLoop(set_as_default=True)
    bus = dbus.bus.BusConnection(env['AT_SPI_BUS_ADDRESS'])
    observer = Observer(env)
    bus_name = str(bus.get_unique_name())
    roles = {
        1: 'TITLE_BAR', 2: 'MENU_BAR', 3: 'SCROLL_BAR', 4: 'GRIP', 5: 'ALERT',
        9: 'FRAME', 10: 'PANEL', 11: 'POPUP_MENU', 12: 'MENU_ITEM', 15: 'DOCUMENT_FRAME',
        16: 'PANEL', 17: 'DIALOG', 18: 'LABEL', 20: 'SEPARATOR', 21: 'SEPARATOR',
        22: 'TOOL_BAR', 23: 'STATUS_BAR', 24: 'TABLE', 25: 'TABLE_COLUMN_HEADER',
        26: 'TABLE_ROW_HEADER', 27: 'TABLE_COLUMN', 28: 'TABLE_ROW', 29: 'TABLE_CELL',
        30: 'LINK', 33: 'LIST', 34: 'LIST_ITEM', 35: 'TREE', 36: 'TREE_ITEM',
        37: 'PAGE_TAB', 38: 'PROPERTY_PAGE', 39: 'LAYERED_PANE', 40: 'IMAGE',
        41: 'LABEL', 42: 'ENTRY', 43: 'PUSH_BUTTON', 44: 'CHECK_BOX', 45: 'RADIO_BUTTON',
        46: 'COMBO_BOX', 47: 'COMBO_BOX', 48: 'PROGRESS_BAR', 49: 'DIAL',
        51: 'SLIDER', 52: 'SPIN_BUTTON', 56: 'ANIMATION', 60: 'PAGE_TAB_LIST',
        62: 'PUSH_BUTTON', 63: 'PUSH_BUTTON',
    }

    class Adapter(dbus.service.FallbackObject):
        def __init__(self):
            super().__init__(bus, '/org/a11y/atspi')
            self.nodes = {}
            self.children = {0: []}
            self.updated = 0
            self.application_id = 0
            self.desktop = ('org.a11y.atspi.Registry', ROOT)

        def ref(self, id):
            return dbus.Struct((bus_name, ROOT if id == 0 else PREFIX + '/n' + str(id)), signature='so')

        def identity(self, path):
            return 0 if path == ROOT else int(path.rsplit('/n', 1)[1])

        def update(self, force=False):
            if not force and time.monotonic() - self.updated < 1:
                return
            items = observer.call('snapshot')
            self.nodes = {item['id']: item for item in items}
            self.children = {0: []}
            for item in items:
                self.children.setdefault(item['parent'], []).append(item['id'])
            self.updated = time.monotonic()

        def node(self, id, fresh=False):
            if id == 0:
                return {'id': 0, 'parent': 0, 'name': name, 'value': '', 'action': '',
                        'role': 0, 'state': 0, 'rect': [0, 0, 0, 0], 'editable': False}
            if fresh:
                value = observer.call('get ' + str(id)); self.nodes[id] = value
            if id not in self.nodes:
                raise dbus.exceptions.DBusException('Stale Windows control', name='org.a11y.atspi.Error.InvalidObject')
            return self.nodes[id]

        def showing(self, id):
            while id:
                n = self.node(id)
                if n['state'] & (MSAA_INVISIBLE | MSAA_OFFSCREEN):
                    return False
                id = n['parent']
            return True

        def state(self, id):
            n = self.node(id)
            states = [] if n['state'] & MSAA_INVISIBLE else ['VISIBLE']
            if self.showing(id): states.append('SHOWING')
            if not n['state'] & 1: states += ['ENABLED', 'SENSITIVE']
            for bit, state in ((2, 'SELECTED'), (4, 'FOCUSED'), (0x10, 'CHECKED'),
                               (0x20, 'INDETERMINATE'), (0x200, 'EXPANDED'),
                               (0x400, 'COLLAPSED'), (0x100000, 'FOCUSABLE'),
                               (0x200000, 'SELECTABLE'), (0x20000000, 'MULTI_LINE')):
                if n['state'] & bit: states.append(state)
            if n['editable']: states.append('EDITABLE')
            words = [0, 0]
            for state in states:
                value = int(getattr(Atspi.StateType, state)); words[value // 32] |= 1 << (value % 32)
            return dbus.Array(words, signature='u')

        def role(self, id):
            return int(Atspi.Role.APPLICATION if not id else getattr(Atspi.Role, roles.get(self.node(id)['role'], 'UNKNOWN'), Atspi.Role.UNKNOWN))

        def interfaces(self, id):
            n = self.node(id)
            names = ['org.a11y.atspi.Accessible', 'org.a11y.atspi.Component']
            if not id: names.append('org.a11y.atspi.Application')
            if n['action']: names.append('org.a11y.atspi.Action')
            if n['role'] in (41, 42) or n['value']: names.append('org.a11y.atspi.Text')
            if n['editable']: names.append('org.a11y.atspi.EditableText')
            return names

        @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='ss', out_signature='v', path_keyword='path')
        def Get(self, interface, property, path=None):
            id = self.identity(path)
            # Registry discovery must never wait for a Windows provider scan.
            if id or property == 'ChildCount': self.update()
            n = self.node(id)
            if interface == 'org.a11y.atspi.Accessible':
                return {'Name': n['name'], 'Description': '', 'Parent': self.desktop if id == 0 else self.ref(n['parent']),
                        'ChildCount': dbus.Int32(len(self.children.get(id, []))), 'Locale': '',
                        'AccessibleId': str(id), 'HelpText': ''}[property]
            if interface == 'org.a11y.atspi.Application':
                return {'ToolkitName': 'Windows MSAA (Wine)', 'Version': '1', 'AtspiVersion': '2.1',
                        'Id': dbus.Int32(self.application_id)}[property]
            if interface == 'org.a11y.atspi.Action' and property == 'NActions': return dbus.Int32(bool(n['action']))
            if interface == 'org.a11y.atspi.Text':
                text = self.text(id)
                return {'CharacterCount': dbus.Int32(len(text)), 'CaretOffset': dbus.Int32(0)}[property]
            raise dbus.exceptions.DBusException('Unsupported property', name='org.freedesktop.DBus.Error.UnknownProperty')

        @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='ssv', out_signature='', path_keyword='path')
        def Set(self, interface, property, value, path=None):
            if interface == 'org.a11y.atspi.Application' and property == 'Id': self.application_id = int(value)
            else: raise dbus.exceptions.DBusException('Read-only property', name='org.freedesktop.DBus.Error.PropertyReadOnly')

        @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='s', out_signature='a{sv}', path_keyword='path')
        def GetAll(self, interface, path=None):
            fields = {'org.a11y.atspi.Accessible': ['Name', 'Description', 'Parent', 'ChildCount', 'Locale', 'AccessibleId', 'HelpText'],
                      'org.a11y.atspi.Application': ['ToolkitName', 'Version', 'AtspiVersion', 'Id'],
                      'org.a11y.atspi.Text': ['CharacterCount', 'CaretOffset'], 'org.a11y.atspi.Action': ['NActions']}
            return {field: self.Get(interface, field, path) for field in fields.get(interface, [])}

        @dbus.service.method('org.a11y.atspi.Accessible', in_signature='i', out_signature='(so)', path_keyword='path')
        def GetChildAtIndex(self, index, path=None):
            self.update(); children = self.children.get(self.identity(path), [])
            return self.ref(children[index]) if 0 <= index < len(children) else ('', NULL)

        @dbus.service.method('org.a11y.atspi.Accessible', out_signature='a(so)', path_keyword='path')
        def GetChildren(self, path=None):
            self.update(); return [self.ref(id) for id in self.children.get(self.identity(path), [])]

        @dbus.service.method('org.a11y.atspi.Accessible', out_signature='i', path_keyword='path')
        def GetIndexInParent(self, path=None):
            id = self.identity(path)
            return self.children.get(self.node(id)['parent'], []).index(id) if id else -1

        @dbus.service.method('org.a11y.atspi.Accessible', out_signature='u', path_keyword='path')
        def GetRole(self, path=None): return self.role(self.identity(path))

        @dbus.service.method('org.a11y.atspi.Accessible', out_signature='s', path_keyword='path')
        def GetRoleName(self, path=None): return Atspi.role_get_name(self.role(self.identity(path)))

        @dbus.service.method('org.a11y.atspi.Accessible', out_signature='s', path_keyword='path')
        def GetLocalizedRoleName(self, path=None): return self.GetRoleName(path)

        @dbus.service.method('org.a11y.atspi.Accessible', out_signature='au', path_keyword='path')
        def GetState(self, path=None):
            id = self.identity(path)
            if id: self.update()
            if id: self.node(id, fresh=True)
            return self.state(id)

        @dbus.service.method('org.a11y.atspi.Accessible', out_signature='a{ss}', path_keyword='path')
        def GetAttributes(self, path=None):
            n = self.node(self.identity(path)); return {'toolkit': 'Windows MSAA', 'windows-role': str(n['role'])}

        @dbus.service.method('org.a11y.atspi.Accessible', out_signature='a(ua(so))')
        def GetRelationSet(self): return []

        @dbus.service.method('org.a11y.atspi.Accessible', out_signature='(so)')
        def GetApplication(self): return self.ref(0)

        @dbus.service.method('org.a11y.atspi.Accessible', out_signature='as', path_keyword='path')
        def GetInterfaces(self, path=None): return self.interfaces(self.identity(path))

        @dbus.service.method('org.a11y.atspi.Application', in_signature='u', out_signature='s')
        def GetLocale(self, type): return ''

        @dbus.service.method('org.a11y.atspi.Cache', out_signature='a((so)(so)(so)iiassusau)')
        def GetItems(self):
            self.update(force=True)
            result = []
            for id in [0, *[key for values in self.children.values() for key in values]]:
                n = self.node(id); parent = self.desktop if id == 0 else self.ref(n['parent'])
                index = -1 if id == 0 else self.children[n['parent']].index(id)
                result.append((self.ref(id), self.ref(0), parent, index, len(self.children.get(id, [])),
                               self.interfaces(id), n['name'], self.role(id), '', self.state(id)))
            return result

        def act(self, path, operation, argument=''):
            self.update(); id = self.identity(path)
            if not id or not self.showing(id): return False
            node = self.node(id)
            while True:
                if node['state'] & 1: return False
                if not node['parent']: break
                node = self.node(node['parent'])
            result = observer.call(f'{operation} {id} {argument}')
            self.updated = 0
            return result

        @dbus.service.method('org.a11y.atspi.Action', out_signature='a(sss)', path_keyword='path')
        def GetActions(self, path=None): return [('click', self.node(self.identity(path))['action'], '')] if self.node(self.identity(path))['action'] else []

        @dbus.service.method('org.a11y.atspi.Action', in_signature='i', out_signature='s', path_keyword='path')
        def GetName(self, index, path=None): return 'click' if index == 0 and self.node(self.identity(path))['action'] else ''

        @dbus.service.method('org.a11y.atspi.Action', in_signature='i', out_signature='s', path_keyword='path')
        def GetLocalizedName(self, index, path=None): return self.GetName(index, path)

        @dbus.service.method('org.a11y.atspi.Action', in_signature='i', out_signature='s', path_keyword='path')
        def GetDescription(self, index, path=None): return self.node(self.identity(path))['action'] if index == 0 else ''

        @dbus.service.method('org.a11y.atspi.Action', in_signature='i', out_signature='s')
        def GetKeyBinding(self, index): return ''

        @dbus.service.method('org.a11y.atspi.Action', in_signature='i', out_signature='b', path_keyword='path')
        def DoAction(self, index, path=None): return index == 0 and self.act(path, 'invoke')

        @dbus.service.method('org.a11y.atspi.Component', out_signature='b', path_keyword='path')
        def GrabFocus(self, path=None): return self.act(path, 'focus')

        @dbus.service.method('org.a11y.atspi.Component', in_signature='u', out_signature='(iiii)', path_keyword='path')
        def GetExtents(self, type, path=None):
            id = self.identity(path); n = self.node(id, fresh=bool(id)); rect = list(n['rect'])
            if type == 1 and id:
                root = n
                while root['parent']: root = self.node(root['parent'])
                rect[0] -= root['rect'][0]; rect[1] -= root['rect'][1]
            return rect

        @dbus.service.method('org.a11y.atspi.Component', in_signature='u', out_signature='ii', path_keyword='path')
        def GetPosition(self, type, path=None): return self.GetExtents(type, path)[:2]

        @dbus.service.method('org.a11y.atspi.Component', out_signature='ii', path_keyword='path')
        def GetSize(self, path=None): return self.GetExtents(0, path)[2:]

        @dbus.service.method('org.a11y.atspi.Component', in_signature='iiu', out_signature='b', path_keyword='path')
        def Contains(self, x, y, type, path=None):
            a, b, w, h = self.GetExtents(type, path); return a <= x < a + w and b <= y < b + h

        @dbus.service.method('org.a11y.atspi.Component', out_signature='u')
        def GetLayer(self): return 3

        @dbus.service.method('org.a11y.atspi.Component', out_signature='n')
        def GetMDIZOrder(self): return 0

        @dbus.service.method('org.a11y.atspi.Component', out_signature='d')
        def GetAlpha(self): return 1.0

        def text(self, id):
            n = self.node(id, fresh=bool(id)); return n['value'] if n['role'] == 42 or n['value'] else n['name']

        @dbus.service.method('org.a11y.atspi.Text', in_signature='ii', out_signature='s', path_keyword='path')
        def GetText(self, start, end, path=None):
            text = self.text(self.identity(path)); return text[max(0, start):None if end < 0 else end]

        @dbus.service.method('org.a11y.atspi.Text', in_signature='i', out_signature='i', path_keyword='path')
        def GetCharacterAtOffset(self, offset, path=None):
            text = self.text(self.identity(path)); return ord(text[offset]) if 0 <= offset < len(text) else 0

        @dbus.service.method('org.a11y.atspi.EditableText', in_signature='s', out_signature='b', path_keyword='path')
        def SetTextContents(self, text, path=None): return self.act(path, 'set', str(text).encode().hex())

        @dbus.service.method('org.a11y.atspi.EditableText', in_signature='isi', out_signature='b', path_keyword='path')
        def InsertText(self, position, text, length, path=None):
            current = self.text(self.identity(path))
            if not 0 <= position <= len(current): return False
            return self.SetTextContents(current[:position] + str(text)[:length] + current[position:], path)

        @dbus.service.method('org.a11y.atspi.EditableText', in_signature='ii', out_signature='b', path_keyword='path')
        def DeleteText(self, start, end, path=None):
            current = self.text(self.identity(path))
            if not 0 <= start <= end <= len(current): return False
            return self.SetTextContents(current[:start] + current[end:], path)

    adapter = Adapter()
    registry = bus.get_object('org.a11y.atspi.Registry', ROOT, introspect=False)
    adapter.desktop = dbus.Interface(registry, 'org.a11y.atspi.Socket').Embed(adapter.ref(0), signature='(so)')
    loop = GLib.MainLoop()
    bus.call_on_disconnection(lambda connection: loop.quit())
    try:
        loop.run()
    finally:
        try: dbus.Interface(registry, 'org.a11y.atspi.Socket').Unembed(adapter.ref(0), signature='(so)')
        except dbus.DBusException: pass
        observer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--lock-fd', type=int)
    args = parser.parse_args()
    serve(args.prefix, args.name, args.lock, args.lock_fd)
