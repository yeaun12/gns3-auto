# Campus XDR VirtualBox package

`campus-xdr-virtualbox.zip` contains the GNS3 project, VirtualBox full-clone preparer, address inventory and Korean setup guide.

24 VMs, 8 switches, 36 links. All VMs default to powered off. Only new, independent full clones are referenced; existing project VMs are not reused. Extract the entire ZIP, run check-first.bat, then setup.bat before opening the .gns3 file.

Guest network/FRR/CARP configuration must be applied separately. Actual cloning, boot and connectivity have not been tested on the user's PC. GNS3 schema validation and 39 automated tests passed in the development environment.
