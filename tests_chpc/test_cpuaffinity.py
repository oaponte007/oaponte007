import os

import pytest

from chpc.cpuaffinity import pin_to_cores


def test_pin_to_empty_set_returns_false():
    assert pin_to_cores([]) is False


def test_pin_to_available_core(monkeypatch):
    calls = {}

    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {0, 1, 2, 3})

    def fake_set(pid, cores):
        calls["cores"] = cores

    monkeypatch.setattr(os, "sched_setaffinity", fake_set)

    assert pin_to_cores([1]) is True
    assert calls["cores"] == {1}


def test_pin_falls_back_to_available_intersection(monkeypatch):
    calls = {}
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {0, 1})
    monkeypatch.setattr(os, "sched_setaffinity", lambda pid, cores: calls.setdefault("cores", cores))

    result = pin_to_cores([1, 99])

    assert result is True
    assert calls["cores"] == {1}


def test_pin_returns_false_when_no_requested_core_available(monkeypatch):
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {0, 1})
    monkeypatch.setattr(os, "sched_setaffinity", lambda pid, cores: None)

    assert pin_to_cores([99]) is False


def test_pin_handles_setaffinity_oserror(monkeypatch):
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {0})

    def raise_oserror(pid, cores):
        raise OSError("blocked by seccomp")

    monkeypatch.setattr(os, "sched_setaffinity", raise_oserror)

    assert pin_to_cores([0]) is False
