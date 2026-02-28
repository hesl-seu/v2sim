from v2sim import *
from feasytools import SegFunc

def test_gs():
    gs1 = GS("gs1", "node1", 6, 100.0, 200.0, ConstPriceGetter(1.0), None, 0.7)
    gvs = [GV(f"g{i}", VehType.Private, 50, 0.4, 7.9 / 100 / 1000, 12, 0.95, 0.2, [], {}) for i in range(10)]
    for gv in gvs:
        gs1.add_veh(gv)
    assert gs1.pop_veh(gvs[9])
    assert gs1.pop_veh(gvs[0])
    assert not gs1.pop_veh(gvs[9])  # already removed
    assert len(gs1) == 8
    assert len(gs1._chi) == 6
    assert len(gs1._buf) == 2
    chi_veh_names = set(veh._name for veh in gs1._chi)
    buf_veh_names = set(veh._name for veh in gs1._buf)
    assert chi_veh_names == {f"g{i}" for i in range(1, 7)}
    assert buf_veh_names == {f"g{i}" for i in range(7, 9)}
    assert gvs[1] in gs1 and gvs[7] in gs1

    ret = gs1.update(60, 0, 7)
    for gv in ret:
        assert gv._energy >= gv._etar
    for gv in gvs[1:7]:
        assert gv not in gs1, f"{gv._name} should have been removed"
        assert abs(gv._cost - 1.0 * (50 - 50 * 0.4)) < 1e-6, f"{gv._name} cost calculation error"
    
    ret = gs1.update(60, 0, 7)
    for gv in ret:
        assert gv._energy >= gv._etar
    for gv in gvs[7:9]:
        assert gv not in gs1, f"{gv._name} should have been removed"

def test_cs():
    cs1 = BiCS("cs1", "node1", 10, "b1", 1.0, -1.0, CSType.FCS, 300.0, 100.0, ToUPriceGetter(SegFunc([3600, 7200, 10800], [0, 8*3600, 18*3600])))
    evs = [EV(f"e{i}", VehType.Private, 60, 0.5, 60 / 300, 0.88, 0.9, 0.93, 300, 7, 20, 20, 0.9, 0.6, 0.2, 0.75, [], {}) for i in range(8)]
    for ev in evs: cs1.add_veh(ev)
    assert cs1.pop_veh(evs[7])
    assert cs1.pop_veh(evs[0])
    assert not cs1.pop_veh(evs[7])  # already removed
    assert len(cs1) == 6
    assert len(cs1._chi) == 4
    assert len(cs1._buf) == 2
    chi_veh_names = set(veh._name for veh in cs1._chi)
    buf_veh_names = set(veh._name for veh in cs1._buf)
    assert chi_veh_names == {f"e{i}" for i in range(1, 5)}
    assert buf_veh_names == {f"e{i}" for i in range(5, 7)}
    assert evs[1] in cs1 and evs[5] in cs1

    ret = cs1.update(3600, 7*3600, 0, 1.0, 1.0)
    for ev in ret:
        assert ev._energy >= ev._etar
    for ev in evs[1:5]:
        assert ev not in cs1, f"{ev._name} should have been removed"
        assert abs(ev._cost - 0.2 * (60 - 60 * 0.5) / 0.9) < 1e-6, f"{ev._name} cost calculation error"
    
    ret2 = cs1.update(3600, 8*3600, 0, 1.0, 1.0)
    for ev in ret2:
        assert ev._energy >= ev._etar
    for ev in evs[5:7]:
        assert ev not in cs1, f"{ev._name} should have been removed"