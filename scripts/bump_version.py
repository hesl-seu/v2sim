#!/usr/bin/env python3
import toml
import re
from pathlib import Path

def bump_version():
    pyproject_path = Path("pyproject.toml")
    
    if not pyproject_path.exists():
        print("pyproject.toml not found")
        return
    
    # 读取 pyproject.toml
    with open(pyproject_path, 'r') as f:
        data = toml.load(f)
    
    # 获取当前版本
    current_version = data['project']['version']
    print(f"Current version: {current_version}")
    
    # 解析版本号 (支持 semver 格式)
    match = re.match(r'(\d+)\.(\d+)\.(\d+)', current_version)
    if match:
        major, minor, patch = map(int, match.groups())
        # 自增修订版本号
        new_version = f"{major}.{minor}.{patch + 1}"
    else:
        # 如果不是标准格式，尝试简单自增
        try:
            new_version = str(float(current_version) + 0.1)
        except:
            print("无法解析版本号格式")
            return
    
    # 更新版本号
    data['project']['version'] = new_version
    
    # 写回文件
    with open(pyproject_path, 'w') as f:
        toml.dump(data, f)
    
    print(f"Bumped version to: {new_version}")

if __name__ == "__main__":
    bump_version()