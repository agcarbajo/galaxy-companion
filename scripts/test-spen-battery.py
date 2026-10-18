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
