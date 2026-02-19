from setuptools import setup
from Cython.Build import cythonize

setup(
    ext_modules=cythonize([
        "src/label_app.py",
        "src/items.py"
    ]
        , compiler_directives={'language_level': "3"}),
)
