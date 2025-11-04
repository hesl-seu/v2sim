# V2Sim Family

> Open-Source V2G Simulation Platform in Urban Power and Transportation Network

**Documents:** http://v2sim.heslab.wiki (Backup links: [HTTPS Link](https://hesl-seu.github.io/v2sim-wiki) | [CN Mirror 中文镜像](https://v2sim.myfrank.cn/#/zh_hans/))

V2Sim family includes several open-source software for coupled urban power and transportation network. They are different in the transportation simulation part.

+ **V2Sim**: Use SUMO for **MICROSCOPIC** traffic simulation. It could identify the microscopic motion of a single vehicle, including its lane, speed, accerlation, etc. This version is suitable if your research concerns the implication of delicate motion of EVs on power grid. (Please scroll down to read instructions.)

+ **V2Sim-UX**: Use uxsim for **MESOCOPIC** traffic simulation. It runs very fast with free-threading Python (3.14+). This version is suitable if your research need fast iterations and focus on the overall implication of the traffic flow. (Link: [V2Sim-UX](https://github.com/hesl-seu/v2sim/tree/uxsim))

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

## V2Sim: The Microscopic Version

V2Sim is a microscopic V2G simulation platform in urban power and transportation network. It is open-source under BSD license. 

+ **Note**: Current code of V2Sim is ahead of the paper described. The exact older code used in the paper is [here](https://github.com/fmy-xfk/v2sim/commit/940ebd5d988f53fde90f4d83d107f136334952f9). The code used in [arXiv](https://arxiv.org/abs/2412.09808) is the initial commit.

+ **Note 2**: Code of PDN part is not included in the repository, it is stored in another repository: [FPowerKit](https://gitee.com/fmy_xfk/fpowerkit).

## Quick start
Visit our documents to see the quick start guide!
Link: https://hesl-seu.github.io/v2sim-wiki/#/v2sim/quick-start (English)