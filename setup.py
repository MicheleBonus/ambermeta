from pathlib import Path
from setuptools import find_packages, setup

README = Path(__file__).parent / "README.md"

setup(
    name="ambermeta",
    version="0.2.0",
    description="Simulation provenance extraction utilities for AMBER molecular dynamics runs.",
    long_description=README.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    license="BUSL-1.1",
    python_requires=">=3.8",
    packages=find_packages(include=["ambermeta", "ambermeta.*"]),
    package_data={"ambermeta.gui": ["static/**"]},
    extras_require={
        "netcdf": ["netCDF4>=1.6", "scipy>=1.8", "numpy>=1.23"],
        "tui": ["textual>=0.40.0"],
        "gui": [
            "fastapi>=0.100.0",
            "uvicorn>=0.23.0",
            "websockets>=11.0",
            "python-multipart>=0.0.6",
            "pyyaml>=6.0",
        ],
        "yaml": ["pyyaml>=6.0"],
        "toml": ["tomli>=2.0; python_version < '3.11'"],
        "tests": ["pytest>=7", "pytest-cov>=4.0"],
        "dev": ["black>=23.0", "ruff>=0.1.0", "mypy>=1.0"],
        "all": [
            "netCDF4>=1.6",
            "scipy>=1.8",
            "numpy>=1.23",
            "textual>=0.40.0",
            "fastapi>=0.100.0",
            "uvicorn>=0.23.0",
            "websockets>=11.0",
            "python-multipart>=0.0.6",
            "pyyaml>=6.0",
            "tomli>=2.0; python_version < '3.11'",
        ],
    },
    entry_points={"console_scripts": ["ambermeta=ambermeta.cli:main"]},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "License :: Other/Proprietary License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
        "Topic :: Scientific/Engineering :: Chemistry",
    ],
)
