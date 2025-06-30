import re
from importlib.metadata import distribution, PackageNotFoundError
from typing import List, Tuple, Optional

def _parse_requirement(line: str) -> Optional[Tuple[str, Optional[str]]]:
    line = line.strip()
    if not line or line.startswith(('#')):
        return None
    
    match = re.match(r'^([a-zA-Z0-9\-_\.]+)([=<>!~]=?.*)?$', line)
    if not match:
        return None
    
    package = match.group(1).lower()
    version_spec = match.group(2).strip() if match.group(2) else None
    return package, version_spec

def _version_satisfies(installed_version: str, version_spec: str) -> bool:
    from packaging import version
    from packaging.specifiers import SpecifierSet

    try:
        spec = SpecifierSet(version_spec)
        return spec.contains(version.parse(installed_version))
    except:
        return False

def _check_requirements(requirements_file: str) -> List[Tuple[str, str, str]]:
    violations = []
    
    try:
        with open(requirements_file, 'r') as f:
            requirements = [_parse_requirement(line) for line in f]
            requirements = [r for r in requirements if r is not None]
    except FileNotFoundError:
        print(f"Error: {requirements_file} not found")
        return violations
    
    for package, version_spec in requirements:
        try:
            dist = distribution(package)
            installed_version = dist.version
            
            if version_spec and not _version_satisfies(installed_version, version_spec):
                violations.append((package, version_spec, installed_version))
                
        except PackageNotFoundError:
            violations.append((package, version_spec, "NOT INSTALLED"))
    
    return violations

def check_requirements(file = 'requirements.txt'):
    violations = _check_requirements(file)
    
    if not violations: return
    print("Some packages do not meet the requirements:")
    
    max_name_len = max(len(v[0]) for v in violations)
    max_spec_len = max(len(v[1] or 'any') for v in violations)
    
    for package, spec, installed in violations:
        if installed == "NOT INSTALLED":
            print(f"  {package:<{max_name_len}} - Required: {spec or 'any':<{max_spec_len}} | Current: Not installed")
        else:
            print(f"  {package:<{max_name_len}} - Required: {spec or 'any':<{max_spec_len}} | Current: {installed}")
    
    print("Please install them via 'pip install -r requirements.txt'")
    exit(1)

def check_requirements_gui(file = 'requirements.txt'):
    violations = _check_requirements(file)
    
    if not violations: return

    import tkinter as tk
    from tkinter import scrolledtext
    import subprocess
    import sys, os
    import threading
    
    root = tk.Tk()
    root.title("Requirements Checker")

    msg = "Some packages do not meet the requirements:\n\n"
    max_name_len = max(len(v[0]) for v in violations)
    max_spec_len = max(len(v[1] or 'any') for v in violations)

    for package, spec, installed in violations:
        if installed == "NOT INSTALLED":
            msg += f"{package:<{max_name_len}} - Required: {spec or 'any':<{max_spec_len}} | Current: Not installed\n"
        else:
            msg += f"{package:<{max_name_len}} - Required: {spec or 'any':<{max_spec_len}} | Current: {installed}\n"

    command = f"{sys.executable} -m pip install -r {file}"
    msg += f"\nPlease install them via '{command}'"

    text = scrolledtext.ScrolledText(root, width=80, height=15)
    text.insert(tk.END, msg)
    text.config(state=tk.DISABLED)
    text.pack(padx=10, pady=10)

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=(0, 10))

    btn = tk.Button(btn_frame, text="Exit", command=root.destroy)
    btn.pack(side=tk.LEFT, padx=5)

    close = True
    def run_command():
        for widget in btn_frame.winfo_children():
            widget.pack_forget()
        installing_label = tk.Label(btn_frame, text="Installing...", fg="blue")
        installing_label.pack(side=tk.LEFT, padx=5)
        root.update()

        def install_and_restart():
            nonlocal close
            close = False
            subprocess.call(command, shell=True)
            root.destroy()
            os.execl(sys.executable, sys.executable, *sys.argv)

        threading.Thread(target=install_and_restart, daemon=True).start()

    install_btn = tk.Button(btn_frame, text="Install and Retry", command=run_command)
    install_btn.pack(side=tk.LEFT, padx=5)

    root.mainloop()
    if close: exit(1)

if __name__ == "__main__":
    check_requirements()
    print("All packages meet the requirments.")