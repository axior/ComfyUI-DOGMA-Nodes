"""Read-only visual review of the actual render and blend, backed by temp PNGs."""
import copy
import json
from pathlib import Path
import uuid

from .dogma_integrated_v122 import DOGMAPhase3RenderV122


class ReviewRecorder:
    def __init__(self, side):
        import folder_paths
        self.root = Path(folder_paths.get_temp_directory()) / 'DOGMA_REVIEW' / uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=False)
        self.side = side
        self.categories = []
        self.current = None
        self.pending = None
        self.last_result = None
        self.counter = 0

    def save(self, image):
        import numpy as np
        from PIL import Image
        self.counter += 1
        array = image[0, ..., :3].detach().float().cpu().clamp(0, 1).numpy()
        pil = Image.fromarray(np.rint(array * 255).astype(np.uint8))
        if self.side:
            pil.thumbnail((self.side, self.side), Image.Resampling.LANCZOS)
        path = self.root / f'{self.counter:04d}.png'
        pil.save(path)
        return str(path)

    @staticmethod
    def region(image, job):
        m = job['metadata']
        x, y, w, h = (int(m[k]) for k in ('x', 'y', 'width', 'height'))
        return image[:, y:y+h, x:x+w, :3]

    def finish_category(self):
        if self.current is not None:
            self.current['after'] = self.save(self.last_result)

    def before(self, job, image):
        # Group consecutive target jobs; never reorder the renderer to make a prettier report.
        if self.current is None or self.current['target_id'] != job['target_id']:
            self.finish_category()
            before = self.current['after'] if self.current else self.save(image)
            self.current = dict(category=job['category'], target_id=job['target_id'],
                                denoise=job['denoise'], before=before, crops=[])
            self.categories.append(self.current)
        self.last_result = image
        self.pending = dict(id=job['id'], instance_id=job['instance_id'],
                            before=self.save(self.region(image, job)),
                            input=self.save(job['image']),
                            prompt=job.get('prompt', ''), metadata=job['metadata'])
        for key in ('inpaint', 'mask'):
            mask = job[key]
            if mask.ndim == 2: mask = mask[None]
            self.pending[key] = self.save(mask[..., None].expand(-1, -1, -1, 3))

    def after(self, job, result, generated, info):
        self.pending.update(after=self.save(self.region(result, job)),
                            generated=self.save(generated) if generated is not None else self.pending['input'],
                            status=info['status'], reason=info.get('reason', ''))
        self.current['crops'].append(self.pending)
        self.last_result = result
        self.pending = None

    def finish(self):
        self.finish_category()
        review = dict(schema=1, enabled=True, preview_side=self.side, categories=self.categories)
        path = self.root / 'review.json'
        path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
        review['manifest'] = str(path)
        return review


class DOGMAPhase3RenderV123(DOGMAPhase3RenderV122):
    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(super().INPUT_TYPES())
        inputs['required'].update(
            save_comparisons=('BOOLEAN', {'default': True}),
            comparison_side=('INT', {'default': 2048, 'min': 0, 'max': 8192, 'step': 64,
                                     'tooltip': 'Preview longest side only. 0 saves native resolution. Render pixels are unchanged.'}))
        return inputs
    RETURN_TYPES = ('IMAGE', 'STRING', 'DOGMA_REVIEW')
    RETURN_NAMES = ('image', 'render_report', 'review')
    CATEGORY = 'DOGMA/v1.0.23'

    def render(self, prepared, save_comparisons=True, comparison_side=2048, **kwargs):
        recorder = ReviewRecorder(comparison_side) if save_comparisons and prepared['jobs'] else None
        image, report = super().render(prepared, _review=recorder, **kwargs)
        review = recorder.finish() if recorder else dict(schema=1, enabled=save_comparisons, categories=[])
        if recorder: report += '\nVisual comparisons: ' + review['manifest']
        return image, report, review


class DOGMAEmptyReviewV123:
    @classmethod
    def INPUT_TYPES(cls): return {'required': {}}
    RETURN_TYPES = ('DOGMA_REVIEW',)
    FUNCTION = 'empty'
    CATEGORY = 'DOGMA/v1.0.23'
    def empty(self): return (dict(schema=1, enabled=False, categories=[]),)


def load_preview(path, side):
    import numpy as np
    import torch
    from PIL import Image
    with Image.open(path) as image:
        image = image.convert('RGB')
        if side: image.thumbnail((side, side), Image.Resampling.LANCZOS)
        return torch.from_numpy(np.array(image, copy=True)).float()[None] / 255.


class DOGMAReviewPairV123:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'review': ('DOGMA_REVIEW',),
            'category_index': ('INT', {'default': 1, 'min': 1, 'max': 128}),
            'crop_index': ('INT', {'default': 1, 'min': 1, 'max': 1024}),
            'view': (['category', 'crop_applied', 'crop_generated', 'masks'],),
            'preview_side': ('INT', {'default': 1536, 'min': 0, 'max': 8192, 'step': 64})}}
    RETURN_TYPES = ('IMAGE', 'IMAGE', 'STRING')
    RETURN_NAMES = ('before_A', 'after_B', 'details')
    FUNCTION = 'pair'
    CATEGORY = 'DOGMA/v1.0.23'

    def pair(self, review, category_index, crop_index, view, preview_side):
        import torch
        empty = torch.empty((0, 64, 64, 3))
        categories = review['categories']
        label = f'CAT {category_index:02d}'
        if not 1 <= category_index <= len(categories):
            reason = 'Confronti disattivati.' if not review['enabled'] else f'Nessuna categoria in questo slot; {len(categories)} passaggi disponibili.'
            return {'ui': {'dogma_review_label': [label + ' - vuoto']}, 'result': (empty, empty, reason)}
        cat = categories[category_index - 1]
        label += f' - {cat["category"]} - denoise {cat["denoise"]:.2f}'
        details = [label, 'Ordine reale di lavorazione; A = prima, B = dopo.',
                   'Tutti i confronti provengono dai risultati effettivi, non da una nuova generazione.',
                   'Categorie: ' + '; '.join(f'{i+1}: {c["category"]}' for i, c in enumerate(categories))]
        details.extend(f'Ritaglio {i+1} (job {j["id"]}): {j["status"]} {j["reason"]}' for i, j in enumerate(cat['crops']))
        if view == 'category':
            a, b = cat['before'], cat['after']
            label += ' - prima/dopo categoria'
        else:
            if not 1 <= crop_index <= len(cat['crops']):
                return {'ui': {'dogma_review_label': [label + ' - ritaglio assente']},
                        'result': (empty, empty, '\n'.join(details) + '\nRitaglio richiesto non presente.')}
            crop = cat['crops'][crop_index - 1]
            keys = {'crop_applied': ('before', 'after'), 'crop_generated': ('input', 'generated'), 'masks': ('inpaint', 'mask')}[view]
            a, b = (crop[key] for key in keys)
            label += f' - ritaglio {crop_index}/{len(cat["crops"])} - {view}'
            details += [label, 'Prompt: ' + crop['prompt']]
            if view == 'crop_generated': details.append('B e il crop generato grezzo: fuori dalla maschera puo differire senza essere applicato al master.')
            if view == 'masks': details.append('A = maschera inpaint; B = maschera finale di blend.')
        try:
            before, after = load_preview(a, preview_side), load_preview(b, preview_side)
        except FileNotFoundError:
            raise ValueError('DOGMA: anteprime temporanee non piu disponibili. Rieseguire la fase 3 per rigenerare i confronti.') from None
        return {'ui': {'dogma_review_label': [label]}, 'result': (before, after, '\n'.join(details))}


NODE_CLASS_MAPPINGS = {c.__name__: c for c in (DOGMAPhase3RenderV123, DOGMAEmptyReviewV123, DOGMAReviewPairV123)}
NODE_DISPLAY_NAME_MAPPINGS = {name: name.replace('DOGMA', 'DOGMA ').replace('V123', ' 1.0.23') for name in NODE_CLASS_MAPPINGS}
