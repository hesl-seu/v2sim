'''
This file is used to package the V2Sim core module (exactly the folder "./v2sim") into a distributable format (*.whl).
Note that it will not contain GUI files, external components, command line scripts, or cases.
'''

from setuptools import setup, find_packages

with open("readme.md", "r", encoding="utf8") as f:
    long_description = f.read()

setup(
    name="v2sim",
    version="1.0.0",
    author="fmy_xfk",
    packages=find_packages(include=["v2sim", "v2sim.*"]),
    description="V2Sim: An Open-Source Microscopic V2G Simulation Platform in Urban Power and Transportation Network",
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.12",
    install_requires=[
        "feasytools>=0.0.24",
        "fpowerkit>=0.1.6",
        "gurobipy",
        "numpy",
        "matplotlib",
        "pyproj",
        "requests",
        "pillow",
        "ordered-set"
    ],
    url = "https://github.com/fmy-xfk/v2sim",
    include_package_data=True,
)