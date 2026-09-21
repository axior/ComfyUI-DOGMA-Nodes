import importlib.util
import os
from pathlib import Path
import numpy as np
import pytest
import torch

spec=importlib.util.spec_from_file_location('v566',os.environ.get('DOGMA_V566_MODULE',str(Path(__file__).parents[1]/'dogma_semantic_v566.py')))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_vehicle_mask_cannot_select_sky_outside_detection():
    image=torch.zeros(1,96,128,3)
    mask=torch.zeros(1,96,128);mask[0,50:75,40:90]=1
    mask[0,2:20,2:120]=1;mask[0,45,43]=1
    boxes=[[dict(x=35,y=40,width=60,height=40,score=.9)]]
    clean,_=m.DOGMASAMInstanceGuardV566().clean(mask,boxes,image,'vehicles')
    assert clean.shape[0]==1
    assert clean[0,50:75,40:90].all()
    assert not clean[0,:40].any()
    assert clean[0,45,43]==0

def test_holes_and_substantial_occluded_parts_are_preserved():
    mask=torch.zeros(1,80,80);mask[0,10:40,10:35]=1;mask[0,10:40,40:65]=1
    mask[0,20:25,15:20]=0
    clean,_=m.DOGMASAMInstanceGuardV566().clean(mask,[[dict(x=5,y=5,width=65,height=40,score=.9)]],torch.zeros(1,80,80,3),'car')
    assert torch.equal(clean,mask)

@pytest.mark.parametrize('boxes', [[],[[dict(x=0,y=0,width=20,height=20,score=.2)]],[[dict(x=0,y=0,width=-2,height=20,score=.9)]]])
def test_unreliable_boxes_are_skipped(boxes):
    clean,_=m.DOGMASAMInstanceGuardV566().clean(torch.ones(1,32,32),boxes,torch.zeros(1,32,32,3),'car')
    assert not clean.any()

def test_invalid_mask_and_batch_are_rejected():
    box=[[dict(x=0,y=0,width=32,height=32,score=.9)]]
    for mask,image in [(torch.full((1,32,32),float('nan')),torch.zeros(1,32,32,3)),(torch.ones(1,32,32),torch.zeros(2,32,32,3))]:
        out,_=m.DOGMASAMInstanceGuardV566().clean(mask,box,image,'car');assert out.numel()==0

@pytest.mark.parametrize('decision',['FAIL','PASS\nFAIL','probably PASS','','PASS, but the sky is selected'])
def test_audit_cannot_silently_accept_malformed_or_failed_verdict(decision):
    mask=torch.ones(1,32,32)
    out,_=m.DOGMAMaskAuditGateV566().gate(mask,decision,'vehicles','geometry')
    assert out.sum()==0

def test_valid_audit_is_pixel_identical():
    mask=torch.rand(2,32,32)
    out,_=m.DOGMAMaskAuditGateV566().gate(mask,' PASS ','car','geometry')
    assert torch.equal(out,mask)

def test_dual_mask_does_not_fill_holes_or_expand_ownership():
    mask=torch.zeros(1,96,96);mask[:,20:70,20:70]=1;mask[:,40:50,40:50]=0
    generation,blend,*_=m.DOGMADualMaskV566().build(mask,'OBJECT')
    assert torch.equal(blend,mask)
    assert generation.sum()>blend.sum()

def test_crop_prompt_uses_actual_caption_and_declarative_context():
    caption='A cream sedan occupies the lower right corner. Its dark windows reflect a pale sky.'
    out=m.DOGMAChunkPromptV566().build(caption,'Italy, 1970s. Preserve all objects.')[0]
    assert out.startswith(caption) and 'Italy, 1970s.' in out
    assert 'Preserve' not in out and 'Refine' not in out
    with pytest.raises(ValueError):m.DOGMAChunkPromptV566().build('Preserve all objects.','Italy.')

def test_masked_denoise_encodes_original_once_without_edit_conditioning():
    class VAE:
        def __init__(self):self.calls=[]
        def encode_tiled(self,pixels,**kw):self.calls.append(pixels.clone());return torch.ones(1,128,4,4)
    vae=VAE();pixels=torch.rand(1,64,64,3);positive=[['pos',{}]];negative=[['neg',{}]]
    pos,neg,lat=m.DOGMAMaskedDenoiseLatentV566().encode(positive,negative,vae,pixels,torch.ones(1,64,64))
    assert pos is positive and neg is negative and len(vae.calls)==1
    assert torch.equal(vae.calls[0],pixels)
    assert set(lat)=={'samples','noise_mask'}
    assert 'concat_latent_image' not in pos[0][1]

def composite(base,patch,mask,strength=.15):
    h,w=base.shape[1:3]
    meta=dict(x=0,y=0,width=w,height=h,noop=False)
    return m.DOGMASoftStitchV566().stitch_regions([base],[patch],[torch.ones_like(mask)],[mask],[meta],['car'],['OBJECT'],[strength])[0]

def test_feather_has_zero_edge_and_no_changed_pixels_outside_mask():
    base=torch.rand(1,96,96,3)*.3+.3;patch=base+.1
    mask=torch.zeros(1,96,96);mask[:,20:80,20:80]=1
    out=composite(base,patch,mask,1)
    assert torch.equal(out[:,mask[0]==0],base[:,mask[0]==0])
    assert torch.equal(out[:,20,20:80],base[:,20,20:80])
    assert torch.allclose(out[:,45:55,45:55],patch[:,45:55,45:55],atol=1e-6)

def test_exposure_offset_is_reduced_but_detail_remains():
    base=torch.full((1,96,96,3),.4);patch=base+.2
    patch[:,::2,::2]+=.05;patch[:,1::2,1::2]-=.05
    out=composite(base,patch,torch.ones(1,96,96))
    region=out[:,30:60,30:60]
    assert abs(float(region.mean())-.43)<.005
    assert float(region.std())>.015

def test_empty_mask_and_noop_leave_master_exactly_unchanged():
    base=torch.rand(1,32,32,3)
    assert torch.equal(composite(base,1-base,torch.zeros(1,32,32)),base)
    out,_=m.DOGMASoftStitchV566().stitch_regions([base],[1-base],[torch.ones(1,32,32)],[torch.ones(1,32,32)],[{'noop':True}],['none'],['OBJECT'])
    assert torch.equal(out,base)

def test_audit_view_empty_and_nonempty_masks():
    view=m.DOGMAMaskAuditViewV566()
    for mask in [torch.zeros(0,96,128),torch.ones(2,96,128)]:
        sheet,prompt=view.build(torch.rand(1,96,128,3),mask,'vehicles',256)
        assert sheet.shape==(1,192,256,3) and torch.isfinite(sheet).all()
        assert 'vehicles' in prompt and 'PASS or FAIL' in prompt
