"""Rehearse a production specimen's end/ejection path after only its first layer.

Actual layer height is not represented as a full-height object. The entire end
path is copied from a separately validated full-height artifact. This is a
supervised motion/ooze trial, not proof that a one-layer object can be ejected.
"""
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4
import zipfile

from device_bridges.printer_fleet.providers.bambu_autoejection import BambuGcodeAutoejectionPatcher


def first_layer_only(full):
    layers=list(re.finditer(r'^; CHANGE_LAYER\s*$', full, re.M))
    if len(layers)<2: raise ValueError('A full multi-layer specimen is required')
    end=full.index('; close powerlost recovery', layers[-1].start())
    text=full[:layers[1].start()]+full[end:]
    # Keep all motion/extrusion/cleanup commands verbatim. Only UI metadata changes.
    text=re.sub(r'^; total layer number:.*$', '; total layer number: 1', text, flags=re.M)
    return text


def prepare(source, root):
    source=Path(source).resolve()
    trial='x2d-303030-first-layer-path-'+uuid4().hex[:8]
    folder=Path(root).resolve()/'artifacts/bambu_cleanup_trials'/trial
    folder.mkdir(parents=True,exist_ok=False)
    patched=BambuGcodeAutoejectionPatcher(output_dir=folder/'validated-full-path').patch_artifact(source)
    if not patched.get('ok'): raise ValueError(patched.get('blockers'))
    full_path=Path(patched['patched_artifact_path'])
    plate='Metadata/plate_1.gcode'
    with zipfile.ZipFile(full_path) as z:
        full=z.read(plate).decode()
        text=first_layer_only(full)
        assert len(re.findall(r'^; CHANGE_LAYER\s*$',text,re.M))==1
        assert text.split('; MACHINE_END_GCODE_START',1)[1]==full.split('; MACHINE_END_GCODE_START',1)[1]
        assert text.count('; atr.bambu.autoejection.v1')==1
        output=folder/(trial+'.autoeject.gcode.3mf')
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as out:
            for info in z.infolist():
                content=z.read(info.filename)
                if info.filename==plate: content=text.encode()
                if info.filename==plate+'.md5': content=hashlib.md5(text.encode()).hexdigest().encode()
                out.writestr(info,content)
    with zipfile.ZipFile(output) as z:
        assert z.read(plate+'.md5').decode().strip()==hashlib.md5(z.read(plate)).hexdigest()
    report={'ok':True,'schema':'x2d.first_layer_path_rehearsal.v1',
        'source':str(source),'artifact':str(output),'trial_id':trial,
        'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'printed_layers':1,'actual_print_height_mm':0.2,
        'planned_specimen_size_mm':[30,30,30],
        'ejection_path':'verbatim_validated_full_height_path',
        'full_path_validation':patched['post_write_validation'],
        'one_layer_detachment_verified':False,'manual_removal_required':True,
        'nozzle_trial_temperature_c':140,'bed_wait_c':40,'will_publish':False}
    (folder/'report.json').write_text(json.dumps(report,indent=2))
    (folder/'end-sequence.gcode').write_text(text.split('; MACHINE_END_GCODE_START',1)[1])
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('source')
    args=parser.parse_args()
    print(json.dumps(prepare(args.source,Path(__file__).resolve().parents[1]),indent=2))
