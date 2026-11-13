# Bluetooth event and service lifecycle

`HardwareService.sample()` is the one-second timer callback and returns
`GLib.SOURCE_CONTINUE`. Passing it directly to `idle_add` after an adapter
`Powered` change retains an idle source that runs again immediately. Every
toggle can add another such source.

The adapter event now schedules `sample_once()`, which samples and returns
`GLib.SOURCE_REMOVE`. The regular timer retains its repeating behavior.
`scripts/test-companion-efficiency.py` exercises the actual event and wrapper
methods with three synthetic adapter toggles and verifies one callback per
event. It uses no device or system bus.

The pairing daemon holds proxies belonging to bluetoothd. Its unit now has
`PartOf=bluetooth.service`, in addition to its startup ordering and dependency,
so stopping/restarting bluetoothd propagates to pairing and recreates those
proxies. The existing reconnect/status regressions remain applicable.

The Linux package candidate is `1:1.0.1`. Physical S Pen acceptance after a
bluetoothd package upgrade or restart remains pending. This follows findings
B1/B2 in the Ubuntu port's issue 13. After upstream integration, the port's
Galaxy Companion submodule pin and paired package requirement need updating;
the port still pins its released upstream revision.
