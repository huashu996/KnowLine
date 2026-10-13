"""Repair the two legacy builder defects in an unregistered, task-owned working PPT.

Preserves source, formula XML, visible geometry, IDs, final targets and review
history. The normal workflow still performs native and visual acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import zipfile
from lxml import etree as ET

sys.path.insert(0,str(Path(__file__).resolve().parent))
from figure_workflow import Workflow, task_lock, read, require, APP
from backend.layout import project_root
from backend.safety import atomic_json

P='http://schemas.openxmlformats.org/presentationml/2006/main'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
NS={'p':P,'a':A}


def repair(workflow):
    job=workflow.live()
    require(not (workflow.output/'result.json').exists(),'figure_result_already_published')
    path=workflow.owned(workflow.working)
    require(workflow.relative(path) not in {a['path'] for a in (job.get('result') or {}).get('artifacts',[])},'figure_registered_target_changed')
    plan=read(workflow.owned(workflow.output/'figure-plan.json'))
    require(plan.get('source_image_sha256')==workflow.context['figure_selection']['image']['sha256'],'artifact_hash_mismatch')
    items={o['name']:o for o in plan['objects']}
    with zipfile.ZipFile(path) as package:
        entries=package.infolist()
        data={entry.filename:package.read(entry.filename) for entry in entries}
    root=ET.fromstring(data['ppt/slides/slide1.xml'])
    converted=[]
    for shape in root.findall('.//p:cxnSp',NS):
        name=shape.find('p:nvCxnSpPr/p:cNvPr',NS).get('name')
        if shape.find('p:spPr/a:custGeom',NS) is None:continue
        require(items.get(name,{}).get('native_bezier'),'figure_plan_geometry_invalid')
        shape.tag='{'+P+'}sp'
        nonvisual=shape.find('p:nvCxnSpPr',NS);nonvisual.tag='{'+P+'}nvSpPr'
        properties=nonvisual.find('p:cNvCxnSpPr',NS);properties.tag='{'+P+'}cNvSpPr'
        for binding in list(properties):properties.remove(binding)
        converted.append(name)
    rank={'noFill':0,'solidFill':0,'gradFill':0,'pattFill':0,'prstDash':1,'custDash':1,'round':2,'bevel':2,'miter':2,'headEnd':3,'tailEnd':4,'extLst':5}
    reordered=0
    for line in root.findall('.//a:ln',NS):
        children=list(line)
        ordered=sorted(children,key=lambda node:rank.get(ET.QName(node).localname,-1))
        if children!=ordered:
            for node in children:line.remove(node)
            for node in ordered:line.append(node)
            reordered+=1
    data['ppt/slides/slide1.xml']=ET.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True)
    staging=workflow.owned(path.with_suffix('.repairing.pptx'),exists=False)
    try:
        with zipfile.ZipFile(staging,'w') as package:
            for entry in entries:package.writestr(entry,data[entry.filename])
        from backend.document_quality import validate
        validate(staging,'powerpoint')
        os.replace(staging,path)
    finally:
        if staging.exists():staging.unlink()
    manifest_path=workflow.owned(workflow.output/'native-audit-input.json')
    manifest=read(manifest_path)
    manifest['expected_connector_count']=sum(o['kind']=='connector' and not o.get('native_bezier') for o in items.values())
    atomic_json(manifest_path,manifest)
    preparation=workflow.output/'native-text-preparation-input.json'
    atomic_json(preparation,dict(mode='Office',equations=[],text_objects=[dict(name=o['name'],resize_frame=o['kind']=='text') for o in items.values() if 'text' in o and o['kind']!='formula']))
    return dict(converted_curve_names=converted,reordered_lines=reordered,
                presentation=workflow.relative(path),preparation_manifest=workflow.relative(preparation))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('context');args=parser.parse_args()
    workflow=Workflow(project_root(APP),args.context)
    with task_lock(workflow.output/'figure-workflow.lock'):
        result=repair(workflow)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
