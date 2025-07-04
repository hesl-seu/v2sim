import re, sys
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
    
    command = f"{sys.executable} -m pip install -r {file}"
    print(f"Please install them via '{command}'")
    exit(1)

def check_requirements_gui(file = 'requirements.txt'):
    violations = _check_requirements(file)
    
    if not violations: return

    from PyQt5 import QtWidgets
    import subprocess, os, threading

    class ReqCheckerDialog(QtWidgets.QDialog):
        def __init__(self, violations, file, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Requirements Checker")
            self.setFixedSize(600, 300)
            self.close_flag = True

            msg = "Some packages do not meet the requirements:\n\n"
            max_name_len = max(len(v[0]) for v in violations)
            max_spec_len = max(len(v[1] or 'any') for v in violations)
            for package, spec, installed in violations:
                if installed == "NOT INSTALLED":
                    msg += f"{package:<{max_name_len}} - Required: {spec or 'any':<{max_spec_len}} | Current: Not installed\n"
                else:
                    msg += f"{package:<{max_name_len}} - Required: {spec or 'any':<{max_spec_len}} | Current: {installed}\n"
            self.command = f"{sys.executable} -m pip install -r {file}"
            msg += f"\nPlease install them via '{self.command}'"

            layout = QtWidgets.QVBoxLayout(self)
            self.text = QtWidgets.QPlainTextEdit(self)
            self.text.setPlainText(msg)
            self.text.setReadOnly(True)
            layout.addWidget(self.text)

            btn_layout = QtWidgets.QHBoxLayout()
            self.exit_btn = QtWidgets.QPushButton("Exit", self)
            def close(): self.close()
            self.exit_btn.clicked.connect(close)
            btn_layout.addWidget(self.exit_btn)

            self.install_btn = QtWidgets.QPushButton("Install and Retry", self)
            self.install_btn.clicked.connect(self.run_command)
            btn_layout.addWidget(self.install_btn)

            layout.addLayout(btn_layout)

        def run_command(self):
            self.exit_btn.setEnabled(False)
            self.install_btn.setEnabled(False)
            self.text.appendPlainText("\nInstalling...")
            QtWidgets.QApplication.processEvents()

            def install_and_restart():
                self.close_flag = False
                subprocess.call(self.command, shell=True)
                self.accept()
                os.execl(sys.executable, sys.executable, *sys.argv)

            threading.Thread(target=install_and_restart, daemon=True).start()

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    dlg = ReqCheckerDialog(violations, file)
    dlg.exec_()
    close = getattr(dlg, "close_flag", True)
    if close: exit(1)

if __name__ == "__main__":
    check_requirements()
    print("All packages meet the requirments.")