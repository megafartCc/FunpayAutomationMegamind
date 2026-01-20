from setuptools import find_packages, setup

setup(
    name="pysteamauth",
    version="1.1.2",
    description="Vendored pysteamauth (local copy for FunpaySeller)",
    packages=find_packages(),
    install_requires=[
        "pydantic>=1.9,<2",
        "aiohttp>=3.8,<4",
        "requests>=2.28",
    ],
)
