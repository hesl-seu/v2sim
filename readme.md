# V2Sim Family: Open-Source V2G Simulation Platform in Urban Power and Transportation Network

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

# V2Sim: The Microscopic Version

[Click here to read the Wiki](https://github.com/fmy-xfk/v2sim/wiki) 

V2Sim is a microscopic V2G simulation platform in urban power and transportation network. It is open-source under BSD license. 

+ **Note**: Current code of V2Sim is ahead of the paper described. The exact older code used in the paper is [here](https://github.com/fmy-xfk/v2sim/commit/940ebd5d988f53fde90f4d83d107f136334952f9). The code used in [arXiv](https://arxiv.org/abs/2412.09808) is the initial commit.

+ **Note 2**: Code of PDN part is not included in the repository, it is stored in another repository: [FPowerKit](https://gitee.com/fmy_xfk/fpowerkit).

## Quick Start

### A. Setup the environment

NOTE: We do not recommend use conda or other virtual environment, because some users have reported that libsumo may not work normally in these environments. 

1. Setup Python: Visit `https://www.python.org/download` to get Python (version >=3.8 is required. Older version cannot run this program normally).

2. Setup SUMO: Visit `https://eclipse.dev/sumo/` to get SUMO (version 1.19 and above are recommended). Note: This step can be skipped if you do not want to edit the road network.

3. Setup necessary packages. Ensure you have installed `pip` together with Python. Note: As for package `libsumo`, its version must be same as the vesion of SUMO!
```bash
pip install -r requirements.txt
```

5. Download this repo. You can directly download this repo by clicking the `download` button on this page. Or you can setup `git` and clone this repo by the following command. The official tutorial about using `git` is [here](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git).
```bash
git clone https://github.com/fmy-xfk/v2sim.git
```

### B. Create a case
There are 3 pre-defined cases in the `cases` folder. You can exploit the 3 cases directly, or create a new case from scratch.

The following is a full tutorial for creating a case:

1. Download transportation network: Use the OSMWebWizard provided by SUMO to download the road network. 

|Do NOT add vehicles|Only preserve 'highway'|
|---|---|
|![alt text](docs/1.png)|![alt text](docs/2.png)|

Copy your case generated with OSMWebWizard to a proper place. Then run `gui_main.py` in the command prompt by:
```bash
python gui_main.py
```
* **Notice:** Double click to open this file is **NOT** recommended since many users have reported it doesn't work as expected.

Click the `Project` menu and open the folder you have created. You will see something like this:
![alt text](docs/3.png)

2. Download charging station positions: If the area you downloaded is in **China Mainland**, you can download charging station positions in this program. Otherwise, please skip this step.
+ Switch to `CS Downloader` page and type an AMap(Chinese: 高德地图) developer key in the given input box. **ATTENTION: You must apply for a key for web service (Chinese: Web服务) on the [AMap official site](https://lbs.amap.com/). This function will never work without a key.** 
+ Click `Download` to get CS positions from AMap. Please wait patiently while downloading the CS positions. If there are too many CSs in the given area, they may not be all downloaded due to the restriction of AMap.
+ A successful result is shown below (The address are all Chinese since they are located in China):

![alt text](docs/4.png)

+ After download the CS positions, please close the project editor and reopen it to avoid any potential error in the editor.

3. Generate charging stations: Switch to `Fast CS` and `Slow CS` respectively to generate differnt types of charging stations. We strongly recommend you to generate CS from the downloaded positions if you are using a real-world road network. Click the `Generate` button to generate CS.

+ Do **NOT** click `Generate` repeatedly even if it seems not working. The progress will be shown in the command prompt instead of popping up another window.

+ **Generating Fast CS is neccessary**, while generating slow CS is not.

+ A successful result is like this:

![alt text](docs/5.png)

4. **Edit grid**: Switch to `Network` page to view the road netowrk (in blue) and distribution network (in black). Hold the mouse's right button to pan. Distribution network can be moved and edited by left click. **However, editing road network is not available here. Please use SUMO NetEdit.**

![alt text](docs/11.png)

(Slim rectangle = Bus, Triangle = PV / Wind turbine, Square = Energy Stoarge, Circle = Generator)

5. **Generate vehicles**: Switch to `Vehicles` page to generate vehicles. We strongly recommend you to generate trips from the buildings' contours and types if you are using a real-world road network. 

+ Do **NOT** click `Generate` repeatedly even if it seems not working. The progress will be shown in the command prompt instead of popping up another window.

6. **Start simulation**: Make sure the `FCS`, `SCS`,` Road Network`, and `Vehicles` are not `None` in the left column. Then go back to `Simulation` page, tick your desired statistic items, and click `Start Simulation!`.


### C. Simulation
The window will shut down once you clicked `Start Simulation!`. Please wait patiently during simulation. It may cost several hours when simulate a large real-world network. You can watch the progress and estimated time required displayed in the command prompt.

If you want to run several simulation parallelly (which can fully utilize your CPU), you can use `gui_para.py`. This function is quite useful 
when you want to change a specific parameter to measure its implication. Like the following image:
![alt text](docs/10.png)

### D. View the results
After the simulation is done, run `gui_viewer.py` and open the case. The results is in the case folder, with a subfolder named `results`. It will be something like this:

![alt text](docs/6.png)

#### Plotting
Tick the items you want to draw the corresponding figures. Click the button `Plot` to draw figures. Figures of results will be stored in `results\<case_name>\figures`.

**NOTE:**  Some items may not be available becasuse the corresponding statistic item is not selected when configuring the project, and thus it is not produced. 

**Compare two results:** Use `gui_cmp.py` to show two results in the same page, which makes it easier for you to identify the difference. Just like the following image:

![gui_cmp](docs/9.png)

**Better Plotting:** The GUI version of plotting is quite limited. You can visit [Wiki](https://github.com/fmy-xfk/v2sim/wiki) for better plotting tools: `cmd_advplot.py` and `cmd_plot.py`. The former one provides highly-customizable plotting experience, while the latter one enables plotting for batch of result folders.

#### Grid Information
You can also collect the data of the power grid at a specific time in page `Grid`. Enter the time point and then click `Collect`.

![alt text](docs/7.png)

#### Trips viewer
Trips are also counted in `Trips` page. You can filter them by giving the conditions in the bar attached to the bottom of the window. You can also save the filtered results to a specific file.

![alt text](docs/8.png)

#### State viewer
If you have ticked "Save state ..." before simulation, the state will be saved in the result folder. You can go through the status of FCS, SCS, and EV in the page. 

![alt text](docs/12.png)