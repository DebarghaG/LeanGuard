"""Bundle an explicitly supplied native build in a platform wheel.

Editable/source installs remain Python-only. scripts/release.py supplies the binary
and build metadata after verification; installation never downloads executable code.
"""

import os
import shutil
from pathlib import Path

from setuptools import Distribution, setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_py import build_py


class BundleBuild(build_py):
    def run(self):
        super().run()
        destination = Path(self.build_lib) / "leanguard" / "bin"
        if binary := os.environ.get("LEANGUARD_BUNDLE_BINARY"):
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary, destination / "leanguard")
            (destination / "leanguard").chmod(0o755)
            metadata = Path(os.environ["LEANGUARD_BUILD_METADATA"])
            for name in ("build-details.json", "proof-audit.txt", "THIRD_PARTY_NOTICES"):
                shutil.copy2(metadata / name, destination / name)
        elif destination.exists():
            # Reusing a build directory must not leak a previous platform binary.
            shutil.rmtree(destination)


class NativeDistribution(Distribution):
    def has_ext_modules(self):
        return bool(os.environ.get("LEANGUARD_BUNDLE_BINARY"))


class PlatformWheel(bdist_wheel):
    def get_tag(self):
        python, abi, platform = super().get_tag()
        return ("py3", "none", platform) if not self.root_is_pure else (python, abi, platform)


setup(
    distclass=NativeDistribution, cmdclass={"build_py": BundleBuild, "bdist_wheel": PlatformWheel}
)
