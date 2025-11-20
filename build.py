from pathlib import Path
import os, sys

MODE_LIST = [".dev", "a", "b", "rc", "", ".post"]
MODE_MAP = {m: i for i, m in enumerate(MODE_LIST)}

class MyVersionInfo:
    def __init__(self, major:int, minor:int, patch:int, mode:str, mode_count:int=1):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.mode = mode
        self.mode_count = mode_count

    def __str__(self):
        base_version = f"{self.major}.{self.minor}.{self.patch}"
        if self.mode == "a":
            return f"{base_version}a{self.mode_count}"
        elif self.mode == "b":
            return f"{base_version}b{self.mode_count}"
        elif self.mode == "rc":
            return f"{base_version}rc{self.mode_count}"
        elif self.mode == "":
            return base_version
        elif self.mode == ".post":
            return f"{base_version}.post{self.mode_count}"
        elif self.mode == ".dev":
            return f"{base_version}.dev{self.mode_count}"
        else:
            raise ValueError("Invalid mode")
    
    def increase_count(self):
        if self.mode in ["", ".post"]:
            self.increase_patch()
            self.mode = ".dev"
            self.mode_count = 1
        else:
            self.mode_count += 1
    
    def increase_mode(self):
        new_mode_index = MODE_MAP[self.mode] + 1
        if new_mode_index >= len(MODE_LIST):
            new_mode_index = len(MODE_LIST) - 1
        new_mode = MODE_LIST[new_mode_index]
        self.mode = new_mode
        self.mode_count = 1
    
    def set_mode(self, mode:str):
        assert mode in MODE_LIST, "Invalid mode"
        if mode == ".post":
            self.patch -= 1
            assert self.patch >= 0, "Cannot set to post version from patch 0"
            self.mode = ".post"
            self.mode_count = 1
            return
        else:
            if MODE_MAP[mode] <= MODE_MAP[self.mode]:
                input("Warning: Setting mode to an earlier or same stage. Press Enter to increase patch...")
                self.increase_patch()
            self.mode = mode
            self.mode_count = 1
    
    def increase_patch(self):
        self.patch += 1
        self.mode = ".dev"
        self.mode_count = 1
    
    def increase_minor(self):
        self.minor += 1
        self.patch = 0
        self.mode = ".dev"
        self.mode_count = 1
    
    def increase_major(self):
        self.major += 1
        self.minor = 0
        self.patch = 0
        self.mode = ".dev"
        self.mode_count = 1
    
    def __repr__(self) -> str:
        return str(self)
    
    @staticmethod
    def from_string(version_str:str):
        parts = version_str.strip().split('.')
        major = int(parts[0])
        minor = int(parts[1])
        patch_part = parts[2]
        if 'a' in patch_part:
            patch, rest = patch_part.split('a')
            patch = int(patch)
            mode = 'a'
            mode_count = int(rest)
        elif 'b' in patch_part:
            patch, rest = patch_part.split('b')
            patch = int(patch)
            mode = 'b'
            mode_count = int(rest)
        elif 'rc' in patch_part:
            patch, rest = patch_part.split('rc')
            patch = int(patch)
            mode = 'rc'
            mode_count = int(rest)
        elif len(parts) == 4:
            patch = int(patch_part)
            mode_part = parts[3]
            if mode_part.startswith('dev'):
                mode = '.dev'
                mode_count = int(mode_part[3:])
            elif mode_part.startswith('post'):
                mode = '.post'
                mode_count = int(mode_part[4:])
            else:
                raise ValueError("Invalid version string")
        elif len(parts) == 3:
            patch = int(patch_part)
            mode = ''
            mode_count = 0
        else:
            raise ValueError("Invalid version string")
        
        return MyVersionInfo(major, minor, patch, mode, mode_count)

    
def sync_versions(next_major:bool=False, next_minor:bool=False, next_patch:bool=False, phase:str="<none>", ):
    with open("version.txt", "r") as f:
        VERSION = MyVersionInfo.from_string(f.read().strip())

    if next_major:
        VERSION.increase_major()
    elif next_minor:
        VERSION.increase_minor()    
    elif next_patch:
        VERSION.increase_patch()
    elif phase == "<next>":
        VERSION.increase_mode()
    elif phase in MODE_LIST:
        VERSION.set_mode(phase)
        
    print("Version:", VERSION)

    init_file = "v2sim/__init__.py"
    with open(init_file, 'r') as f:
        content = f.read()
        
        # 检查是否已有 __version__
        if '__version__' in content:
            # 替换现有版本号
            import re
            content = re.sub(
                r'__version__\s*=\s*["\'][^"\']*["\']',
                f'__version__ = "{VERSION}"',
                content
            )
        else:
            # 在文件末尾添加版本号
            content = content.rstrip() + f'\n\n__version__ = "{VERSION}"'
    
    with open(init_file, 'w') as f:
        f.write(content)
    print(f"Updated {init_file} to version {VERSION}")

    try:
        import toml
    except ImportError:
        os.system(f'{sys.executable} -m pip install toml')
        import toml

    with open('pyproject.toml', 'r') as f:
        data = toml.load(f)
    
    if 'project' in data:
        data['project']['version'] = VERSION
    elif 'tool' in data and 'poetry' in data['tool']:
        data['tool']['poetry']['version'] = VERSION
    
    with open('pyproject.toml', 'w') as f:
        toml.dump(data, f)
    
    print(f"Updated {init_file} and pyproject.toml to version {VERSION}")

    VERSION.increase_count()

    with open('version.txt', 'w') as f:
        f.write(str(VERSION))

def ensure_all_v2sim():
    flag = True
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                if Path(path).absolute() == Path(__file__).absolute():
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "v2simux" in content.lower():
                    print(f"Found 'v2simux' in {path}")
                    flag = False
    return flag

def build():
    try:
        import uv
    except ImportError:
        os.system(f'{sys.executable} -m pip install uv')
        import uv
        
    os.system('uv build')
    
if __name__ == "__main__":
    from feasytools import ArgChecker
    args = ArgChecker()
    # Default is dev
    next_major = args.pop_bool("next-major")
    next_minor = args.pop_bool("next-minor")
    if next_minor and next_major:
        raise ValueError("Cannot use --next-major and --next-minor together")
    next_patch = args.pop_bool("next-patch")
    if next_patch and (next_major or next_minor):
        raise ValueError("Cannot use --next-patch with --next-major or --next-minor")
    next_phase = args.pop_bool("next-phase")
    if next_phase:
        set_phase = "<next>"
        assert not (next_major or next_minor or next_patch), "Cannot use --next-phase with --next-major, --next-minor, or --next-patch"
        assert not any(x in args for x in ["set-phase", "dev", "a", "b", "rc", "release", "post"]), "Cannot use --next-phase and --set-phase together"
    set_phase = args.pop_str("set-phase", "<none>")

    if args.pop_bool("dev"): set_phase = ".dev"
    if args.pop_bool("a"): set_phase = "a"
    if args.pop_bool("b"): set_phase = "b"
    if args.pop_bool("rc"): set_phase = "rc"
    if args.pop_bool("release"): set_phase = ""
    if args.pop_bool("post"): set_phase = ".post"

    if len(args) > 0:
        raise ValueError(f"Unknown arguments: {args.keys()}")
    
    assert ensure_all_v2sim(), "Some files still reference v2simux, please fix them before building."
    sync_versions(next_major=next_major, next_minor=next_minor, next_patch=next_patch, phase=set_phase)
    input("All checks passed. Press Enter to start building...")
    build()