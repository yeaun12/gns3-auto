# Campus XDR VirtualBox package

`campus-xdr-virtualbox.zip` contains the GNS3 project, VirtualBox full-clone preparer, address inventory and Korean setup guide.

24 VMs, 8 switches, 36 links. All VMs default to powered off. Only new, independent full clones are referenced; existing project VMs are not reused. Extract the entire ZIP, run check-first.bat, then setup.bat before opening the .gns3 file.

Guest network/FRR/CARP configuration must be applied separately. Actual cloning, boot and connectivity have not been tested on the user's PC. GNS3 schema validation and 44 automated tests passed in the development environment.

## VirtualBox 7.2 compatibility fix (v2)

If check-first.bat stopped with `showmediuminfo ... unknown option: --machinereadable`, download `campus-virtualbox-fix-v2.zip` and replace only prepare_virtualbox.py and check-first.bat in the original extracted folder. The full campus ZIP is also updated. No project identity or VM name changed.

The check now saves check-result.txt. CHECK PASSED only validates prerequisites; no VM is cloned or started in check mode. Keep showvminfo's supported machine-readable option; only showmediuminfo was corrected. Real user-PC validation is still required.

## Read-only inventory of existing VirtualBox VMs

Use `virtualbox-vm-list-tool.zip` when you already have cloned VMs and want to reuse them. Extract it and double-click `collect-vms.bat`. It creates a uniquely named result folder with vm-inventory.json, vm-list.csv and vm-list.txt. Share the JSON or text file to map existing VMs into the campus project. No VM is cloned, started, stopped, registered, modified or deleted. Parent-dependent disks are reported; original/full-clone history and GNS3 project use are not guessed. Partial inspection is explicitly marked.

The standalone source is collect_virtualbox.py. Six inventory tests and the current full 50-test suite passed; real PC execution is still required. The original campus clone ZIP is not required for this inventory step.

## Campus project using existing VMs (no new clones)

Download campus-xdr-existing-vms.zip. This replaces the earlier full-clone workflow: do not run the old setup.bat. Extract to a new folder, inspect role-mapping.csv, run check-existing-vms.bat, then open Campus-XDR-existing.gns3 only if the checker passes.

The package selects 26 existing VMs from the supplied 51-VM inventory, excluding the named original bases. It contains 9 switches and 41 links, with automatic startup disabled. Current guest memory totals 16GiB for the smallest 8-VM profile, plus host/GNS3 overhead. Zeek and Suricata are inline and require transparent bridges; Sophos VMs are a candidate HA pair, while pfSense/Windows7 are isolated. HA, guest addressing, sensors and XDR services are not configured or validated on the PC.

The read-only checker verifies exact existing VM names/UUIDs, current disks, accessible disk parent chains and power-off state. The package contains no clone or setup tool. Import/start in GNS3 can change selected existing VM NICs; retained guest settings must be reviewed. Parent-dependent disk files/snapshots must be retained. Unselected VMs are untouched. The raw 51-VM inventory is not included. Schema validation and 55 automated tests passed; PC boot/connectivity remains unverified.

## Evidence-based PC diagnostics (full runtime verification is NOT complete)

Use campus-validation-tools.zip by extracting its files into the existing campus project folder. Open the GNS3 project, start only CORE1 and wait for its login screen, then run verify-campus.bat. Send verification-results-*/verification.json. The tool does not start/configure/clone/stop VMs and does not treat missing guest evidence or unrun scenarios as success.

The kit queries actual local VirtualBox/GNS3 nodes, wiring, VLANs, memory and runtime state. Optional Linux guest reports are checked for role/project/hardware identity and freshness before IP/OSPF/kernel route/bridge/service tests are evaluated. Read-only diagnostics cannot complete controlled HA, permit/deny, sensor log delivery or XDR incident/action/rollback scenarios; these remain explicitly unrun until access and actual observations exist.

60 automated tests and actual FRR 8.4.4 syntax parsing of four router templates passed in the development environment. This does NOT validate guest configuration, traffic, Sophos HA or XDR behavior on the user PC. SSH/Guest Additions access still needs to be established; credentials are never requested in chat. Local GNS3 authentication can be entered interactively with verify-campus-auth.bat if needed.
