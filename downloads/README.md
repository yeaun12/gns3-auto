# Campus XDR VirtualBox package

`campus-xdr-virtualbox.zip` contains the GNS3 project, VirtualBox full-clone preparer, address inventory and Korean setup guide.

24 VMs, 8 switches, 36 links. All VMs default to powered off. Only new, independent full clones are referenced; existing project VMs are not reused. Extract the entire ZIP, run check-first.bat, then setup.bat before opening the .gns3 file.

Guest network/FRR/CARP configuration must be applied separately. Actual cloning, boot and connectivity have not been tested on the user's PC. GNS3 schema validation and 44 automated tests passed in the development environment.

## VirtualBox 7.2 compatibility fix (v2)

If check-first.bat stopped with `showmediuminfo ... unknown option: --machinereadable`, download `campus-virtualbox-fix-v2.zip` and replace only prepare_virtualbox.py and check-first.bat in the original extracted folder. The full campus ZIP is also updated. No project identity or VM name changed.

The check now saves check-result.txt. CHECK PASSED only validates prerequisites; no VM is cloned or started in check mode. Keep showvminfo's supported machine-readable option; only showmediuminfo was corrected. Real user-PC validation is still required.
