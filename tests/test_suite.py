# -*- coding: utf-8 -*-
"""غلاف pytest: يشغّل كل اختبارات المشروع (كل ملف يشغّل خادماً حقيقياً ومتصفحاً) ويعتبر الفشل أي رمز خروج ≠ 0."""
import os, subprocess, sys, pytest
HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.mark.parametrize("name", ["test_flow", "features_test", "station_test", "ui_test", "hier_test", "cohort_ui_test", "late_window_test", "mobile_offline_test", "mobile_scanner_test", "mobile_unreachable_test"])
def test_script(name):
    r = subprocess.run([sys.executable, os.path.join(HERE, name + ".py")], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]


def test_load_light():
    env = dict(os.environ, N="300", CONC="20")
    r = subprocess.run([sys.executable, os.path.join(HERE, "load_test.py")], capture_output=True, text=True, timeout=900, env=env)
    assert r.returncode == 0, r.stdout[-2000:]
