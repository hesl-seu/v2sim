from v2sim import *

def test_ev():
    epm = 60 / 400 # kWh/km
    epmkWhm = epm / 1000  # kWh/m
    v1 = EV("v1", VehType.Private, 60, 0.5, epm, 0.88, 0.9, 0.85, 350, 7, 20, 12, 0.95, 0.2, 0.5, 0.7, [], {})
    assert abs(v1.E - 60 * 0.5) < 1e-6
    v1.drive(1000)
    assert abs(v1.E - (60 * 0.5 - 1000 * epmkWhm)) < 1e-6
    v1.start_charging(400)
    v1.charge(60, 1.2)
    v1.end_charging()
    assert abs(v1.E - (60 * 0.5 - 1000 * epmkWhm + 350 * 60 / 3600 * 0.88)) < 1e-6
    assert abs(v1.cost  - (1.2 * 350 * 60 / 3600)) < 1e-6

    # x = range(120)
    # y = []
    # for i in range(120):
    #     v1.charge(5, 1.5)
    #     y.append(v1.soc)
    # from matplotlib import pyplot as plt
    # plt.plot(x, y)
    # plt.show()

def test_gv():
    epm = 7.9 / 100 / 1000  # L/m
    v1 = GV("g1", VehType.Private, 50, 0.4, epm, 12, 0.95, 0.2, [], {})
    assert abs(v1.E - 50 * 0.4) < 1e-6
    v1.drive(1000)
    assert abs(v1.E - (50 * 0.4 - 1000 * epm)) < 1e-6
    v1.start_refueling()
    v1.refuel(30, 9.0)
    v1.end_refueling()
    assert abs(v1.E - (50 * 0.4 - 1000 * epm + 30)) < 1e-6
    assert abs(v1.cost - (30 * 9.0)) < 1e-6