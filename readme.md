# V2Sim Family

> Open-Source V2G Simulation Platform in Urban Power and Transportation Network

**Documents:** https://hesl-seu.github.io/v2sim-wiki

V2Sim family includes several open-source software for coupled urban power and transportation network. They are different in the transportation simulation part.

+ **V2Sim**: Use SUMO for **MICROSCOPIC** traffic simulation. It could identify the microscopic motion of a single vehicle, including its lane, speed, accerlation, etc. This version is suitable if your research concerns the implication of delicate motion of EVs on power grid. (Link: [V2Sim](https://github.com/hesl-seu/v2sim/))

+ **V2Sim-UX**: Use UXsim for **MESOCOPIC** traffic simulation. It runs much faster than the microscopic version, and can be accelerated furthermore with free-threading Python (3.14+). This version is suitable if your research need fast iterations and focus on the overall implication of the traffic flow. (Please scroll down to read instructions.)

If you are using V2Sim family, please cite the paper:
```
@ARTICLE{10970754,
  author={Qian, Tao and Fang, Mingyu and Hu, Qinran and Shao, Chengcheng and Zheng, Junyi},
  journal={IEEE Transactions on Smart Grid}, 
  title={V2Sim: An Open-Source Microscopic V2G Simulation Platform in Urban Power and Transportation Network}, 
  year={2025},
  volume={16},
  number={4},
  pages={3167-3178},
  keywords={Vehicle-to-grid;Partial discharges;Microscopy;Batteries;Planning;Discharges (electric);Optimization;Vehicle dynamics;Transportation;Roads;EV charging load simulation;microscopic EV behavior;vehicle-to-grid;charging station fault sensing},
  doi={10.1109/TSG.2025.3560976}}
```
Paper link for the microscopic version: https://ieeexplore.ieee.org/document/10970754

## V2Sim-UX: The Mesoscopic Version

V2Sim-UX is a mesoscopic V2G simulation platform in urban power and transportation network. It is open-source under BSD license. The traffic simulation is based on [UXsim](https://github.com/toruseo/UXsim).

## Quick start
Visit our documents to see the quick start guide!
Link: https://hesl-seu.github.io/v2sim-wiki/#/v2simux/quick-start (English)