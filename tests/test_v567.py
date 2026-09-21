import importlib.util
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import torch

spec=importlib.util.spec_from_file_location('v567',os.environ['DOGMA_V567_MODULE'])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
torch.set_num_threads(2)


def item(x0=10,y0=10,x1=30,y1=30,h=64,w=64,source='test'):
    mask=torch.zeros(h,w,dtype=torch.bool);mask[y0:y1,x0:x1]=True
    return dict(mask=mask,score=.8,source=source)


def bundle(items,cat='buildings',accepted=()):
    return dict(category=cat,shape=(64,64),items=items,accepted=list(accepted),notes=[])


def test_planner_deduplicates_families_without_inventing_categories():
    result=m.DOGMASemanticPlanV567().build('1. buildings\n2. cars\n3. buses\n4. people\n5. fence')
    assert result[1::3]==('buildings','vehicles','people','fence','none')
    assert '4 visible categories' in result[0]


def test_global_and_local_search_recover_missing_building(monkeypatch):
    calls=[]
    def detect(model,clip,image,query,threshold,max_instances):
        h,w=image.shape[1:3];calls.append((h,w,query))
        if h==64:return torch.zeros(0,h,w),[[]]
        mask=torch.zeros(1,h,w);mask[:,10:30,10:30]=1
        return mask,[[dict(x=10,y=10,width=20,height=20,score=.3)]]
    monkeypatch.setattr(m.DOGMASAMSearchV567,'_detect',staticmethod(detect))
    search=m.DOGMASAMSearchV567();image=torch.rand(1,64,64,3)
    primary,_=search.search(image,None,None,'buildings')
    review,_=m.DOGMAInstanceReviewV567().review([primary],[])
    retry,_=search.search(image,None,None,'buildings','local_recovery',previous=review)
    assert not primary['items'] and len(retry['items'])==4
    reviewed,_=m.DOGMAInstanceReviewV567().review([retry],['PASS: building']*4)
    masks,report=m.DOGMAFinalMasksV567().finish(reviewed)
    assert len(masks)==4 and masks.any() and len(calls)==6


def test_one_bad_instance_does_not_erase_other_buildings():
    data=bundle([item(),item(35,10,55,30)])
    review,_=m.DOGMAInstanceReviewV567().review([data],['PASS. Building facade.','FAIL: road'])
    masks,_=m.DOGMAFinalMasksV567().finish(review)
    assert len(masks)==1 and torch.equal(masks[0].bool(),data['items'][0]['mask'])


def test_recovery_keeps_previously_approved_instances(monkeypatch):
    data=bundle([item()]);prior,_=m.DOGMAInstanceReviewV567().review([data],['PASS'])
    monkeypatch.setattr(m.DOGMASAMSearchV567,'_detect',staticmethod(lambda a,b,img,*rest:(torch.zeros(0,*img.shape[1:3]),[[]])))
    searched,_=m.DOGMASAMSearchV567().search(torch.zeros(1,64,64,3),None,None,'buildings','local_recovery',previous=prior)
    review,_=m.DOGMAInstanceReviewV567().review([searched],[])
    assert len(m.DOGMAFinalMasksV567().finish(review)[0])==1


def test_failed_visible_category_is_not_reported_as_successful_empty_crop():
    data=dict(category='buildings',shape=(64,64),accepted=[],notes=['both searches failed'])
    with pytest.raises(ValueError,match='global AND local recovery'):
        m.DOGMAFinalMasksV567().finish(data)
    data['category']='none'
    assert m.DOGMAFinalMasksV567().finish(data)[0].shape==(0,64,64)


def test_misaligned_reviews_raise_instead_of_shifting_answers():
    with pytest.raises(ValueError,match='audit answers'):
        m.DOGMAInstanceReviewV567().review([bundle([item(),item()])],['PASS'])


@pytest.mark.parametrize('value,expected',[
    ('PASS',True),('PASS. Partial building.',True),('**PASS**',True),('FAIL',False),
    ('PASS\nFAIL',False),('probably PASS',False),('',False),('<think>maybe</think>PASS',True)])
def test_verdict_parser(value,expected):
    assert m.verdict(value)==expected


def test_cleanup_uses_same_score_as_detector_and_keeps_holes():
    raw=item()['mask'].float()[None];raw[:,15:18,15:18]=0;raw[:,1,1]=1
    items,notes=m.clean_instances(raw,[[dict(x=8,y=8,width=25,height=25,score=.3)]],64,64,.25,'buildings','raw')
    assert len(items)==1 and not items[0]['mask'][1,1] and not items[0]['mask'][16,16]


def test_fragmented_frame_mask_rejected_without_growth():
    mask=torch.zeros(1,64,64);mask[:,::2,::2]=1
    items,notes=m.clean_instances(mask,[[dict(x=0,y=0,width=64,height=64,score=.9)]],64,64,.25,'cars','raw')
    assert not items and 'fragmented' in notes[0]


def test_dedup_keeps_separate_objects_and_removes_contained_retries():
    large=item();small=item(12,12,20,20);other=item(40,10,60,30)
    assert len(m.deduplicate([small,large,other,large]))==2
    assert m.deduplicate([small],already=[large])==[]


def test_local_windows_cover_image_and_have_overlap():
    canvas=np.zeros((79,101),int)
    for x0,y0,x1,y1 in m.local_windows(*canvas.shape):canvas[y0:y1,x0:x1]+=1
    assert canvas.min()==1 and canvas.max()==4


def test_semantic_ownership_protects_people_and_cars_from_facades():
    car=item(10,35,40,55)['mask'][None].float()
    person=item(20,25,26,45)['mask'][None].float()
    building=item(0,0,60,45)['mask'][None].float()
    road=item(0,40,64,64)['mask'][None].float()
    masks=[road,building,car,person,torch.zeros(0,64,64)]
    cats=['road','buildings','vehicles','people','none'];kwargs={}
    for i,(mask,cat) in enumerate(zip(masks,cats),1):kwargs.update({f'mask_{i}':mask,f'category_{i}':cat})
    result=m.DOGMAMaskOwnershipV567().resolve(**kwargs)
    unions=[x.any(0) for x in result[:4]]
    for i,a in enumerate(unions):
        for b in unions[i+1:]:assert not (a&b).any()
    assert torch.equal(result[3],person)
    assert torch.equal(torch.stack(unions).any(0),torch.cat(masks[:4]).any(0))


def test_audit_sheet_has_per_instance_prompt_without_target_class_veto():
    sheets,prompts=m.DOGMAInstanceAuditViewV567().build(torch.rand(1,64,64,3),bundle([item(),item(40,10,60,30)]),256)
    assert len(sheets)==len(prompts)==2
    assert all('ONE candidate' in p and 'Partial buildings' in p for p in prompts)
    assert all(torch.isfinite(s).all() and s.shape[-1]==3 for s in sheets)


def test_inactive_slots_do_not_request_caption_or_denoise():
    zero=torch.zeros(0,64,64);image=torch.rand(1,64,64,3)
    imagegate=m.DOGMALazyImageV567();textgate=m.DOGMALazyTextV567();auditgate=m.DOGMAAuditTextV567()
    assert imagegate.check_lazy_status(image,zero)==[]
    assert torch.equal(imagegate.choose(image,zero)[0],image)
    assert textgate.check_lazy_status(zero)==[]
    assert auditgate.check_lazy_status([bundle([])])==[]
    assert auditgate.choose([bundle([])])==([],)
    assert auditgate.check_lazy_status([bundle([item()])],(None,))==['audit_text']
    assert auditgate.check_lazy_status([bundle([item()])],['PASS'])==[]
    nonzero=torch.ones(1,64,64)
    assert imagegate.check_lazy_status(image,nonzero)==['result']
    assert textgate.check_lazy_status(nonzero)==['text']


def test_bundle_cleanup_keeps_list_order_without_model_operations():
    tiles=[torch.rand(1,32,32,3),torch.rand(1,32,32,3)]
    data=m.DOGMATileBundleV567().pack(tiles,['first','second'],['one','two'])[0]
    out=m.DOGMATileUnpackV567().unpack(data)
    assert out[0] is tiles and out[1]==['first','second']
    with pytest.raises(ValueError):m.DOGMATileBundleV567().pack(tiles,['one'],['one'])


@pytest.mark.parametrize('multi',[False,True])
def test_core_sam_adapter_requests_many_instances_and_raw_masks(monkeypatch,multi):
    captured={};cond=torch.zeros(1,2,3);mask=torch.ones(1,2)
    metadata={'attention_mask':mask}
    if multi:metadata['sam3_multi_cond']=[dict(cond=cond,attention_mask=mask,max_detections=1)]
    nodes=types.ModuleType('nodes')
    class Encoder:
        def encode(self,clip,text):return ([[cond,metadata]],)
    nodes.CLIPTextEncode=Encoder
    core=types.ModuleType('comfy_extras.nodes_sam3')
    class Detect:
        @classmethod
        def execute(cls,**kwargs):captured.update(kwargs);return ('masks','boxes')
    core.SAM3_Detect=Detect
    monkeypatch.setitem(sys.modules,'nodes',nodes)
    monkeypatch.setitem(sys.modules,'comfy_extras',types.ModuleType('comfy_extras'))
    monkeypatch.setitem(sys.modules,'comfy_extras.nodes_sam3',core)
    assert m.DOGMASAMSearchV567._detect(None,None,torch.zeros(1,64,64,3),'building',.25,64)==('masks','boxes')
    assert captured['refine_iterations']==0 and captured['individual_masks'] is True
    assert captured['conditioning'][0][1]['sam3_multi_cond'][0]['max_detections']==64
    if multi:assert metadata['sam3_multi_cond'][0]['max_detections']==1
