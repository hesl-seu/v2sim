"""
Analyzer for a UXsim simulation result.
This module is automatically loaded when you import the `uxsim` module.
"""

import numpy as np
import glob, os, csv, time
import pandas as pd
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
        s.flag_pandas_convert = 0
        s.flag_od_analysis = 0

    def basic_analysis(s):
        """
        Analyze basic stats.
        """
        df = s.W.analyzer.od_to_pandas()

        s.trip_completed = np.sum(df["completed_trips"])
        s.trip_all = np.sum(df["total_trips"])
        
        s.total_distance_traveled = np.sum(df["average_distance_traveled_per_veh"]*df["total_trips"])

        if s.trip_completed:
            s.total_travel_time = np.sum(df["completed_trips"]*df["average_travel_time"])
            s.average_travel_time = s.total_travel_time/s.trip_completed
            s.total_delay = np.sum(df["completed_trips"]*(df["average_travel_time"]-df["free_travel_time"]))
            s.average_delay = s.total_delay/s.trip_completed
        else:
            s.total_travel_time = -1
            s.average_travel_time = -1
            s.total_delay = -1
            s.average_delay = -1


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
    def print_simple_stats(s, force_print=False):
        """
        Prints basic statistics of simulation result.

        Parameters
        ----------
        force_print : bool, optional
            print the stats regardless of the value of `print_mode`
        """
        s.W.print("results:")
        s.W.print(f" average speed:\t {s.average_speed:.1f} m/s")
        s.W.print(" number of completed trips:\t", s.trip_completed, "/", s.trip_all)
        #s.W.print(" number of completed trips:\t", s.trip_completed, "/", len(s.W.VEHICLES)*s.W.DELTAN)
        if s.trip_completed > 0:
            s.W.print(f" total travel time:\t\t {s.total_travel_time:.1f} s")
            s.W.print(f" average travel time of trips:\t {s.average_travel_time:.1f} s")
            s.W.print(f" average delay of trips:\t {s.average_delay:.1f} s")
            s.W.print(f" delay ratio:\t\t\t {s.average_delay/s.average_travel_time:.3f}")
        s.W.print(f" total distance traveled:\t {s.total_distance_traveled:.1f} m")

        if force_print == 1 and s.W.print_mode == 0:
            print("results:")
            print(f" average speed:\t {s.average_speed:.1f} m/s")
            print(" number of completed trips:\t", s.trip_completed, "/", s.trip_all)
            #print(" number of completed trips:\t", s.trip_completed, "/", len(s.W.VEHICLES)*s.W.DELTAN)
            if s.trip_completed > 0:
                print(f" total travel time:\t\t {s.total_travel_time:.1f} s")
                print(f" average travel time of trips:\t {s.average_travel_time:.1f} s")
                print(f" average delay of trips:\t {s.average_delay:.1f} s")
                print(f" delay ratio:\t\t\t {s.average_delay/s.average_travel_time:.3f}")
            print(f" total distance traveled:\t {s.total_distance_traveled:.1f} m")


    def comp_route_travel_time(s, t, route):
        pass


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


    def vehicles_to_pandas(s):
        """
        Compute the detailed vehicle travel logs and return as a pandas DataFrame.

        Returns
        -------
        pd.DataFrame
            A DataFrame containing the travel logs of vehicles, with the columns:
            
            - 'name': the name of the vehicle (platoon).
            - 'dn': the platoon size.
            - 'orig': the origin node of the vehicle's trip.
            - 'dest': the destination node of the vehicle's trip.
            - 't': the timestep.
            - 'link': the link the vehicle is on (or relevant status).
            - 'x': the position of the vehicle on the link.
            - 's': the spacing of the vehicle.
            - 'v': the speed of the vehicle.
        """
        if s.W.vehicle_logging_timestep_interval != 1:
            warnings.warn("vehicle_logging_timestep_interval is not 1. The output data is not exactly accurate.", LoggingWarning)

        if s.flag_pandas_convert == 0:
            out = [["name", "dn", "orig", "dest", "t", "link", "x", "s", "v"]]
            for veh in s.W.VEHICLES.values():
                for i in range(len(veh.log_t)):
                    if veh.log_state[i] in ("wait", "run", "end", "abort"):
                        if veh.log_link[i] != -1:
                            linkname = veh.log_link[i].name
                        else:
                            if veh.log_state[i] == "wait":
                                linkname = "waiting_at_origin_node"
                            elif veh.log_state[i] == "abort":
                                linkname = "trip_aborted"
                            else:
                                linkname = "trip_end"
                        veh_dest_name = None
                        if veh.dest != None:
                            veh_dest_name = veh.dest.name
                        out.append([veh.name, s.W.DELTAN, veh.orig.name, veh_dest_name, veh.log_t[i], linkname, veh.log_x[i], veh.log_s[i], veh.log_v[i]])
            s.df_vehicles = pd.DataFrame(out[1:], columns=out[0])

            s.flag_pandas_convert = 1
        return s.df_vehicles

    def log_vehicles_to_pandas(s):
        """
        Same to `vehicles_to_pandas`, just for backward compatibility.
        """
        return s.vehicles_to_pandas()

    def vehicle_trip_to_pandas(s):
        """
        Compute the vehicle trip summary and return as a pandas DataFrame.

        Returns
        -------
        pd.DataFrame
            A DataFrame containing the trip summary of the vehicle trip logs, with the columns:
            
            - 'name': the name of the vehicle (platoon).
            - 'orig': the origin node of the vehicle's trip.
            - 'dest': the destination node of the vehicle's trip.
            - 'departure_time': the departure time of the vehicle.
            - 'final_state': the final state of the vehicle.
            - 'travel_time': the travel time of the vehicle.
            - 'average_speed': the average speed of the vehicle.
            - 'distance_traveled': the distance traveled by the vehicle.
        """
        out = [["name", "orig", "dest", "departure_time", "final_state", "travel_time", "average_speed", "distance_traveled"]]
        for veh in s.W.VEHICLES.values():
            veh_dest_name = veh.dest.name if veh.dest != None else None
            veh_state = veh.log_state[-1]
            veh_ave_speed = np.average([v for v in veh.log_v if v != -1])
            veh_dist_traveled = veh.distance_traveled

            out.append([veh.name, veh.orig.name, veh_dest_name, veh.departure_time*s.W.DELTAT, veh_state, veh.travel_time, veh_ave_speed, veh_dist_traveled])
        
        s.df_vehicle_trip = pd.DataFrame(out[1:], columns=out[0])
        return s.df_vehicle_trip

    def gps_like_log_to_pandas(s):
        """
        Generate GPS-like log (x and y in the coordinate system used for Node) of vehicles and return as a pandas DataFrame.

        Returns
        -------
        pd.DataFrame
        """
        out = [["name", "t", "x", "y", "v"]]
        for veh in s.W.VEHICLES.values():
            for i,t in enumerate(veh.log_t):
                x, y = veh.get_xy_coords(t)
                if (x, y) == (-1, -1):
                    continue
                v = veh.log_v[i]
                out.append([veh.name, t, x, y, v])
        s.df_gps_like_log = pd.DataFrame(out[1:], columns=out[0])
        return s.df_gps_like_log

    def basic_to_pandas(s):
        """
        Comutes the basic stats and return as a pandas DataFrame.

        Returns
        -------
        pd.DataFrame
        """
        out = [["total_trips", "completed_trips", "total_travel_time", "average_travel_time", "total_delay", "average_delay"], [s.trip_all, s.trip_completed, s.total_travel_time, s.average_travel_time, s.total_delay, s.average_delay]]

        s.df_basic = pd.DataFrame(out[1:], columns=out[0])
        return s.df_basic

    def od_to_pandas(s):
        """
        Compute the OD-specific stats and return as a pandas DataFrame.

        Returns
        -------
        pd.DataFrame
        """

        s.od_analysis()

        out = [["orig", "dest", "total_trips", "completed_trips", "free_travel_time", "average_travel_time", "stddiv_travel_time",  "shortest_distance", "average_distance_traveled_per_veh", "stddiv_distance_traveled_per_veh"]]
        for o,d in s.od_trips.keys():
            out.append([o.name, d.name, s.od_trips[o,d], s.od_trips_comp[o,d], s.od_tt_free[o,d], s.od_tt_ave[o,d], s.od_tt_std[o,d], s.od_dist_min[o,d], s.od_dist_ave[o,d], s.od_dist_std[o,d]])

        s.df_od = pd.DataFrame(out[1:], columns=out[0])
        return s.df_od
    
    def areas2areas_to_pandas(s, areas, area_names=None):
        """
        Compute the area-wise OD-specific stats and return a pandas DataFrame. It analyzes travel stats between areas (set of nodes).
        
        Parameters
        ----------
        areas : list
            The list of areas. Each area is defined as a list of nodes. The items of area can be Node objects or names of Nodes.
        area_names : list, optional
            The list of names of areas.
            
        Returns
        -------
        pd.DataFrame
        """
        df = s.od_to_pandas()

        o_name_rec = []
        d_name_rec = []
        total_trips_rec = []
        completed_trips_rec = []
        average_travel_time_rec = []
        stddiv_travel_time_rec = []
        average_distance_traveled_rec = []
        stddiv_distance_traveled_rec = []

        average_free_travel_time_rec = []
        average_shortest_distance_rec = []

        areas = [[s.W.get_node(n).name for n in area] for area in areas]
        if area_names == None: 
            area_names = [f"area {i} including {areas[i][0]}" for i in range(len(areas))]

        for i, origs in enumerate(areas):
            for j, dests in enumerate(areas):
                o_name = area_names[i]
                d_name = area_names[j]

                # print(o_name, d_name)

                # group by area: average travel time from origs to dests
                rows = df["orig"].isin(origs) & df["dest"].isin(dests)
                total_tripss = np.array(df["total_trips"][rows])
                average_travel_times = np.array(df["average_travel_time"][rows])
                completed_tripss = np.array(df["completed_trips"][rows])
                var_travel_times = np.array(df["stddiv_travel_time"][rows])**2
                distance_traveleds = np.array(df["average_distance_traveled_per_veh"][rows])
                var_distance_traveleds = np.array(df["stddiv_distance_traveled_per_veh"][rows])**2

                free_travel_time_times = np.array(df["free_travel_time"][rows])
                shortest_distances = np.array(df["shortest_distance"][rows])

                # print(f"{total_tripss = }")
                # print(f"{average_travel_times = }")
                # print(f"{completed_tripss = }")
                # print(f"{var_travel_times = }")
                # print(f"{distance_traveleds = }")
                # print(f"{var_distance_traveleds = }")

                total_trips = total_tripss.sum()
                completed_trips = completed_tripss.sum()

                if total_trips:
                    average_travel_time = (completed_tripss*average_travel_times).sum()/completed_trips
                    var_travel_time = (completed_tripss*var_travel_times).sum()/completed_trips    #wrong! there is a correct formula. TODO: implement
                    stddiv_travel_time = np.sqrt(var_travel_time)

                    average_shortest_distance = (total_tripss*shortest_distances).sum()/total_trips
                else:
                    continue
                    # average_travel_time = np.nan
                    # var_travel_time = np.nan
                    # stddiv_travel_time = np.nan
                    # average_shortest_distance = np.nan

                if completed_trips:
                    average_distance_traveled = (total_tripss*distance_traveleds).sum()/total_trips
                    var_distance_traveled = (total_tripss*distance_traveleds).sum()/total_trips    #wrong!
                    stddiv_distance_traveled = np.sqrt(var_distance_traveled)

                    average_free_travel_time = (completed_tripss*free_travel_time_times).sum()/completed_trips
                else:
                    average_distance_traveled = np.nan
                    var_distance_traveled = np.nan
                    stddiv_distance_traveled = np.nan
                    average_free_travel_time = np.nan

                # print(f"{total_trips = }")
                # print(f"{completed_trips = }")
                # print(f"{average_travel_time = }")
                # print(f"{stddiv_travel_time = }")
                # print(f"{average_distance_traveled = }")
                # print(f"{stddiv_distance_traveled = }")

                o_name_rec.append(o_name)
                d_name_rec.append(d_name)
                total_trips_rec.append(total_trips)
                completed_trips_rec.append(completed_trips)
                average_travel_time_rec.append(average_travel_time)
                stddiv_travel_time_rec.append(stddiv_travel_time)
                average_distance_traveled_rec.append(average_distance_traveled)
                stddiv_distance_traveled_rec.append(stddiv_distance_traveled)
                average_free_travel_time_rec.append(average_free_travel_time)
                average_shortest_distance_rec.append(average_shortest_distance)

        out = [["origin_area", "destination_area", "total_trips", "completed_trips", "average_travel_time", "average_free_travel_time", "average_distance_traveled", "average_shortest_distance"]]
        out += [[o_name_rec[i], d_name_rec[i], total_trips_rec[i], completed_trips_rec[i], average_travel_time_rec[i], average_free_travel_time_rec[i], average_distance_traveled_rec[i], average_shortest_distance_rec[i]] for i in range(len(o_name_rec))]
        
        s.df_areas2areas = pd.DataFrame(out[1:], columns=out[0])
        return s.df_areas2areas

    def area_to_pandas(s, areas, area_names=None, border_include=True):
        """
        Compute traffic stats in area and return as pandas.DataFrame.

        Parameters
        ----------
        areas : list
            The list of areas. Each area is defined as a list of nodes. The items of area can be Node objects or names of Nodes.
        area_names : list, optional
            The list of names of areas.
        border_include : bool, optional
            If set to True, the links on the border of the area are included in the analysis. Default is True.

        Returns
        -------
        pd.DataFrame
        """

        # Precompute DataFrames
        df_links = s.W.analyzer.link_to_pandas()
        df_veh_link = s.W.analyzer.vehicles_to_pandas().drop_duplicates(subset=['name', 'link'])

        # Prepare areas as sets for fast lookup
        areas_set = [{s.W.get_node(n).name for n in area} for area in areas]

        # Initialize result lists
        n_links_rec = []
        traffic_volume_rec = []
        vehicles_remain_rec = []
        total_travel_time_rec = []
        average_delay_rec = []
        average_speed_rec = []
        vehicle_density_rec = []

        # Vectorized approach to process all areas at once
        for area_set in areas_set:
            if border_include:
                rows = df_links["start_node"].isin(area_set) | df_links["end_node"].isin(area_set)
            else:
                rows = df_links["start_node"].isin(area_set) & df_links["end_node"].isin(area_set)

            links = df_links.loc[rows, "link"].unique()

            n_links = links.size
            traffic_volume = df_veh_link[df_veh_link["link"].isin(links)]["name"].nunique() * s.W.DELTAN
            vehicles_remain = df_links.loc[rows, "vehicles_remain"].sum()

            if traffic_volume > 0:
                traffic_volume_rows = (
                            df_links.loc[rows, "traffic_volume"] - df_links.loc[rows, "vehicles_remain"]).values
                total_travel_time = np.sum(df_links.loc[rows, "average_travel_time"].values * traffic_volume_rows)
                total_free_time = np.sum(df_links.loc[rows, "free_travel_time"].values * traffic_volume_rows)
                average_delay = max(total_travel_time / total_free_time - 1, 0)

                # Average speed calculation: total distance / total time
                total_distance = np.sum(df_links.loc[rows, "length"].values * traffic_volume_rows)
                average_speed = total_distance / total_travel_time if total_travel_time > 0 else np.nan

                # Vehicle density calculation: total number of vehicles / total link length
                total_link_length = df_links.loc[rows, "length"].sum()
                vehicle_density = traffic_volume / total_link_length if total_link_length > 0 else np.nan
            else:
                total_travel_time = 0
                total_free_time = 0
                average_delay = np.nan
                average_speed = np.nan
                vehicle_density = np.nan

            # Append the results to lists
            n_links_rec.append(n_links)
            traffic_volume_rec.append(traffic_volume)
            vehicles_remain_rec.append(vehicles_remain)
            total_travel_time_rec.append(total_travel_time)
            average_delay_rec.append(average_delay)
            average_speed_rec.append(average_speed)
            vehicle_density_rec.append(vehicle_density)

        # Create DataFrame from the results
        df_result = pd.DataFrame({
            "area": area_names,
            "n_links": n_links_rec,
            "traffic_volume": traffic_volume_rec,
            "vehicles_remain": vehicles_remain_rec,
            "total_travel_time": total_travel_time_rec,
            "average_delay": average_delay_rec,
            "average_speed": average_speed_rec,
            "vehicle_density": vehicle_density_rec,
        })

        s.df_area = df_result
        return s.df_area

    def vehicle_groups_to_pandas(s, groups, group_names=None):
        """
        Computes the stats of vehicle group and return as a pandas DataFrame.

        Parameters
        ----------
        groups : list
            The list of vehicle groups. Each group is defined as a list of vehicle object.
        group_names : list, optional
            The list of names of vehicle groups.
        
        Returns
        -------
        pd.DataFrame
        """
        df_od = s.W.analyzer.od_to_pandas()

        if group_names == None: 
            group_names = [f"group {i} including {groups[0].name}" for i in range(len(groups))]

        total_trip_rec = []
        completed_trip_rec = []
        average_travel_time_rec = []
        average_delay_rec = []
        std_delay_rec = []
        average_traveled_distance_rec = []
        average_detour_rec = []
        std_detour_rec = []
        averae_speed_rec = []
        std_speed_rec = []
        for i, group in enumerate(groups):
            total_trips = 0
            completed_trips = 0
            travel_times = []
            delays = []
            traveled_distances = []
            detours = []
            speeds = []


            for veh in group:

                total_trips += 1
                if veh.state == "end":
                    completed_trips += 1
                    travel_times.append(veh.travel_time)
                    traveled_distances.append(veh.distance_traveled)
                    
                    free_travel_time = df_od["free_travel_time"][(df_od["orig"]==veh.orig.name) & (df_od["dest"]==veh.dest.name)].values[0]
                    shortest_distance = df_od["shortest_distance"][(df_od["orig"]==veh.orig.name) & (df_od["dest"]==veh.dest.name)].values[0]

                    delays.append(veh.travel_time/free_travel_time)
                    detours.append(veh.distance_traveled/shortest_distance)

                    speeds.append(veh.distance_traveled/veh.travel_time)

                #print(f"{group_names[i]=}, {np.average(travel_times)=}, {np.average(traveled_distances)=}, {np.average(delays)=}, {np.average(detours)=}, {np.std(delays)=}, {np.std(detours)=}, {np.average(speeds)}, {np.std(speeds)}")

            total_trip_rec.append(total_trips)
            completed_trip_rec.append(completed_trips)
            if completed_trips > 0:
                average_travel_time_rec.append(np.average(travel_times))
                average_delay_rec.append(np.average(delays))
                std_delay_rec.append(np.std(delays))
                average_traveled_distance_rec.append(np.average(traveled_distances))
                average_detour_rec.append(np.average(detours))
                std_detour_rec.append(np.std(detours))
                averae_speed_rec.append(np.average(speeds))
                std_speed_rec.append(np.std(speeds))
            else:
                average_travel_time_rec.append(np.nan)
                average_delay_rec.append(np.nan)
                std_delay_rec.append(np.nan)
                average_traveled_distance_rec.append(np.nan)
                average_detour_rec.append(np.nan)
                std_detour_rec.append(np.nan)
                averae_speed_rec.append(np.nan)
                std_speed_rec.append(np.nan)

        df = pd.DataFrame({
            "group": group_names,
            "total_trips": total_trip_rec,
            "completed_trips": completed_trip_rec,
            "average_travel_time": average_travel_time_rec,
            "average_delay_ratio": average_delay_rec,
            "std_delay_ratio": std_delay_rec,
            "average_traveled_distance": average_traveled_distance_rec,
            "average_detour_ratio": average_detour_rec,
            "std_detour_ratio": std_detour_rec,
            "average_speed": averae_speed_rec,
            "std_speed": std_speed_rec,
        })

        s.df_vehicle_groups = df
        
        return s.df_vehicle_groups

    def mfd_to_pandas(s, links=None):
        """
        Compute the MFD-like stats and return as a pandas DataFrame.

        Returns
        -------
        pd.DataFrame
        """
        if links == None:
            links = s.W.LINKS
        s.compute_mfd(links)
        links = [s.W.get_link(link) for link in links]
        links = frozenset(links)

        out = [["t", "network_k", "network_q"]]
        for i in lange(s.W.K_AREA):
            out.append([i*s.W.EULAR_DT, s.W.K_AREA[links][i], s.W.Q_AREA[links][i]])
        s.df_mfd = pd.DataFrame(out[1:], columns=out[0])
        return s.df_mfd

    def link_to_pandas(s):
        """
        Converts the link-level analysis results to a pandas DataFrame.

        Returns
        -------
        pd.DataFrame
        """
        s.link_analysis_coarse()

        out = [["link", "start_node", "end_node", "traffic_volume", "vehicles_remain", "free_travel_time", "average_travel_time", "stddiv_travel_time", "delay_ratio", "length"]]
        for l in s.W.LINKS:
            out.append([l.name, l.start_node.name, l.end_node.name, s.linkc_volume[l], s.linkc_remain[l], s.linkc_tt_free[l], s.linkc_tt_ave[l], s.linkc_tt_std[l], s.linkc_tt_ave[l]/s.linkc_tt_free[l], l.length])
        s.df_linkc = pd.DataFrame(out[1:], columns=out[0])
        return s.df_linkc

    def link_traffic_state_to_pandas(s):
        """
        Compute the traffic states in links and return as a pandas DataFrame.

        Returns
        -------
        pd.DataFrame
        """
        s.compute_edie_state()

        out = [["link", "t", "x", "delta_t", "delta_x", "q", "k", "v"]]
        for l in s.W.LINKS:
            for i in range(l.k_mat.shape[0]):
                for j in range(l.k_mat.shape[1]):
                    out.append([l.name, i*l.edie_dt, j*l.edie_dx, l.edie_dt, l.edie_dx, l.q_mat[i,j], l.k_mat[i,j], l.v_mat[i,j]])
        s.df_link_traffic_state = pd.DataFrame(out[1:], columns=out[0])
        return s.df_link_traffic_state

    def link_cumulative_to_pandas(s):
        """
        Compute the cumulative counts etc. in links and return as a pandas DataFrame.

        Returns
        -------
        pd.DataFrame
        """
        out = [["link", "t", "arrival_count", "departure_count", "actual_travel_time", "instantanious_travel_time"]]
        for link in s.W.LINKS:
            for i in range(s.W.TSIZE):
                out.append([link.name, i*s.W.DELTAT, link.cum_arrival[i], link.cum_departure[i], link.traveltime_actual[i], link.traveltime_instant[i]])
        s.df_link_cumulative = pd.DataFrame(out[1:], columns=out[0])
        return s.df_link_cumulative

    @catch_exceptions_and_warn()
    def output_data(s, fname=None):
        """
        Save all results to CSV files. This is obsolute; not all functions are implemented.
        """
        if fname == None:
            fname = f"out{s.W.name}/data"
        s.basic_to_pandas().to_csv(fname+"_basic.csv", index=False)
        s.od_to_pandas().to_csv(fname+"_od.csv", index=False)
        s.mfd_to_pandas().to_csv(fname+"_mfd.csv", index=False)
        s.link_to_pandas().to_csv(fname+"_link.csv", index=False)
        s.link_traffic_state_to_pandas().to_csv(fname+"_link_traffic_state.csv", index=False)
        s.vehicles_to_pandas().to_csv(fname+"_vehicles.csv", index=False)
