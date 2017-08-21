#!/usr/bin/env python
try:
    from setuptools import setup, Extension
except ImportError:
    from distutils.core import setup, Extension
import os
import stat
import subprocess
import textwrap
import sys

import platform
is_cpython = platform.python_implementation() == 'CPython'

if sys.platform == "darwin":
    # Don't create resource files on OS X tar.
    os.environ['COPY_EXTENDED_ATTRIBUTES_DISABLE'] = 'true'
    os.environ['COPYFILE_DISABLE'] = 'true'

setup_args = {}

def add_command_class(name, cls):
    cmdclasses = setup_args.get('cmdclass', {})
    cmdclasses[name] = cls
    setup_args['cmdclass'] = cmdclasses

from distutils.command.sdist import sdist as sdist_orig
class sdist(sdist_orig):
    def run(self):
        self.force_manifest = 1
        if (sys.platform != "win32" and
            os.path.isdir('.git')):
            assert os.system("git rev-parse --verify HEAD > .gitrev") == 0
        sdist_orig.run(self)
add_command_class('sdist', sdist)

if sys.version_info[:2] == (3, 2):
    import lib2to3.refactor
    from distutils.command.build_py \
         import build_py_2to3 as build_py
    # need to convert sources to Py3 on installation
    with open('2to3-fixers.txt') as f:
        fixers = [line.strip() for line in f if line.strip()]
    build_py.fixer_names = fixers
    add_command_class("build_py", build_py)

pxd_include_dirs = [
    directory for directory, dirs, files
    in os.walk(os.path.join('Cython', 'Includes'))
    if '__init__.pyx' in files or '__init__.pxd' in files
    or directory == os.path.join('Cython', 'Includes')
    or directory == os.path.join('Cython', 'Includes', 'Deprecated')]

pxd_include_patterns = [
    p+'/*.pxd' for p in pxd_include_dirs ] + [
    p+'/*.pyx' for p in pxd_include_dirs ]

setup_args['package_data'] = {
    'Cython.Plex'     : ['*.pxd'],
    'Cython.Compiler' : ['*.pxd'],
    'Cython.Runtime'  : ['*.pyx', '*.pxd'],
    'Cython.Utility'  : ['*.pyx', '*.pxd', '*.c', '*.h', '*.cpp'],
    'Cython'          : [ p[7:] for p in pxd_include_patterns ],
    }

# This dict is used for passing extra arguments that are setuptools
# specific to setup
setuptools_extra_args = {}

# tells whether to include cygdb (the script and the Cython.Debugger package
include_debugger = sys.version_info[:2] > (2, 5)

if 'setuptools' in sys.modules:
    setuptools_extra_args['zip_safe'] = False
    setuptools_extra_args['entry_points'] = {
        'console_scripts': [
            'cython = Cython.Compiler.Main:setuptools_main',
            'cythonize = Cython.Build.Cythonize:main'
        ]
    }
    scripts = []
else:
    if os.name == "posix":
        scripts = ["bin/cython", 'bin/cythonize']
    else:
        scripts = ["cython.py", "cythonize.py"]

if include_debugger:
    if 'setuptools' in sys.modules:
        setuptools_extra_args['entry_points']['console_scripts'].append(
            'cygdb = Cython.Debugger.Cygdb:main')
    else:
        if os.name == "posix":
            scripts.append('bin/cygdb')
        else:
            scripts.append('cygdb.py')


def compile_cython_modules(profile=False, compile_more=False, cython_with_refnanny=False):
    source_root = os.path.abspath(os.path.dirname(__file__))
    compiled_modules = [
        "Cython.Plex.Scanners",
        "Cython.Plex.Actions",
        "Cython.Compiler.Scanning",
        "Cython.Compiler.Parsing",
        "Cython.Compiler.Visitor",
        "Cython.Compiler.FlowControl",
        "Cython.Compiler.Code",
        "Cython.Runtime.refnanny",
        # "Cython.Compiler.FusedNode",
        "Cython.Tempita._tempita",
    ]
    if compile_more:
        compiled_modules.extend([
            "Cython.Build.Dependencies",
            "Cython.Compiler.Lexicon",
            "Cython.Compiler.ParseTreeTransforms",
            "Cython.Compiler.Nodes",
            "Cython.Compiler.ExprNodes",
            "Cython.Compiler.ModuleNode",
            "Cython.Compiler.Optimize",
            ])

    from distutils.spawn import find_executable
    from distutils.sysconfig import get_python_inc
    pgen = find_executable(
        'pgen', os.pathsep.join([os.environ['PATH'], os.path.join(get_python_inc(), '..', 'Parser')]))
    if not pgen:
        sys.stderr.write("Unable to find pgen, not compiling formal grammar.\n")
    else:
        parser_dir = os.path.join(os.path.dirname(__file__), 'Cython', 'Parser')
        grammar = os.path.join(parser_dir, 'Grammar')
        subprocess.check_call([
            pgen,
            os.path.join(grammar),
            os.path.join(parser_dir, 'graminit.h'),
            os.path.join(parser_dir, 'graminit.c'),
            ])
        cst_pyx = os.path.join(parser_dir, 'ConcreteSyntaxTree.pyx')
        if os.stat(grammar)[stat.ST_MTIME] > os.stat(cst_pyx)[stat.ST_MTIME]:
            mtime = os.stat(grammar)[stat.ST_MTIME]
            os.utime(cst_pyx, (mtime, mtime))
        compiled_modules.extend([
                "Cython.Parser.ConcreteSyntaxTree",
            ])

    defines = []
    if cython_with_refnanny:
        defines.append(('CYTHON_REFNANNY', '1'))

    extensions = []
    for module in compiled_modules:
        source_file = os.path.join(source_root, *module.split('.'))
        if os.path.exists(source_file + ".py"):
            pyx_source_file = source_file + ".py"
        else:
            pyx_source_file = source_file + ".pyx"
        dep_files = []
        if os.path.exists(source_file + '.pxd'):
            dep_files.append(source_file + '.pxd')
        if '.refnanny' in module:
            defines_for_module = []
        else:
            defines_for_module = defines
        extensions.append(Extension(
            module, sources=[pyx_source_file],
            define_macros=defines_for_module,
            depends=dep_files))
        # XXX hack around setuptools quirk for '*.pyx' sources
        extensions[-1].sources[0] = pyx_source_file

    if sys.version_info[:2] == (3, 2):
        # Python 3.2: can only run Cython *after* running 2to3
        build_ext = _defer_cython_import_in_py32(source_root, profile)
    else:
        from Cython.Distutils import build_ext
        if profile:
            from Cython.Compiler.Options import get_directive_defaults
            get_directive_defaults()['profile'] = True
            sys.stderr.write("Enabled profiling for the Cython binary modules\n")

    # not using cythonize() here to let distutils decide whether building extensions was requested
    add_command_class("build_ext", build_ext)
    setup_args['ext_modules'] = extensions


def _defer_cython_import_in_py32(source_root, profile=False):
    # Python 3.2: can only run Cython *after* running 2to3
    # => re-import Cython inside of build_ext
    from distutils.command.build_ext import build_ext as build_ext_orig

    class build_ext(build_ext_orig):
        # we must keep the original modules alive to make sure
        # their code keeps working when we remove them from
        # sys.modules
        dead_modules = []

        def __reimport(self):
            if self.dead_modules:
                return
            # add path where 2to3 installed the transformed sources
            # and make sure Python (re-)imports them from there
            already_imported = [
                module for module in sys.modules
                if module == 'Cython' or module.startswith('Cython.')
            ]
            keep_alive = self.dead_modules.append
            for module in already_imported:
                keep_alive(sys.modules[module])
                del sys.modules[module]
            sys.path.insert(0, os.path.join(source_root, self.build_lib))

        def build_extensions(self):
            self.__reimport()
            if profile:
                from Cython.Compiler.Options import directive_defaults
                directive_defaults['profile'] = True
                print("Enabled profiling for the Cython binary modules")
            from Cython.Build.Dependencies import cythonize
            self.distribution.ext_modules[:] = cythonize(
                self.distribution.ext_modules)
            build_ext_orig.build_extensions(self)

    return build_ext


cython_profile = '--cython-profile' in sys.argv
if cython_profile:
    sys.argv.remove('--cython-profile')

try:
    sys.argv.remove("--cython-compile-all")
    cython_compile_more = True
except ValueError:
    cython_compile_more = False

try:
    sys.argv.remove("--cython-with-refnanny")
    cython_with_refnanny = True
except ValueError:
    cython_with_refnanny = False

try:
    sys.argv.remove("--no-cython-compile")
    compile_cython_itself = False
except ValueError:
    compile_cython_itself = True

if compile_cython_itself and (is_cpython or cython_compile_more):
    compile_cython_modules(cython_profile, cython_compile_more, cython_with_refnanny)

setup_args.update(setuptools_extra_args)

from Cython import __version__ as version


def dev_status():
    if 'b' in version or 'c' in version:
        # 1b1, 1beta1, 2rc1, ...
        return 'Development Status :: 4 - Beta'
    elif 'a' in version:
        # 1a1, 1alpha1, ...
        return 'Development Status :: 3 - Alpha'
    else:
        return 'Development Status :: 5 - Production/Stable'


packages = [
    'Cython',
    'Cython.Build',
    'Cython.Compiler',
    'Cython.Runtime',
    'Cython.Distutils',
    'Cython.Plex',
    'Cython.Tests',
    'Cython.Build.Tests',
    'Cython.Compiler.Tests',
    'Cython.Utility',
    'Cython.Tempita',
    'pyximport',
]

if include_debugger:
    packages.append('Cython.Debugger')
    packages.append('Cython.Debugger.Tests')
    # it's enough to do this for Py2.5+:
    setup_args['package_data']['Cython.Debugger.Tests'] = ['codefile', 'cfuncs.c']

setup(
    name='Cython',
    version=version,
    url='http://cython.org/',
    author='Robert Bradshaw, Stefan Behnel, Dag Seljebotn, Greg Ewing, et al.',
    author_email='cython-devel@python.org',
    description="The Cython compiler for writing C extensions for the Python language.",
    long_description=textwrap.dedent("""\
    The Cython language makes writing C extensions for the Python language as
    easy as Python itself.  Cython is a source code translator based on Pyrex_,
    but supports more cutting edge functionality and optimizations.

    The Cython language is a superset of the Python language (almost all Python
    code is also valid Cython code), but Cython additionally supports optional
    static typing to natively call C functions, operate with C++ classes and
    declare fast C types on variables and class attributes.  This allows the
    compiler to generate very efficient C code from Cython code.

    This makes Cython the ideal language for writing glue code for external
    C/C++ libraries, and for fast C modules that speed up the execution of
    Python code.

    Note that for one-time builds, e.g. for CI/testing, on platforms that are not
    covered by one of the wheel packages provided on PyPI, it is substantially faster
    than a full source build to install an uncompiled (slower) version of Cython with::

        pip install Cython --install-option="--no-cython-compile"

    .. _Pyrex: http://www.cosc.canterbury.ac.nz/greg.ewing/python/Pyrex/
    """),
    license='Apache',
    classifiers=[
        dev_status(),
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 3",
        "Programming Language :: C",
        "Programming Language :: Cython",
        "Topic :: Software Development :: Code Generators",
        "Topic :: Software Development :: Compilers",
        "Topic :: Software Development :: Libraries :: Python Modules"
    ],

    scripts=scripts,
    packages=packages,
    py_modules=["cython"],
    **setup_args
)
