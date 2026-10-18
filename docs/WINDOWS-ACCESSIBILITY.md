# Windows accessibility

Windows applications launched through `arlinux-windows` and
`arlinux-windows-app` automatically expose their Windows MSAA controls on
the session's AT-SPI bus. Android, Linux and Windows applications use the
same `arlinux.a11y` and `pyatspi` entry points.

For an open Paint.NET window:

```python
from arlinux import a11y

print(a11y.describe(app='Paint.NET'))
settings = a11y.find('Settings (Alt+X)', app='Paint.NET')[0]
settings.queryAction().doAction(0)
```

The adapter exposes names, roles, children, state, component bounds,
default actions, focus, text and editable text when the Windows provider
supports them. `queryEditableText().setTextContents(value)` writes through
the provider. Protected text is withheld. Custom controls that expose no
MSAA objects remain unavailable; this is not full Windows UI Automation
pattern support. Text selection and accessibility event streaming are not
implemented.

Yibu's compositor visibility controls the AT-SPI SHOWING state. Background
controls cannot execute actions, focus or text edits; disabled ancestors
also block operations while a modal dialog is open. Visibility currently
matches the Windows top-level title to the compositor's Xwayland title.
Applications with identical top-level titles can be ambiguous.

One adapter runs per Wine prefix and AT-SPI session. Its logs are under
`$XDG_RUNTIME_DIR/windows-accessibility/`. Starting the same application
again reuses the adapter. Application grouping follows the launcher's
prefix name, so multiple applications sharing a prefix share that name.
Steam/Proton game prefixes do not start this adapter.

## Build integration

The observer is an ARM64 Windows executable built by the independent Wine
pipeline and consumed as a verified helper artifact by rootfs packaging.
Use only [BUILD.md](BUILD.md); no separate observer build or assets override
is a supported product build path. Runtime dependencies are Python D-Bus,
PyGObject, AT-SPI and the shared Bionic Wine runtime.

Validated on Xiaomi 15 with Paint.NET: enumerate menu/tool controls,
open Settings by default action, close the dialog, write/read/restore the
hex color field, and reject a retained control reference after switching
to Apps.
