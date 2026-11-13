"""Per-session edit promotion, without interrupting Comfy's other jobs."""
import threading
import uuid
from .dogma_h3_edit_sampling import validate_final_options

_LOCK=threading.RLock()
_ACTIVE={}

class PromoteEdit(Exception):
    pass

class EditBatch:
    def __init__(self,session,total,available):
        self.session=session;self.id=uuid.uuid4().hex;self.total=total
        self.available=set(available);self.chosen=None;self.phase='draft';self.current=0;self.completed=0;self.final_options=None

    def snapshot(self):
        with _LOCK:
            return dict(id=self.id,phase=self.phase,total=self.total,current=self.current,completed=self.completed,chosen=self.chosen,final_options=self.final_options)

    def checkpoint(self):
        with _LOCK:
            if self.phase=='draft' and self.chosen:raise PromoteEdit()

    def add(self,trial):
        with _LOCK:self.available.add(trial);self.completed+=1

    def request(self,trial,batch_id=None,options=None):
        options=validate_final_options(options) if options is not None else None
        with _LOCK:
            if batch_id and batch_id!=self.id:raise ValueError('Il gruppo di provini è cambiato. Riapri la scelta.')
            if trial not in self.available:raise ValueError('Il provino deve essere già completo prima di sceglierlo.')
            if self.chosen and options!=self.final_options:raise ValueError('La modalità finale è già stata confermata. Attendi questa lavorazione.')
            if self.phase=='finish':
                if trial==self.chosen:return self.snapshot()
                raise ValueError('È già in corso la rigenerazione del provino scelto.')
            if self.phase!='draft':return None
            if self.chosen and self.chosen!=trial:raise ValueError('È già stato scelto un provino per la rigenerazione.')
            self.chosen=trial;self.final_options=options
            return self.snapshot()

    def seal(self):
        with _LOCK:
            self.phase='finish' if self.chosen else 'ready'
            return self.chosen

    def close(self):
        with _LOCK:
            if _ACTIVE.get(self.session) is self:_ACTIVE.pop(self.session)

def begin_batch(session,total,available):
    session=str(uuid.UUID(session))
    with _LOCK:
        if session in _ACTIVE:raise ValueError('Questa sessione ha già un gruppo di provini in esecuzione.')
        batch=EditBatch(session,total,available);_ACTIVE[session]=batch
        return batch

def request_promotion(session,trial,batch_id=None,options=None):
    session=str(uuid.UUID(session))
    with _LOCK:
        batch=_ACTIVE.get(session)
        return batch.request(trial,batch_id,options) if batch else None

def register_promotion_route(routes):
    from aiohttp import web
    @routes.post('/dogma/h3/v2/edit/promote')
    async def promote(request):
        try:
            data=await request.json()
            result=request_promotion(data['session'],data['trial'],data.get('batch'),data.get('options'))
            return web.json_response({'status':'accepted' if result else 'idle','batch':result})
        except (ValueError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))
