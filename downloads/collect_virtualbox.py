"""Read-only VirtualBox inventory exporter; standalone, standard-library only."""
import argparse
import csv
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET


def parse_inventory(text):
    rows=[];seen=set()
    for line in text.splitlines():
        if not line.strip():continue
        match=re.fullmatch(r'"(.*)"\s+\{([0-9a-fA-F-]{36})\}',line.strip())
        if not match:raise RuntimeError('Cannot parse the complete VirtualBox VM list; no entries will be silently skipped.')
        identity=str(uuid.UUID(match[2]))
        if identity in seen:raise RuntimeError('Duplicate VM UUID in VirtualBox inventory')
        seen.add(identity)
        rows.append({'name':match[1].replace('\\"','"'),'uuid':identity})
    return rows


def machine_fields(text):
    result={}
    for line in text.splitlines():
        if '=' in line:
            key,value=line.split('=',1)
            result[key.strip().strip('"')]=value.strip().strip('"').replace('\\"','"')
    return result


class ReadOnlyVBox:
    def __init__(self,executable=None):
        candidates=[executable,shutil.which('VBoxManage'),shutil.which('VBoxManage.exe')]
        if os.name=='nt':candidates.append(str(Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Oracle/VirtualBox/VBoxManage.exe'))
        self.executable=next((str(p) for p in candidates if p and Path(p).is_file()),None)
        if not self.executable:raise RuntimeError('VBoxManage not found. Use --vboxmanage with its installed path.')

    def run(self,*args):
        if args==('list','vms'):
            pass
        elif len(args)==3 and args[0]=='showvminfo' and args[2]=='--machinereadable':
            uuid.UUID(args[1])
        elif len(args)==3 and args[:2]==('showmediuminfo','disk'):
            uuid.UUID(args[2])
        else:
            raise ValueError('This tool permits only list vms, showvminfo and showmediuminfo.')
        result=subprocess.run([self.executable,*args],capture_output=True,text=True,encoding='utf-8',timeout=30)
        if result.returncode:
            # Do not dump native output: it may contain private host paths/settings.
            raise RuntimeError(args[0]+' failed (exit '+str(result.returncode)+')')
        return result.stdout


def disk_ids(config):
    machine=ET.parse(config).getroot().find('{*}Machine')
    if machine is None:raise ValueError('Missing current Machine settings')
    controllers=machine.find('{*}StorageControllers')
    if controllers is None:
        hardware=machine.find('{*}Hardware')
        controllers=hardware.find('{*}StorageControllers') if hardware is not None else None
    if controllers is None:return []
    result=[]
    for controller in controllers:
        for device in controller:
            if device.get('type')=='HardDisk':
                image=device.find('{*}Image')
                if image is None:raise ValueError('Unknown hard disk attachment')
                result.append(str(uuid.UUID(image.attrib['uuid'].strip('{}'))))
    return result


def medium_fields(text,identity):
    allowed={'UUID':'uuid','Parent UUID':'parent_uuid','Storage format':'format',
             'Format variant':'variant','Capacity':'capacity','Size on disk':'size_on_disk'}
    result={}
    for line in text.splitlines():
        label,separator,value=line.partition(':')
        if separator and label.strip() in allowed:result[allowed[label.strip()]]=value.strip()
    if str(uuid.UUID(result['uuid']))!=identity:raise ValueError('Disk identity mismatch')
    parent=result['parent_uuid'].strip('{}')
    result['parent_uuid']=None if parent in ('base','00000000-0000-0000-0000-000000000000') else str(uuid.UUID(parent))
    result['relationship']='parent_dependent' if result['parent_uuid'] else 'standalone_disk'
    return result


def collect(vbox):
    vms=parse_inventory(vbox.run('list','vms'));cache={}
    def disk(identity):
        if identity not in cache:cache[identity]=medium_fields(vbox.run('showmediuminfo','disk',identity),identity)
        return dict(cache[identity])
    for index,vm in enumerate(vms,1):
        print(f'Inspecting {index}/{len(vms)}: '+vm['name'],flush=True)
        vm.update({'state':'unknown','inspection_status':'complete','issues':[],'disks':[]})
        try:
            info=machine_fields(vbox.run('showvminfo',vm['uuid'],'--machinereadable'))
            vm.update({'state':info.get('VMState','unknown'),'memory_mb':info.get('memory',''),
                       'cpus':info.get('cpus',''),'guest_os_type':info.get('ostype',''),
                       'network_adapters':[{'slot':int(key[3:]),'attachment':value,
                         'cable_connected':info.get('cableconnected'+key[3:],'unknown')}
                         for key,value in info.items() if re.fullmatch(r'nic\d+',key) and value!='none']})
            if 'CfgFile' not in info:raise ValueError('Missing local VM configuration location')
            for identity in disk_ids(info['CfgFile']):
                item={'uuid':identity}
                try:
                    item=disk(identity);current=item;seen={identity};chain=[]
                    while current['parent_uuid']:
                        parent=current['parent_uuid']
                        if parent in seen or len(seen)>64:raise ValueError('Cyclic or excessive disk parent chain')
                        seen.add(parent);chain.append(parent);current=disk(parent)
                    item.update(parent_chain=chain,parent_chain_status='readable')
                except (RuntimeError,ValueError,KeyError,OSError,subprocess.TimeoutExpired):
                    item['parent_chain_status']='unreadable'
                    vm['issues'].append('One disk or its parent chain could not be inspected')
                vm['disks'].append(item)
        except (RuntimeError,ValueError,KeyError,OSError,ET.ParseError,subprocess.TimeoutExpired):
            vm['issues'].append('VM metadata/configuration could not be completely inspected')
        if vm['issues']:vm['inspection_status']='partial'
    return {'schema_version':1,'collected_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'total_vms':len(vms),'partial_vms':sum(v['inspection_status']!='complete' for v in vms),
            'read_only':True,'vms':vms,
            'notes':['No VM was cloned, started, stopped, modified, registered or deleted.',
                     'A standalone disk may be an original or a full clone; its history cannot be inferred.',
                     'This list does not prove a VM is unused by another GNS3 project.',
                     'No credentials, full host paths, disk contents or guest files are exported.']}


def csv_cell(value):
    text=str(value)
    return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text


def export(report,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    (directory/'vm-inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=[f'VirtualBox VM inventory: {report["total_vms"]} registered; {report["partial_vms"]} partially inspected',
           'Read-only scan. VM history/original-vs-full-clone and GNS3 project usage are not automatically known.','']
    with (directory/'vm-list.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.writer(stream);writer.writerow(['name','uuid','state','memory_mb','guest_os_type','disk_relationship','inspection_status'])
        for vm in report['vms']:
            relation=', '.join(sorted({d.get('relationship','unknown') for d in vm['disks']})) or 'no readable disk'
            values=[vm['name'],vm['uuid'],vm['state'],vm.get('memory_mb',''),vm.get('guest_os_type',''),relation,vm['inspection_status']]
            writer.writerow([csv_cell(v) for v in values])
            lines.append(f'{vm["name"]} | {vm["uuid"]} | {vm["state"]} | RAM {vm.get("memory_mb","?")} MB | {relation} | {vm["inspection_status"]}')
    (directory/'vm-list.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    return directory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vboxmanage');parser.add_argument('--output-dir')
    args=parser.parse_args()
    output=args.output_dir or str(Path(__file__).resolve().parent/('vm-inventory-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]))
    try:
        report=collect(ReadOnlyVBox(args.vboxmanage));directory=export(report,output)
        print('\nDONE: '+str(directory.resolve()),flush=True)
        print('Share vm-inventory.json (preferred) or vm-list.txt. No VM settings changed.',flush=True)
        return 0
    except (RuntimeError,ValueError,OSError,subprocess.TimeoutExpired) as exc:
        print('STOP: '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
