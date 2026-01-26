from pathlib import Path
from setuptools import find_packages, setup

README = Path(__file__).parent / "README.md"

setup(
    name="ambermeta",
    version="0.1.0",
    description="Simulation provenance extraction utilities for AMBER molecular dynamics runs.",
    long_description=README.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    python_requires=">=3.8",
    packages=find_packages(include=["ambermeta", "ambermeta.*"]),
    extras_require={
        "netcdf": ["netCDF4>=1.6", "scipy>=1.8", "numpy>=1.23"],
        "tui": ["textual>=0.40.0"],
        "tests": ["pytest>=7"],
        "all": ["netCDF4>=1.6", "scipy>=1.8", "numpy>=1.23", "textual>=0.40.0"],
    },
    entry_points={"console_scripts": ["ambermeta=ambermeta.cli:main"]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
