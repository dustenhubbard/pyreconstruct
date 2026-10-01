"""Adding objects to the 3D scene when some are not in the series.

`VPlotter.addToScene` drops the names the open series does not have and asks
before going on with the rest. It removed them by position while walking a
copy of the list, so each removal shifted the next name past the check: two
missing names raised `IndexError`, and the prompt named the wrong objects.

The real unbound method runs on a stand-in carrying the attributes it reads;
building the VTK plotter offscreen is impractical. The series is real.
"""
import types

import pytest


def _run(real_series, monkeypatch, objects, answer=False):
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    prompts = []
    monkeypatch.setattr(
        cp, "notify", lambda msg, *a, **k: prompts.append(("notify", msg))
    )
    monkeypatch.setattr(
        cp, "notifyConfirm",
        lambda msg, *a, **k: prompts.append(("confirm", msg)) or answer,
    )
    started = []

    class FakePool:
        def createWorker(self, fn, series, objs, ztraces, **kw):
            started.append([d["name"] for d in objs])
            result = types.SimpleNamespace(connect=lambda f: None)
            return types.SimpleNamespace(
                signals=types.SimpleNamespace(result=result)
            )

        def startAll(self, *a, **k):
            pass

    monkeypatch.setattr(cp, "ThreadPoolProgBar", FakePool)
    fake = types.SimpleNamespace(
        series=real_series,
        objs=cp.SceneObjectList(),
        saveState=lambda: None,
        mainwindow=types.SimpleNamespace(statusbar=None),
        updateSelected=lambda: None,
        render=lambda: None,
        placeInScene=lambda result: None,
    )
    fake.removeFromScene = types.MethodType(cp.VPlotter.removeFromScene, fake)
    cp.VPlotter.addToScene(fake, list(objects), [])
    return prompts, started


def test_two_missing_objects_do_not_raise(real_series, monkeypatch):
    assert not {"zz_a", "zz_b"} & set(real_series.data["objects"])

    prompts, started = _run(real_series, monkeypatch, ["zz_a", "zz_b"])

    assert prompts == [
        ("notify", "None of the requested objects exist in this series.")
    ]
    assert started == []


def test_the_prompt_names_every_missing_object(real_series, monkeypatch):
    present = sorted(real_series.data["objects"])[0]

    prompts, started = _run(
        real_series, monkeypatch, ["zz_a", "zz_b", present]
    )

    kind, message = prompts[0]
    assert kind == "confirm"
    first_line = message.splitlines()[0]
    assert "zz_a" in first_line and "zz_b" in first_line
    assert present not in first_line
    assert started == []  # the answer was no


def test_going_on_adds_the_objects_that_exist(real_series, monkeypatch):
    present = sorted(real_series.data["objects"])[:2]

    prompts, started = _run(
        real_series, monkeypatch, ["zz_a", present[0], "zz_b", present[1]],
        answer=True,
    )

    assert [kind for kind, _ in prompts] == ["confirm"]
    assert len(started) == 1
    assert set(present) <= set(started[0])
