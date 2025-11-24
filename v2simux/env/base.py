"""
V2SimUX RL Environment
This module defines a Gym environment for V2SimUX simulations, allowing
reinforcement learning agents to interact with EV charging station scenarios.
"""
import gzip
import os
import shutil
import time
import cloudpickle
import dill
import gymnasium as gym
import v2simux as vx
import numpy as np
from itertools import chain
from typing import Any, Callable, Dict, List, Union
from pathlib import Path

ObsRes = dict[str, np.ndarray]
RewardFunction = Callable[[int, 'V2SimUXEnv', vx.V2SimInstance], float]

def mean(it):
    total = 0
    count = 0
    for x in it:
        total += x
        count += 1
    return total / count if count > 0 else 0.0

def default_reward_fn(current_time: int, env: 'V2SimUXEnv', sim: vx.V2SimInstance) -> float:
    speed = sim.traffic_simulator.get_average_speed() # Average speed of all vehicles, m/s
    pc = sim.fcs.get_Pc(3600) # Charging power, kW
    queue_len = sim.fcs.get_veh_count() # Number of vehicles waiting to charge
    return - (speed + 10 * (max(pc) - min(pc)) + (max(queue_len) - min(queue_len)))

_STATE_CACHE:Dict[str, Any] = {}

class V2SimUXEnv(gym.Env):
    def __load_case(self):
        # Load the simulation case from the specified directory
        if os.path.exists(self.output_dir):
            import shutil
            shutil.rmtree(self.output_dir)

        if self.case_dir in _STATE_CACHE:
            plg_state, v2sim_state, ux_state = _STATE_CACHE[self.case_dir]
        else:
            p = Path(self.case_dir) / vx.SAVED_STATE_FOLDER
            with gzip.open(p / vx.PLUGINS_FILE, "rb") as f:
                plg_state = f.read()
            with gzip.open(p / vx.TRAFFIC_INST_FILE_NAME, "rb") as f:
                v2sim_state = f.read()
            with gzip.open(p / vx.WORLD_FILE_NAME, "rb") as f:
                ux_state = f.read()
            _STATE_CACHE[self.case_dir] = (plg_state, v2sim_state, ux_state)

        self.__inst = vx.V2SimInstance(
            self.case_dir, outdir_direct = self.output_dir,
            traffic_step = self.traffic_step_len,
            end_time = self.end_time,
            log = "",
            silent = True,
            seed = 0,
            _unsafe_traffic_state_to_load = dill.loads(ux_state),
            _unsafe_inst_state_to_load = cloudpickle.loads(v2sim_state),
            _unsafe_plugin_state_to_load = dill.loads(plg_state)
        )

        self.__t = self.__inst.ctime

    def __init__(self,
            case_dir: Union[str, Path],
            output_dir: Union[str, Path] = "./output",
            reward_fn: RewardFunction = default_reward_fn,
            traffic_step_len: int = 10,
            traffic_steps_per_rl_step: int = 6 * 10, # 10 minutes
            end_time: int = 3600,
        ):
        """
        Initialize the V2SimUX environment.
        Parameters:
        - case_dir (str): Directory containing the simulation case.
        - output_dir (str): Directory to store output data.
        - reward_fn (Callable): Function to compute the reward.
        - traffic_step_len (int): Length of each traffic simulation step in seconds.
        - traffic_steps_per_rl_step (int): How much traffic steps each RL step includes.
        - end_time (int): Total simulation time in seconds.
        """
        super(V2SimUXEnv, self).__init__()
        self.case_dir = str(case_dir)
        self.case_state = str(Path(case_dir) / "saved_state")
        self.output_dir = str(output_dir)
        self.traffic_step_len = traffic_step_len
        self.traffic_steps_per_rl_step = traffic_steps_per_rl_step
        self.end_time = end_time
        self.reset_count = 0
        self.__reward_fn = reward_fn

        obs, info = self.reset()

        N = len(self.__inst.fcs)

        # Define action and observation space
        # They must be gym.spaces objects
        # Example for using discrete actions:
        self.action_space = gym.spaces.Box(low=0.0, high=5.0, shape=(N,), dtype=np.float32)
        # Example for using box observation space:
        self.observation_space = gym.spaces.Dict({
            "net": gym.spaces.Sequence(gym.spaces.Box(low=0.0, high=2.0, shape=(obs["net"].shape[1],), dtype=np.float32)),
            "price": gym.spaces.Box(0.0, 5.0, (1 + N,)),
        })
    
    def close(self):
        if hasattr(self, "_V2SimUXEnv__inst"):
            self.__inst.stop()
    
    def set_reward_function(self, reward_fn: RewardFunction):
        self.__reward_fn = reward_fn

    def compute_reward(self) -> float:
        return self.__reward_fn(self.__t, self, self.__inst)

    def get_info(self):
        return {}
    
    def get_state(self) -> np.ndarray:
        Ws = self.sim.traffic_simulator
        avg_speed = Ws.get_average_speed() / 15.0  # assuming max speed 15 m/s
        road_density = (l.density for l in Ws.links())
        road_avg_soc = (mean(self.sim.vehicles[v.name].SOC for v in l.vehicles) for l in Ws.links())
        fcs_usage = (fc.veh_count() / fc.slots for fc in self.sim.fcs)
        fcs_avg_soc = (mean(v.SOC for v in fc.vehicles()) for fc in self.sim.fcs)
        fcs_load = (fc.Pc_MW for fc in self.sim.fcs)

        return np.fromiter(chain([self.norm_time, avg_speed], road_density, road_avg_soc, fcs_usage, fcs_avg_soc, fcs_load), dtype=np.float32)

    @property
    def sim(self):
        return self.__inst
    
    @property
    def ctime(self):
        return self.__t
    
    @property
    def norm_time(self):
        return self.__t / self.end_time
    
    def __wrap_obs(self, states: list[np.ndarray]) -> ObsRes:
        return {
            "net": np.stack(states),
            "price": np.array([self.norm_time] + self.sim.fcs.get_prices_at(self.__t), dtype=np.float32),
        }
    
    def step(self, action: np.ndarray):
        assert self.action_space.contains(action), "Action out of bounds: {}".format(action)
        for i, v in enumerate(action):
            self.__inst.fcs[i].pbuy.setOverride(v)
        
        until_s = self.__t + self.traffic_step_len * self.traffic_steps_per_rl_step
        states = []
        while self.__t < until_s:
            self.__inst.step()
            states.append(self.get_state())
            self.__t = self.__inst.ctime
        
        terminated = self.__t >= self.end_time
        truncated = False

        reward = self.compute_reward()
        obs = self.__wrap_obs(states)
        info = self.get_info()
        return obs, reward, terminated, truncated, info
    
    def reset(self, *, seed = None, options = None):
        self.close()
        self.__load_case()

        until_s = self.__t + self.traffic_step_len * self.traffic_steps_per_rl_step
        states = []
        while self.__t < until_s:
            self.__inst.step()
            states.append(self.get_state())
            self.__t = self.__inst.ctime
        
        assert self.__t < self.end_time, f"Simulation ended during reset: {self.__t} < {self.end_time}."

        obs = self.__wrap_obs(states)
        info = self.get_info()
        self.reset_count += 1
        return obs, info
    
    @property
    def time(self) -> int:
        return self.__t


__all__ = ["V2SimUXEnv", "RewardFunction", "default_reward_fn", "ObsRes"]