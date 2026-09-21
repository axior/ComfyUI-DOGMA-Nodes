"""Bounded ModernVLM lifetime for an ordered list of independent images.

Comfy maps ordinary nodes over lists. With unload_after=True that reloaded an
8B model for every mask. Keeping those ordinary nodes cached instead retains
one private bitsandbytes model per graph node. This adapter owns one worker
for one list, reuses it sequentially, and releases it on every exit path.
"""

import copy
import inspect
import logging
import time


def modern_class():
    import nodes

    cls = nodes.NODE_CLASS_MAPPINGS.get('ModernVLM')
    if cls is None:
        raise RuntimeError('DOGMA: install/enable comfyui_vlm_nodes (ModernVLM) in Manager, then restart ComfyUI.')
    return cls


def single(values, name):
    if not isinstance(values, (list, tuple)) or len(values) != 1:
        raise ValueError(f'DOGMA: {name} must have one shared value for this image list.')
    return values[0]


class DOGMAVLMListV568:
    @classmethod
    def INPUT_TYPES(cls):
        # Resolve only at schema/request time: custom-node import order is arbitrary.
        source = copy.deepcopy(modern_class().INPUT_TYPES())
        required = source['required']
        required['image'] = ('IMAGE',)
        optional = {
            name: source['optional'][name]
            for name in ('system_prompt', 'attention_mode', 'enable_thinking', 'stream_output')
        }
        optional['stream_output'] = ('BOOLEAN', {'default': True})
        return {'required': required, 'optional': optional, 'hidden': {'unique_id': 'UNIQUE_ID'}}

    INPUT_IS_LIST = True
    RETURN_TYPES = ('STRING', 'STRING')
    RETURN_NAMES = ('texts_in_order', 'timing_report')
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = 'run'
    CATEGORY = 'DOGMA/v56.8'
    DESCRIPTION = 'One model load per image list; sequential captions/audits; release after the list, including errors and cancellation.'

    def run(self, image, prompt, **settings):
        from comfy.model_management import throw_exception_if_processing_interrupted
        from comfy.utils import ProgressBar

        if not isinstance(image, (list, tuple)) or not isinstance(prompt, (list, tuple)):
            raise ValueError('DOGMA: expected ordered Comfy image/prompt lists.')
        count = len(image)
        if not count:
            return ([], 'DOGMA VLM: no images; no model loaded.')
        if len(prompt) not in (1, count):
            raise ValueError(f'DOGMA: {count} images but {len(prompt)} prompts; refusing ambiguous alignment.')
        for tensor in image:
            if getattr(tensor, 'ndim', None) != 4 or tensor.shape[0] != 1:
                raise ValueError('DOGMA: each list item must contain exactly one image, not an image batch.')
        if any(not isinstance(text, str) for text in prompt):
            raise ValueError('DOGMA: each prompt must be text.')
        options = {name: single(value, name) for name, value in settings.items()}
        node_id = options.get('unique_id')
        options['unload_after'] = False
        options.setdefault('stream_output', True)
        worker_type = modern_class()
        if not callable(getattr(worker_type, 'clear_model', None)):
            raise RuntimeError('DOGMA: this ModernVLM version has no clear_model lifecycle API. Update comfyui_vlm_nodes.')
        progress_options = {'node_id': node_id} if 'node_id' in inspect.signature(ProgressBar).parameters else {}
        progress = ProgressBar(count, **progress_options)
        progress.update_absolute(0)
        throw_exception_if_processing_interrupted()
        worker = worker_type()
        results = []
        elapsed = []
        started = time.perf_counter()
        try:
            for index, tensor in enumerate(image):
                throw_exception_if_processing_interrupted()
                logging.info('[DOGMA VLM %s] image %d/%d START%s', node_id, index + 1, count,
                             ' (initial model load)' if index == 0 else ' (reuse loaded model)')
                tick = time.perf_counter()
                output = worker.run(image=tensor, prompt=prompt[0 if len(prompt) == 1 else index], **options)
                if not isinstance(output, (tuple, list)) or len(output) != 1 or not isinstance(output[0], str):
                    raise RuntimeError('DOGMA: unexpected ModernVLM result; no partial list will be accepted.')
                throw_exception_if_processing_interrupted()
                results.append(output[0])
                elapsed.append(time.perf_counter() - tick)
                progress.update_absolute(index + 1)
                logging.info('[DOGMA VLM %s] image %d/%d DONE in %.1fs', node_id, index + 1, count, elapsed[-1])
        finally:
            # KJ's global unload alone cannot release private bitsandbytes handles.
            # The worker is local, never retained by this Comfy node across queues.
            worker.clear_model()
            logging.info('[DOGMA VLM %s] model released; %d/%d complete, %.1fs total',
                         node_id, len(results), count, time.perf_counter() - started)
        report = f'{count}/{count} images; one worker, released at end; {time.perf_counter() - started:.1f}s total.\n'
        report += '\n'.join(f'{index}: {seconds:.1f}s' for index, seconds in enumerate(elapsed, 1))
        return (results, report)


NODE_CLASS_MAPPINGS = {'DOGMAVLMListV568': DOGMAVLMListV568}
NODE_DISPLAY_NAME_MAPPINGS = {'DOGMAVLMListV568': 'DOGMA VLM — ordered list / one model load'}
