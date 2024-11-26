from Cython.Build import cythonize
from setuptools import setup

setup(
    ext_modules = cythonize("1.py")  # Nama file Python yang akan dikompilasi
)