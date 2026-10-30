#!/usr/bin/env python3
"""Offline evidence reader and controlled transport-failure fixture."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def rows(p):return [json.loads(x) for x in (ROOT/p).read_text(encoding='utf-8').splitlines() if x.strip()]
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--case',required=True);ap.add_argument('--source',required=True)
ap.add_argument('--scenario',choices=['success','transient_timeout','permanent_timeout','empty','malformed'],default='success')
ap.add_argument('--attempt',type=int,default=1)
a=ap.parse_args();cases={x['case_id']:x for x in rows('cases/cases.jsonl')};sources={x['source_id']:x for x in rows('evidence/sources.jsonl')}
def out(x):print(json.dumps(x,ensure_ascii=False))
if a.case not in cases or a.source not in cases[a.case]['allowed_source_ids']:
    out({'ok':False,'error':{'code':'SOURCE_NOT_ALLOWED','retryable':False}});sys.exit(2)
if a.scenario=='permanent_timeout' or (a.scenario=='transient_timeout' and a.attempt<=2):
    out({'ok':False,'fixture':True,'error':{'code':'TIMEOUT','retryable':True},'attempt':a.attempt});sys.exit(3)
if a.scenario=='malformed':print('{ deliberately invalid JSON');sys.exit(4)
if a.scenario=='empty':out({'ok':True,'fixture':True,'source':None});sys.exit(0)
s=sources[a.source]
out({'ok':True,'source':s,'locators':[{'locator':'L'+str(i),'text':v} for i,v in enumerate(s['body'].splitlines(),1)]})
