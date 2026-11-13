#!/usr/bin/python3
"""BlueZ publication is live-only, deduplicated and restart-aware."""
from pathlib import Path
import sys
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'packaging/galaxy-companion/usr/lib/galaxy-companion'))
from galaxy_companion import spen_battery as module

p = module.PenBattery.__new__(module.PenBattery)
p.bus = Mock()
p.values = None
p.adapter = None
p.registered = p.registering = False
p.retry_at = 0
p.child = Mock()
p.InterfacesAdded = Mock()
p.InterfacesRemoved = Mock()
manager = Mock()
device = '/org/bluez/hci0/dev_00_00_00_00_00_01'
with patch.object(module.dbus, 'Interface', return_value=manager):
    p.update(device, 75)
    manager.RegisterBatteryProvider.assert_called_once()
    assert p.registering
    p._registered()
    assert p.GetManagedObjects()[module.ROOT + '/pen'][module.BATTERY]['Percentage'] == 75
    p.update(device, 75)
    p.child.PropertiesChanged.assert_not_called()
    p.update(device, 74)
    p.child.PropertiesChanged.assert_called_once()
    p.update(device, None)
    assert not p.GetManagedObjects()
    p.InterfacesRemoved.assert_called_once()
    p._owner_changed('org.bluez', 'old', 'new')
    assert not p.registered
    p.update(device, 74)
    assert manager.RegisterBatteryProvider.call_count == 2
print('PASS current percentage only, no duplicate work, disconnect removal and BlueZ restart recovery')


# The docked-pen panel is sized from the screen edge it lies along.  A fixed
# 1050 px of pen covered three quarters of this tablet's 1480 px long edge,
# which is what "the pop-up is huge" meant.  Keep it a card on both edges.
import re  # noqa: E402

source = (Path(__file__).resolve().parents[1] /
          'packaging/galaxy-companion/usr/share/gnome-shell/extensions'
          '/spen-dock@agcarbajo.github.io/extension.js').read_text()


def constant(name):
    match = re.search(r'^const ' + name + r' = ([0-9.]+);$', source, re.M)
    assert match, name + ' is no longer a constant in extension.js'
    return float(match.group(1))


fraction, cap = constant('PEN_LONG_FRACTION'), constant('PEN_LONG_MAX')
minimum, slack = constant('PEN_MIN'), constant('PANEL_SLACK')
assert 'PEN_LONG_WANTED' not in source, 'the fixed pen length is back'
for edge in (1480, 924):  # this tablet's logical panel, upright and sideways
    pen = max(minimum, min(min(cap, round(edge * fraction)), round(edge - slack)))
    assert pen + slack <= edge * 0.45, 'the pen panel is a banner again on a %d px edge' % edge
    assert pen >= minimum, 'the pen would be drawn smaller than its own minimum'
print('PASS docked-pen panel stays a card on both screen edges')
