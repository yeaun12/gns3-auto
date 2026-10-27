"""Standalone VirtualBox full-clone preparer. Never modifies or starts a base VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET


def pairs(text):
    result={}
    for line in text.splitlines():
        if '=' not in line:continue
        key,value=line.split('=',1)
        result[key.strip().strip('"')]=value.strip().strip('"').replace('\\"','"')
    return result


def inventory(text):
    result={}
    for line in text.splitlines():
        match=re.fullmatch(r'"(.*)"\s+\{([0-9a-fA-F-]{36})\}',line.strip())
        if match:
            name=match[1].replace('\\"','"')
            identity=str(uuid.UUID(match[2]))
            if name in result:raise RuntimeError('Duplicate VM display name: '+name)
            result[name]=identity
        elif line.strip():
            raise RuntimeError('Unrecognized VirtualBox inventory line; refusing incomplete discovery.')
    return result


def medium_info(text):
    """Parse documented human-readable showmediuminfo output (including VBox 7.2)."""
    labels = {'UUID': 'UUID', 'Parent UUID': 'ParentUUID', 'Location': 'Location', 'Capacity': 'Capacity'}
    result = {}
    for line in text.splitlines():
        label, separator, value = line.partition(':')
        if separator and label.strip() in labels:
            key = labels[label.strip()]
            if key in result:
                raise RuntimeError('Duplicate medium information field: ' + label.strip())
            result[key] = value.strip()
    if set(result) != set(labels.values()) or not result['Location']:
        raise RuntimeError('Incomplete showmediuminfo output; refusing to guess disk identity or capacity.')
    try:
        uuid.UUID(result['UUID'])
        if result['ParentUUID'] != 'base':
            uuid.UUID(result['ParentUUID'])
    except ValueError as exc:
        raise RuntimeError('Invalid medium UUID in showmediuminfo output') from exc
    if not re.fullmatch(r'[1-9]\d*\s+MBytes', result['Capacity']):
        raise RuntimeError('Unsupported disk capacity units in showmediuminfo: ' + result['Capacity'])
    return result


class VBox:
    def __init__(self, executable=None):
        candidates=[executable,shutil.which('VBoxManage'),shutil.which('VBoxManage.exe')]
        if os.name=='nt':
            candidates += [str(Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Oracle/VirtualBox/VBoxManage.exe')]
        self.executable=next((str(p) for p in candidates if p and Path(p).is_file()),None)
        if not self.executable:raise RuntimeError('VBoxManage not found. Install VirtualBox or use --vboxmanage.')

    def run(self,*args):
        r=subprocess.run([self.executable,*map(str,args)],capture_output=True,text=True,encoding='utf-8',errors='strict')
        if r.returncode:raise RuntimeError('VBoxManage '+str(args[0])+' failed: '+(r.stderr.strip() or r.stdout.strip()))
        return r.stdout

    def all(self):return inventory(self.run('list','vms'))
    def info(self,identity):return pairs(self.run('showvminfo',identity,'--machinereadable'))
    def medium(self,identity):
        # showvminfo supports --machinereadable; showmediuminfo does not.
        result = medium_info(self.run('showmediuminfo','disk',identity))
        if uuid.UUID(result['UUID']) != uuid.UUID(identity):
            raise RuntimeError('VirtualBox returned information for a different disk')
        return result


def config_disk_ids(config):
    tree=ET.parse(config)
    machine=tree.getroot().find('{*}Machine')
    if machine is None:raise RuntimeError('No Machine element in '+str(config))
    controllers=machine.find('{*}StorageControllers')
    # VirtualBox 7 may nest StorageControllers inside Hardware.
    if controllers is None:
        hardware=machine.find('{*}Hardware')
        controllers=hardware.find('{*}StorageControllers') if hardware is not None else None
    if controllers is None:raise RuntimeError('No current storage controller inventory in '+str(config))
    ids=[]
    for controller in controllers:
        for device in controller:
            if device.get('type')!='HardDisk':continue
            image=device.find('{*}Image')
            if image is None:raise RuntimeError('Unrecognized hard disk attachment in '+str(config))
            ids.append(str(uuid.UUID(image.attrib['uuid'].strip('{}'))))
    if not ids:raise RuntimeError('A bootable hard disk is required: '+str(config))
    return ids


def under(path,root):
    try:Path(path).resolve().relative_to(Path(root).resolve());return True
    except ValueError:return False


def fingerprint(info):
    path=Path(info['CfgFile'])
    if not path.is_file():raise RuntimeError('VirtualBox config does not exist: '+str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_plan(manifest,vbox):
    all_vms=vbox.all();targets=[m['clone_name'] for m in manifest['machines']]
    if len(targets)!=len(set(targets)):raise RuntimeError('Duplicate target name in manifest')
    if any(name in all_vms for name in targets):
        raise RuntimeError('A target clone name already exists. Existing VMs are NEVER reused or overwritten.')
    used={m['base'] for m in manifest['machines']};sources={}
    for key in sorted(used):
        matches=[(name,identity) for name,identity in all_vms.items() if name in manifest['bases'][key]]
        if len(matches)!=1:raise RuntimeError('Expected exactly one base for '+key+'; found '+str(len(matches))+'. Check the exact aliases in campus-manifest.json.')
        name,identity=matches[0];info=vbox.info(identity)
        if info.get('VMState')!='poweroff':raise RuntimeError('Base must be shut down (not saved/running): '+name)
        for field,value in info.items():
            match=re.fullmatch(r'nic(\d+)',field)
            if match and int(match[1])>8 and value!='none':
                raise RuntimeError('An enabled adapter above NIC 8 requires manual review: '+name)
        disks=config_disk_ids(info['CfgFile']);capacity=0
        for disk in disks:
            medium=vbox.medium(disk)
            match=re.match(r'(\d+)',medium.get('Capacity',''))
            if not match:raise RuntimeError('Cannot determine full-clone disk capacity for '+name)
            capacity+=int(match[1])*1024*1024
        sources[key]={'name':name,'uuid':identity,'config_sha256':fingerprint(info),
                      'disk_ids':disks,'capacity_bytes':capacity,
                      'hardware_uuid':info.get('hardwareuuid',identity),
                      'mac_addresses':[v.upper() for k,v in info.items() if re.fullmatch(r'macaddress\d+',k) and v]}
    if len({s['uuid'] for s in sources.values()})!=len(sources):raise RuntimeError('Different base roles resolve to the same source VM.')
    needed=sum(sources[m['base']]['capacity_bytes'] for m in manifest['machines'])
    return sources,needed


def validate_manifest(manifest,document):
    prefix=manifest.get('prefix','')
    if not re.fullmatch(r'CXDR-[0-9a-f]{8}',prefix):raise RuntimeError('Invalid package prefix')
    uuid.UUID(manifest['project_id'])
    if document['project_id']!=manifest['project_id']:raise RuntimeError('Project/manifest identity mismatch')
    by_name={m['name']:m for m in manifest['machines']}
    vm_nodes=[n for n in document['topology']['nodes'] if n['node_type']=='virtualbox']
    if len(by_name)!=len(manifest['machines']) or len(vm_nodes)!=len(by_name):raise RuntimeError('Unexpected VM membership')
    for node in vm_nodes:
        machine=by_name[node['name']]
        if not re.fullmatch(re.escape(prefix)+r'-[A-Z0-9-]+',machine['clone_name']):raise RuntimeError('Target outside package namespace')
        if node['properties']['vmname']!=machine['clone_name'] or node['properties'].get('linked_clone') is not False:
            raise RuntimeError('Project may only reference new independent clones')
        if not 1<=machine['adapters']<=8:raise RuntimeError('Unsupported adapter count')
    if document.get('auto_start') is not False:raise RuntimeError('Automatic VM startup must be disabled')


def prepare(directory,vbox,clone=False):
    directory=Path(directory).resolve()
    manifest=json.loads((directory/'campus-manifest.json').read_text(encoding='utf-8'))
    project_files=list(directory.glob('*.gns3'))
    if len(project_files)!=1:raise RuntimeError('Exactly one campus .gns3 file is required')
    document=json.loads(project_files[0].read_text(encoding='utf-8'))
    validate_manifest(manifest,document)
    sources,needed=source_plan(manifest,vbox)
    clone_root=directory/'VirtualBoxVMs'
    if clone_root.exists():raise RuntimeError('Clone folder already exists; refusing to reuse any VM or partial clone.')
    free=shutil.disk_usage(directory).free
    required=int(needed*1.10)
    print(f'New full clones: {len(manifest["machines"])}; conservative disk budget: {required/1024**3:.1f} GiB; available: {free/1024**3:.1f} GiB',flush=True)
    audit={'project_id':manifest['project_id'],'sources':sources,'full_clone':True,'complete':False,
           'required_disk_bytes':required,'clones':[]}
    (directory/'preflight.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    if free<required:raise RuntimeError('Insufficient free disk space for conservative full-clone budget. No VM was cloned.')
    if not clone:
        print('CHECK PASSED. No VM was cloned or started. Details: preflight.json',flush=True)
        return audit
    if (directory/'clone-audit.json').exists():raise RuntimeError('An earlier clone audit exists; review it before retrying.')
    clone_root.mkdir()
    source_disks={d for source in sources.values() for d in source['disk_ids']}
    source_ids={s['uuid'] for s in sources.values()};target_ids=set();target_disks=set()
    hardware_ids={s['hardware_uuid'].lower() for s in sources.values()}
    macs={mac for s in sources.values() for mac in s['mac_addresses']}
    def save():
        (directory/'clone-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        for machine in manifest['machines']:
            source=sources[machine['base']];name=machine['clone_name']
            # Recheck inventory and source state before each expensive copy.
            if name in vbox.all():raise RuntimeError('Target appeared during preparation; will not reuse: '+name)
            if vbox.info(source['uuid']).get('VMState')!='poweroff':raise RuntimeError('Source was started during preparation')
            audit['in_progress']={'name':name,'source_uuid':source['uuid']}
            save()
            print('Full clone -> '+name,flush=True)
            vbox.run('clonevm',source['uuid'],'--name',name,'--basefolder',str(clone_root),'--mode','machine','--register')
            registered=vbox.all()
            if name not in registered:raise RuntimeError('Clone was not registered')
            identity=registered[name]
            if identity in source_ids or identity in target_ids:raise RuntimeError('Clone UUID is not independent')
            info=vbox.info(identity)
            hardware=info.get('hardwareuuid',identity).lower()
            if hardware in hardware_ids:raise RuntimeError('Clone hardware UUID was preserved from another VM')
            audit['in_progress']['uuid']=identity;save()
            if info.get('VMState')!='poweroff' or not under(info['CfgFile'],clone_root/name):raise RuntimeError('Unexpected clone state or config location')
            disk_ids=config_disk_ids(info['CfgFile'])
            if set(disk_ids)&(source_disks|target_disks):raise RuntimeError('Clone references an existing virtual disk')
            for disk in disk_ids:
                medium=vbox.medium(disk)
                parent=medium.get('ParentUUID','').strip('{}').lower()
                if parent not in ('base','00000000-0000-0000-0000-000000000000'):
                    raise RuntimeError('Expected a full clone, found a parent/differencing disk')
                if not under(medium['Location'],clone_root/name):raise RuntimeError('Clone disk is outside its dedicated directory')
            # Every NIC is disconnected before the user opens the GNS3 project.
            # No source modifyvm/startvm/snapshot command is ever issued.
            args=[]
            for port in range(1,9):args += [f'--nic{port}','none']
            vbox.run('modifyvm',identity,*args)
            for port in range(1,machine['adapters']+1):
                vbox.run('modifyvm',identity,f'--nic{port}','intnet',f'--intnet{port}',name+f'-UNCONNECTED-{port}',f'--cableconnected{port}','off',f'--macaddress{port}','auto')
            updated=vbox.info(identity)
            enabled_macs=[updated.get(f'macaddress{port}','').upper() for port in range(1,machine['adapters']+1)]
            if any(not re.fullmatch(r'[0-9A-F]{12}',mac) or mac=='000000000000' for mac in enabled_macs):
                raise RuntimeError('Could not verify generated clone MAC addresses')
            if len(set(enabled_macs))!=len(enabled_macs) or set(enabled_macs)&macs:
                raise RuntimeError('Clone MAC address collision')
            target_ids.add(identity);target_disks.update(disk_ids);hardware_ids.add(hardware);macs.update(enabled_macs)
            audit['clones'].append({'node':machine['name'],'name':name,'uuid':identity,'disk_ids':disk_ids,
                                    'config':info['CfgFile'],'source_uuid':source['uuid'],'state':'poweroff',
                                    'hardware_uuid':hardware,'mac_addresses':enabled_macs})
            audit.pop('in_progress',None)
            save()
        for source in sources.values():
            after=vbox.info(source['uuid'])
            if after.get('VMState')!='poweroff' or fingerprint(after)!=source['config_sha256']:
                raise RuntimeError('A base VM changed during cloning; review before opening GNS3.')
        audit['complete']=True;save()
        print('COMPLETE. All new VMs remain powered off. Open '+project_files[0].name,flush=True)
        return audit
    except BaseException as exc:
        audit['error']=str(exc);save()
        print('Preparation incomplete. Existing/source VMs were not reused. New partial clones retained; inspect clone-audit.json.',file=sys.stderr)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',default=str(Path(__file__).resolve().parent))
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true');mode.add_argument('--clone',action='store_true')
    parser.add_argument('--vboxmanage')
    args=parser.parse_args()
    try:prepare(args.directory,VBox(args.vboxmanage),clone=args.clone)
    except (RuntimeError,OSError,ValueError,KeyError,ET.ParseError) as exc:
        print('STOP: '+str(exc),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
