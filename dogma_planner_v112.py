"""Bounded category inventory and conservative recovery of malformed VLM output."""
import copy,json,re,sys

def node(name):
    import nodes
    return nodes.NODE_CLASS_MAPPINGS[name]

def legacy():return sys.modules[node('DOGMAProposeCategoriesV111').__module__]

PROMPT = '''Identify distinct visible object/surface CATEGORIES in this photograph, not individual instances.
Write at most EIGHT short lines. Each category occurs ONCE even if many objects of that kind are visible.
Each line: category | concrete SAM target noun | visible location (3-8 words)
Use simple English nouns, no landmark names. Survey the entire frame before answering.
Only include categories actually visible. Do not fill a quota or infer absent objects.
No JSON, numbering, prose, camera style or historical context. If none are identifiable, output NONE.
Stop immediately after the last unique category.'''
RETRY = '''Look again at the whole photograph. Give a SHORT inventory of DISTINCT object/surface TYPES, never one line per individual object. Do not repeat a type.
Maximum eight lines: category | target noun | visible location
Only visible types, no guessed objects or fixed quota. No JSON or explanation. NONE if no identifiable type. Stop after the inventory.'''

def read_rows(text,presence=False):
    """No JSON repair guesses: accept complete objects or complete delimited lines only.
    Bound bytes/records; nested query arrays must never be mistaken for the outer array.
    """
    text=str(text)[:65536]
    text=re.sub(r'<think>.*?</think>','',text,flags=re.S|re.I)
    if '<think>' in text.lower():text=text[:text.lower().index('<think>')]
    text=re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$','',text.strip(),flags=re.I)
    rows=[];warnings=[]
    if text.strip().upper() in ('NONE','[]','NO CATEGORIES'):return [],[]
    # Extract only the first outer JSON payload, never its last nested closing bracket.
    start=text.find('[')
    if start>=0:
        try:
            value,end=json.JSONDecoder().raw_decode(text[start:])
            if isinstance(value,list):return value[:128],([] if len(value)<=128 else ['record limit reached'])
        except (ValueError,RecursionError):pass
        warnings.append('incomplete/malformed JSON: complete objects recovered only')
    if start>=0 or text.lstrip().startswith('{'):
        depth=0;quoted=False;escaped=False;begin=None
        for i,char in enumerate(text):
            if quoted:
                if escaped:escaped=False
                elif char=='\\':escaped=True
                elif char=='"':quoted=False
                continue
            if char=='"':quoted=True
            elif char=='{':
                if depth==0:begin=i
                depth+=1
            elif char=='}' and depth:
                depth-=1
                if depth==0 and begin is not None:
                    try:row=json.loads(text[begin:i+1])
                    except (ValueError,RecursionError):continue
                    if isinstance(row,dict):rows.append(row)
                    if len(rows)>=128:break
        return rows,warnings or ['JSON object records recovered']
    for line in text.splitlines()[:128]:
        line=re.sub(r'^\s*(?:[-*]|\d+[.)])\s*','',line).strip()
        if not line or line.startswith('DOGMA_STATUS:'):continue
        fields=[f.strip() for f in line.split('|')]
        if len(fields)!=3:
            warnings.append('incomplete/unrecognized line ignored');continue
        a,b,evidence=fields
        if presence:
            if not re.fullmatch(r'[1-8]',a) or b.lower() not in ('present','absent','uncertain') or not evidence:
                warnings.append('invalid presence row ignored');continue
            rows.append(dict(id=int(a),verdict=b.lower(),evidence=evidence))
        else:
            if not re.fullmatch(r'[A-Za-z][A-Za-z -]{0,59}',a) or not b or not evidence:
                warnings.append('invalid category row ignored');continue
            rows.append(dict(category=a,queries=[b],evidence=evidence))
    if not rows and not warnings:warnings.append('empty or unreadable inventory')
    return rows,list(dict.fromkeys(warnings))

def inventory(text):
    rows,warnings=read_rows(text);old=legacy();base=old.module('DOGMASAMSearchV567')
    unique={};duplicates=0;invalid=0
    for row in rows:
        if not isinstance(row,dict):invalid+=1;continue
        category=base.canonical(old.clean_phrase(row.get('category','')))
        evidence=row.get('evidence','')
        if base.inactive(category) or not isinstance(evidence,str) or not evidence.strip():invalid+=1;continue
        qs=row.get('queries',[])
        if not isinstance(qs,list):qs=[]
        queries=old.target_queries(category,[old.clean_phrase(q) for q in qs if isinstance(q,str) and old.clean_phrase(q)])
        if category in unique:duplicates+=1;continue
        unique[category]=dict(category=category,queries=queries,evidence=evidence.strip()[:180])
    if duplicates:warnings.append(f'{duplicates} repeated category records collapsed')
    if invalid:warnings.append(f'{invalid} incomplete records ignored')
    return list(unique.values())[:8],list(dict.fromkeys(warnings))

class DOGMABoundedPlannerV112:
    @classmethod
    def INPUT_TYPES(cls):
        source=copy.deepcopy(node('ModernVLM').INPUT_TYPES())
        source['required']['max_new_tokens']=('INT',{'default':320,'min':64,'max':320})
        source['required']['prompt']=('STRING',{'multiline':True,'default':PROMPT})
        source['required']['image']=('IMAGE',)
        source['optional']={k:v for k,v in source.get('optional',{}).items() if k in ('system_prompt','attention_mode','enable_thinking','unload_after','stream_output')}
        return source
    RETURN_TYPES=('STRING','STRING');RETURN_NAMES=('normalized_inventory','planner_diagnostics')
    FUNCTION='run';CATEGORY='DOGMA/v1.0.12'
    def run(self,image,prompt=PROMPT,max_new_tokens=320,**settings):
        from comfy.model_management import throw_exception_if_processing_interrupted
        worker=node('ModernVLM')()
        settings.update(unload_after=False,enable_thinking=False)
        settings['system_prompt']='List each visually present category once. Categories, not individual objects. Follow the short line format. Do not repeat.'
        raw=[];notes=[];items=[]
        try:
            throw_exception_if_processing_interrupted()
            first=worker.run(image=image,prompt=prompt,max_new_tokens=min(320,max(64,int(max_new_tokens))),**settings)[0]
            raw.append(first);items,warnings=inventory(first);notes.extend(warnings)
            if warnings:
                throw_exception_if_processing_interrupted()
                second=worker.run(image=image,prompt=RETRY,max_new_tokens=192,**settings)[0]
                raw.append(second);recovered,more=inventory(second)
                # Prefer the fresh whole-frame inventory; retain complete original evidence only.
                by_category={r['category']:r for r in recovered}
                for row in items:by_category.setdefault(row['category'],row)
                items=list(by_category.values())[:8];notes.extend(more)
            status=f'{len(items)} unique category proposals; {len(raw)} call(s), max 512 generated tokens total. '
            if notes:status+='RECOVERY / PARTIAL INVENTORY POSSIBLE: '+'; '.join(dict.fromkeys(notes))
            if not items:status+=' No usable category: SAM and semantic rendering will be skipped.'
            normalized=json.dumps(items,ensure_ascii=False)+'\nDOGMA_STATUS: '+status
            diagnostics=status+'\n\n'+'\n\n--- BOUNDED RETRY ---\n\n'.join(raw)
            return normalized,diagnostics
        finally:worker.clear_model()

class DOGMAProposeCategoriesV112:
    INPUT_TYPES=classmethod(lambda cls:node('DOGMAProposeCategoriesV111').INPUT_TYPES())
    RETURN_TYPES=('DOGMA_PLAN','STRING','STRING');RETURN_NAMES=('proposal','presence_prompt','report')
    FUNCTION='build';CATEGORY='DOGMA/v1.0.12'
    def build(self,planner_text):
        items,warnings=inventory(planner_text)
        proposal=[dict(id=i+1,**row) for i,row in enumerate(items)]
        status=str(planner_text).partition('\nDOGMA_STATUS: ')[2]
        prompt=('Inspect the actual photograph independently. Check ONLY the IDs listed below, once each. '
                'Each line: id | present OR absent OR uncertain | short visible evidence/location. '
                'Presence means the named type is actually visible, not expected from setting. '
                'No JSON, explanation or additional IDs. Maximum eight lines. Proposals: '+json.dumps([{'id':p['id'],'category':p['category']} for p in proposal]))
        report=(status+'\n' if status else '')+'\n'.join(warnings)+'\n'+json.dumps(proposal,ensure_ascii=False,indent=2)
        return proposal,prompt,report

class DOGMAVerifiedPlan8V112:
    @classmethod
    def INPUT_TYPES(cls):
        schema=copy.deepcopy(node('DOGMAVerifiedPlan8V111').INPUT_TYPES())
        schema['optional']={'planner_status':('STRING',{'forceInput':True})}
        return schema
    RETURN_TYPES=('STRING',)+('STRING','STRING','FLOAT')*8
    RETURN_NAMES=('plan_preview',)+tuple(x for i in range(1,9) for x in (f'category_{i}',f'sam_prompt_{i}',f'sam_threshold_{i}'))
    FUNCTION='build';CATEGORY='DOGMA/v1.0.12'
    def build(self,proposal,presence_text,sam_threshold=.4,planner_status=''):
        rows,warnings=read_rows(presence_text,True)
        result=node('DOGMAVerifiedPlan8V111')().build(proposal,json.dumps(rows),sam_threshold)
        return (planner_status+'\n'+'\n'.join(warnings)+'\n'+result[0],*result[1:])

NODE_CLASS_MAPPINGS={c.__name__:c for c in (DOGMABoundedPlannerV112,DOGMAProposeCategoriesV112,DOGMAVerifiedPlan8V112)}
NODE_DISPLAY_NAME_MAPPINGS={k:k.replace('DOGMA','DOGMA ').replace('V112',' v1.0.12') for k in NODE_CLASS_MAPPINGS}
