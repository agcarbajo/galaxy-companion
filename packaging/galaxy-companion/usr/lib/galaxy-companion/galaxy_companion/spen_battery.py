# SPDX-License-Identifier: MIT
"""Publish Samsung's proprietary GATT battery through BlueZ's standard API.

UPower consumes org.bluez.Battery1; the pen does not implement the standard
GATT battery service. Never publish the saved, possibly stale UI percentage.
"""
import time
import dbus
import dbus.service

MANAGER = "org.freedesktop.DBus.ObjectManager"
PROPERTIES = "org.freedesktop.DBus.Properties"
BATTERY = "org.bluez.BatteryProvider1"
ROOT = "/io/github/agcarbajo/GalaxyCompanion/Batteries"


class BatteryObject(dbus.service.Object):
    def __init__(self, bus, provider):
        super().__init__(bus, ROOT + "/pen")
        self.provider = provider

    @dbus.service.method(PROPERTIES, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return (self.provider.values or {}) if interface == BATTERY else {}

    @dbus.service.method(PROPERTIES, in_signature="ss", out_signature="v")
    def Get(self, interface, name):
        values = self.GetAll(interface)
        if name not in values:
            raise dbus.exceptions.DBusException("Unknown battery property",
                name="org.freedesktop.DBus.Error.InvalidArgs")
        return values[name]

    @dbus.service.signal(PROPERTIES, signature="sa{sv}as")
    def PropertiesChanged(self, interface, values, invalidated):
        pass


class PenBattery(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, ROOT)
        self.bus = bus
        self.values = None
        self.adapter = None
        self.registered = False
        self.registering = False
        self.retry_at = 0
        self.child = BatteryObject(bus, self)
        bus.add_signal_receiver(self._owner_changed,
            dbus_interface="org.freedesktop.DBus", signal_name="NameOwnerChanged",
            arg0="org.bluez")

    def _owner_changed(self, _name, _old, _new):
        self.registered = self.registering = False
        self.retry_at = 0

    @dbus.service.method(MANAGER, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return ({ROOT + "/pen": {BATTERY: self.values}}
                if self.values is not None else {})

    @dbus.service.signal(MANAGER, signature="oa{sa{sv}}")
    def InterfacesAdded(self, path, interfaces):
        pass

    @dbus.service.signal(MANAGER, signature="oas")
    def InterfacesRemoved(self, path, interfaces):
        pass

    def update(self, device, percentage):
        if not device or percentage is None or not 0 <= percentage <= 100:
            if self.values is not None:
                self.InterfacesRemoved(ROOT + "/pen", [BATTERY])
            self.values = None
            return
        adapter = str(device).rsplit("/dev_", 1)[0]
        if not self.registered and not self.registering and time.monotonic() >= self.retry_at:
            self.adapter = adapter
            self.registering = True
            try:
                # BlueZ calls GetManagedObjects during registration: this must
                # be asynchronous so our main loop can answer it.
                manager = dbus.Interface(self.bus.get_object("org.bluez", adapter),
                                         "org.bluez.BatteryProviderManager1")
                manager.RegisterBatteryProvider(ROOT,
                    reply_handler=self._registered, error_handler=self._failed)
            except dbus.DBusException as error:
                self._failed(error)
        values = {"Device": dbus.ObjectPath(device), "Percentage": dbus.Byte(percentage),
                  "Source": dbus.String("Samsung S Pen")}
        if values == self.values:
            return
        previous = self.values
        if previous is not None and previous['Device'] != values['Device']:
            self.InterfacesRemoved(ROOT + "/pen", [BATTERY])
            previous = None
        self.values = values
        if previous is None:
            self.InterfacesAdded(ROOT + "/pen", {BATTERY: values})
        else:
            self.child.PropertiesChanged(BATTERY, values, [])

    def _registered(self):
        self.registering = False
        self.registered = True

    def _failed(self, error):
        self.registering = False
        self.registered = False
        self.retry_at = time.monotonic() + 60
        print(f"S Pen battery provider unavailable: {error}", flush=True)
