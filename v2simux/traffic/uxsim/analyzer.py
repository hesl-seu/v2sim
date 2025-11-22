"""
Analyzer for a UXsim simulation result.
This module is automatically loaded when you import the `uxsim` module.
"""

import numpy as np
import time
from collections import defaultdict as ddict
from scipy.sparse.csgraph import floyd_warshall
from .utils import *

class Analyzer:
    """
    Class for analyzing and visualizing a simulation result.
    """

    def __init__(s, W, font_pillow=None, font_matplotlib=None):
        """
        Create a result analysis object.

        Parameters
        ----------
        W : object
            The world to which this belongs.
        font_pillow : str, optional
            The path to the font file for Pillow. If not provided, the default font for English and Japanese is used.
        font_matplotlib : str, optional
            The font name for Matplotlib. If not provided, the default font for English and Japanese is used.
        """
        s.W = W

        # os.makedirs(f"out{s.W.name}", exist_ok=True)

        #基礎統計量
        s.average_speed = 0
        s.average_speed_count = 0
        s.trip_completed = 0
        s.trip_all = 0
        s.total_travel_time = 0
        s.average_travel_time = 0

        #フラグ
        s.flag_edie_state_computed = 0
        s.flag_trajectory_computed = 0
        s.flag_od_analysis = 0


    def od_analysis(s):
        """
        Analyze OD-specific stats: number of trips, number of completed trips, free-flow travel time, average travel time, its std, total distance traveled.
        """
        if s.flag_od_analysis:
            return 0
        else:
            s.flag_od_analysis = 1

        s.od_trips = ddict(lambda: 0)
        s.od_trips_comp = ddict(lambda: 0)
        s.od_tt_free = ddict(lambda: 0)
        s.od_tt = ddict(lambda: [])
        s.od_tt_ave = ddict(lambda: 0)
        s.od_tt_std = ddict(lambda: 0)
        s.od_dist = ddict(lambda: [])
        s.od_dist_total = ddict(lambda: 0)
        s.od_dist_ave = ddict(lambda: 0)
        s.od_dist_std = ddict(lambda: 0)
        s.od_dist_min = ddict(lambda: 0)
        dn = s.W.DELTAN

        #自由旅行時間と最短距離
        adj_mat_time = np.zeros([len(s.W.NODES), len(s.W.NODES)])
        adj_mat_dist = np.zeros([len(s.W.NODES), len(s.W.NODES)])
        for link in s.W.LINKS:
            i = link.start_node.id
            j = link.end_node.id
            if s.W.ADJ_MAT[i,j]:
                adj_mat_time[i,j] = link.length/link.u
                adj_mat_dist[i,j] = link.length
                if link.capacity_in == 0: #流入禁止の場合は通行不可
                    adj_mat_time[i,j] = np.inf
                    adj_mat_dist[i,j] = np.inf
            else:
                adj_mat_time[i,j] = np.inf
                adj_mat_dist[i,j] = np.inf
        dist_time = floyd_warshall(adj_mat_time)
        dist_space = floyd_warshall(adj_mat_dist)

        for veh in s.W.VEHICLES.values():
            o = veh.orig
            d = veh.dest
            if d != None:
                s.od_trips[o,d] += dn

                veh_links = [rec[1] for rec in veh.log_t_link if hasattr(rec[1], "length")]
                veh_dist_traveled = sum([l.length for l in veh_links])
                if veh.state == "run":
                    veh_dist_traveled += veh.x
                veh.distance_traveled = veh_dist_traveled
                s.od_dist[o,d].append(veh.distance_traveled)

                if veh.travel_time != -1:
                    s.od_trips_comp[o,d] += dn
                    s.od_tt[o,d].append(veh.travel_time)
        for o,d in s.od_tt.keys():
            s.od_tt_ave[o,d] = np.average(s.od_tt[o,d])
            s.od_tt_std[o,d] = np.std(s.od_tt[o,d])
            s.od_tt_free[o,d] = dist_time[o.id, d.id]
            s.od_dist_total[o,d] = np.sum(s.od_dist[o,d])
            s.od_dist_min[o,d] = dist_space[o.id, d.id]
            s.od_dist_ave[o,d] = np.average(s.od_dist[o,d])
            s.od_dist_std[o,d] = np.std(s.od_dist[o,d])

    def link_analysis_coarse(s):
        """
        Analyze link-level coarse stats: traffic volume, remaining vehicles, free-flow travel time, average travel time, its std.
        """
        s.linkc_volume = ddict(lambda:0)
        s.linkc_tt_free = ddict(lambda:0)
        s.linkc_tt_ave = ddict(lambda:-1)
        s.linkc_tt_std = ddict(lambda:-1)
        s.linkc_remain = ddict(lambda:0)

        for l in s.W.LINKS:
            s.linkc_volume[l] = l.cum_departure[-1]
            s.linkc_remain[l] = l.cum_arrival[-1]-l.cum_departure[-1]
            s.linkc_tt_free[l] = l.length/l.u
            if s.linkc_volume[l]:
                s.linkc_tt_ave[l] = np.average([t for t in l.traveltime_actual if t>0])
                s.linkc_tt_std[l] = np.std([t for t in l.traveltime_actual if t>0])

    def compute_accurate_traj(s):
        """
        Generate more complete vehicle trajectories for each link by extrapolating recorded trajectories. It is assumed that vehicles are in free-flow travel at the end of the link.
        """
        if s.W.vehicle_logging_timestep_interval != 1:
            warnings.warn("vehicle_logging_timestep_interval is not 1. The trajectories are not exactly accurate.", LoggingWarning)

        if s.flag_trajectory_computed:
            return 0
        else:
            s.flag_trajectory_computed = 1

        for veh in s.W.VEHICLES.values():
            l_old = None
            for i in lange(veh.log_t):
                if veh.log_link[i] != -1:
                    l = s.W.get_link(veh.log_link[i])
                    if l_old != l:
                        l.tss.append([])
                        l.xss.append([])
                        l.ls.append(veh.log_lane[i])
                        l.cs.append(veh.color)
                        l.names.append(veh.name)

                    l_old = l
                    l.tss[-1].append(veh.log_t[i])
                    l.xss[-1].append(veh.log_x[i])

        for l in s.W.LINKS:
            #端部を外挿
            for i in lange(l.xss):
                if len(l.xss[i]):
                    if l.xss[i][0] != 0:
                        x_remain = l.xss[i][0]
                        if x_remain/l.u > s.W.DELTAT*0.01:
                            l.xss[i].insert(0, 0)
                            l.tss[i].insert(0, l.tss[i][0]-x_remain/l.u)
                    if l.length-l.u*s.W.DELTAT <= l.xss[i][-1] < l.length:
                        x_remain = l.length-l.xss[i][-1]
                        if x_remain/l.u > s.W.DELTAT*0.01:
                            l.xss[i].append(l.length)
                            l.tss[i].append(l.tss[i][-1]+x_remain/l.u)

    def compute_edie_state(s):
        """
        Compute Edie's traffic state for each link.
        """
        if s.flag_edie_state_computed:
            return 0
        else:
            s.flag_edie_state_computed = 1

        s.compute_accurate_traj()
        for l in s.W.LINKS:
            DELTAX = l.edie_dx
            DELTATE = l.edie_dt
            MAXX = l.length
            MAXT = s.W.TMAX

            dt = DELTATE
            dx = DELTAX
            tn = [[ddict(lambda: 0) for i in range(int(MAXX/DELTAX))] for j in range(int(MAXT/DELTATE))]
            dn = [[ddict(lambda: 0) for i in range(int(MAXX/DELTAX))] for j in range(int(MAXT/DELTATE))]

            l.k_mat = np.zeros([int(MAXT/DELTATE), int(MAXX/DELTAX)])
            l.q_mat = np.zeros([int(MAXT/DELTATE), int(MAXX/DELTAX)])
            l.v_mat = np.zeros([int(MAXT/DELTATE), int(MAXX/DELTAX)])

            for v in lange(l.xss):
                for i in lange(l.xss[v][:-1]):
                    i0 = l.names[v]
                    x0 = l.xss[v][i]
                    x1 = l.xss[v][i+1]
                    t0 = l.tss[v][i]
                    t1 = l.tss[v][i+1]
                    if t1-t0 != 0:
                        v0 = (x1-x0)/(t1-t0)
                    else:
                        #compute_accurate_traj()の外挿で極稀にt1=t0になったのでエラー回避（もう起きないはずだが念のため）
                        v0 = 0

                    tt = int(t0//dt)
                    xx = int(x0//dx)

                    if v0 > 0:
                        #残り
                        xl0 = dx-x0%dx
                        xl1 = x1%dx
                        tl0 = xl0/v0
                        tl1 = xl1/v0

                        if tt < int(MAXT/DELTATE) and xx < int(MAXX/DELTAX):
                            if xx == x1//dx:
                                #(x,t)
                                dn[tt][xx][i0] += x1-x0
                                tn[tt][xx][i0] += t1-t0
                            else:
                                #(x+n, t)
                                jj = int(x1//dx-xx+1)
                                for j in range(jj):
                                    if xx+j < int(MAXX/DELTAX):
                                        if j == 0:
                                            dn[tt][xx+j][i0] += xl0
                                            tn[tt][xx+j][i0] += tl0
                                        elif j == jj-1:
                                            dn[tt][xx+j][i0] += xl1
                                            tn[tt][xx+j][i0] += tl1
                                        else:
                                            dn[tt][xx+j][i0] += dx
                                            tn[tt][xx+j][i0] += dx/v0
                    else:
                        if tt < int(MAXT/DELTATE) and xx < int(MAXX/DELTAX):
                            dn[tt][xx][i0] += 0
                            tn[tt][xx][i0] += t1-t0

            for i in lange(tn):
                for j in lange(tn[i]):
                    t = list(tn[i][j].values())*s.W.DELTAN
                    d = list(dn[i][j].values())*s.W.DELTAN
                    l.tn_mat[i,j] = sum(t)
                    l.dn_mat[i,j] = sum(d)
                    l.k_mat[i,j] = l.tn_mat[i,j]/DELTATE/DELTAX
                    l.q_mat[i,j] = l.dn_mat[i,j]/DELTATE/DELTAX
            with np.errstate(invalid="ignore"):
                l.v_mat = l.q_mat/l.k_mat
            l.v_mat = np.nan_to_num(l.v_mat, nan=l.u)


    @catch_exceptions_and_warn()
    def show_simulation_progress(s):
        """
        Print simulation progress.
        """
        if s.W.print_mode:
            vehs = [l.density*l.length for l in s.W.LINKS]
            sum_vehs = sum(vehs)

            vs = [l.density*l.length*l.speed for l in s.W.LINKS]
            if sum_vehs > 0:
                avev = sum(vs)/sum_vehs
            else:
                avev = 0

            print(f"{s.W.TIME:>8.0f} s| {sum_vehs:>8.0f} vehs|  {avev:>4.1f} m/s| {time.time()-s.W.sim_start_time:8.2f} s", flush=True)


    def compute_mfd(s, links=None):
        """
        Compute network average flow and density for MFD.
        """
        s.compute_edie_state()
        if links == None:
            links = s.W.LINKS
        links = [s.W.get_link(link) for link in links]
        links = frozenset(links)


        for i in range(len(s.W.Q_AREA[links])):
            tn = sum([l.tn_mat[i,:].sum() for l in s.W.LINKS if l in links])
            dn = sum([l.dn_mat[i,:].sum() for l in s.W.LINKS if l in links])
            an = sum([l.length*s.W.EULAR_DT for l in s.W.LINKS if l in links])
            s.W.K_AREA[links][i] = tn/an
            s.W.Q_AREA[links][i] = dn/an
