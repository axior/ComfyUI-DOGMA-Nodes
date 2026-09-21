import importlib.util
import os
import sys
import types

import pytest
import torch


spec = importlib.util.spec_from_file_location('v568', os.environ['DOGMA_V568_MODULE'])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def runtime(monkeypatch):
    state = types.SimpleNamespace(workers=[], loads=0, releases=0, calls=[], progress=[], checks=0,
                                  fail_at=None, interrupt_at=None, malformed=False)

    class Worker:
        def __init__(self):
            state.workers.append(self)
            self.loaded = False

        def run(self, image, prompt, **options):
            if not self.loaded:
                state.loads += 1
                self.loaded = True
            state.calls.append((int(image[0, 0, 0, 0]), prompt, options))
            assert options['unload_after'] is False
            if len(state.calls) == state.fail_at:
                raise RuntimeError('generation failed')
            return {'bad': True} if state.malformed else (f'{prompt}:{int(image[0, 0, 0, 0])}',)

        def clear_model(self):
            state.releases += 1
            self.loaded = False

    class Progress:
        def __init__(self, total, node_id=None):
            assert node_id == '30:2202'
            self.total = total

        def update_absolute(self, value):
            state.progress.append((value, self.total))

    def interrupt():
        state.checks += 1
        if state.checks == state.interrupt_at:
            raise KeyboardInterrupt()

    monkeypatch.setattr(m, 'modern_class', lambda: Worker)
    monkeypatch.setitem(sys.modules, 'comfy', types.ModuleType('comfy'))
    monkeypatch.setitem(sys.modules, 'comfy.utils', types.SimpleNamespace(ProgressBar=Progress))
    monkeypatch.setitem(sys.modules, 'comfy.model_management',
                        types.SimpleNamespace(throw_exception_if_processing_interrupted=interrupt))
    return state


def inputs(count=3):
    return dict(image=[torch.full((1, 2, 2, 3), float(i)) for i in range(count)],
                prompt=[f'crop{i}' for i in range(count)], model=['Qwen 3 VL 8B Instruct'],
                custom_model_id=[''], memory_mode=['8-bit (bitsandbytes)'], max_new_tokens=[32],
                temperature=[0.0], top_p=[0.9], unique_id=['30:2202'])


def test_one_load_for_ordered_list_and_release(runtime):
    text, report = m.DOGMAVLMListV568().run(**inputs())
    assert text == ['crop0:0', 'crop1:1', 'crop2:2']
    assert runtime.loads == runtime.releases == len(runtime.workers) == 1
    assert runtime.progress == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert all(call[2]['stream_output'] is True for call in runtime.calls)
    assert '3/3 images' in report


def test_no_cached_worker_retained_across_runs(runtime):
    node = m.DOGMAVLMListV568()
    node.run(**inputs())
    node.run(**inputs())
    assert runtime.loads == runtime.releases == 2
    assert not any(worker.loaded for worker in runtime.workers)
    assert node.__dict__ == {}


def test_broadcast_prompt_but_keep_separate_image_outputs(runtime):
    data = inputs()
    data['prompt'] = ['caption']
    assert m.DOGMAVLMListV568().run(**data)[0] == ['caption:0', 'caption:1', 'caption:2']


@pytest.mark.parametrize('field,value', [('prompt', ['one', 'two']), ('model', ['a', 'b']),
                                         ('image', [torch.zeros((2, 2, 2, 3))]), ('prompt', [None])])
def test_invalid_alignment_fails_before_loading(runtime, field, value):
    data = inputs()
    data[field] = value
    with pytest.raises(ValueError):
        m.DOGMAVLMListV568().run(**data)
    assert not runtime.workers


def test_generation_error_releases_and_does_not_return_partial_list(runtime):
    runtime.fail_at = 2
    with pytest.raises(RuntimeError, match='generation failed'):
        m.DOGMAVLMListV568().run(**inputs())
    assert runtime.loads == runtime.releases == 1
    assert len(runtime.calls) == 2
    assert runtime.progress[-1] == (1, 3)


@pytest.mark.parametrize('at,loaded', [(1, 0), (2, 0), (3, 1), (4, 1)])
def test_interruption_releases_worker_and_never_finishes_list(runtime, at, loaded):
    runtime.interrupt_at = at
    with pytest.raises(KeyboardInterrupt):
        m.DOGMAVLMListV568().run(**inputs())
    assert runtime.loads == loaded
    assert runtime.releases == len(runtime.workers)
    assert all(not w.loaded for w in runtime.workers)


def test_empty_list_skips_model(runtime):
    assert m.DOGMAVLMListV568().run(**inputs(0))[0] == []
    assert not runtime.workers


def test_bad_provider_result_releases(runtime):
    runtime.malformed = True
    with pytest.raises(RuntimeError, match='unexpected ModernVLM'):
        m.DOGMAVLMListV568().run(**inputs())
    assert runtime.releases == 1


def test_old_progressbar_without_node_id_is_supported(runtime, monkeypatch):
    class OldProgress:
        def __init__(self, total):
            self.total = total

        def update_absolute(self, value):
            runtime.progress.append((value, self.total))

    monkeypatch.setattr(sys.modules['comfy.utils'], 'ProgressBar', OldProgress)
    assert len(m.DOGMAVLMListV568().run(**inputs())[0]) == 3


def test_missing_dependency_has_actionable_message(monkeypatch):
    monkeypatch.setitem(sys.modules, 'nodes', types.SimpleNamespace(NODE_CLASS_MAPPINGS={}))
    with pytest.raises(RuntimeError, match='Manager'):
        m.modern_class()
