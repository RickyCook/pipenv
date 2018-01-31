# -*- coding: utf-8 -*-
"""import contextlib
import codecs
import os
import sys
import shutil
import signal
import time
import tempfile
from glob import glob
import json as simplejson

import urllib3
import background
import click
import click_completion
import crayons
import dotenv
import delegator
import pexpect
import requests
import pip
import pipfile
import pipdeptree
import requirements
import semver
import flake8.main.cli
from pipreqs import pipreqs
from blindspin import spinner
from urllib3.exceptions import InsecureRequestWarning
from pip.req.req_file import parse_requirements
from click_didyoumean import DYMCommandCollection
from .project import Project
from .utils import (
    convert_deps_from_pip, convert_deps_to_pip, is_required_version,
    proper_case, pep423_name, split_file, merge_deps, resolve_deps, shellquote, is_vcs,
    python_version, suggest_package, find_windows_executable, is_file,
    prepare_pip_source_args, temp_environ, is_valid_url, download_file,
    get_requirement, need_update_check, touch_update_stamp
)"""
import sys
import crayons
import click
import click_completion
import os
import delegator
from .__version__ import __version__
from . import pep508checker, progress
from . import environments
from .environments import (
    PIPENV_COLORBLIND, PIPENV_NOSPIN, PIPENV_SHELL_FANCY,
    PIPENV_VENV_IN_PROJECT, PIPENV_TIMEOUT, PIPENV_SKIP_VALIDATION,
    PIPENV_HIDE_EMOJIS, PIPENV_INSTALL_TIMEOUT, PYENV_ROOT,
    PYENV_INSTALLED, PIPENV_YES, PIPENV_DONT_LOAD_ENV,
    PIPENV_DEFAULT_PYTHON_VERSION, PIPENV_MAX_SUBPROCESS,
    PIPENV_DONT_USE_PYENV, SESSION_IS_INTERACTIVE, PIPENV_USE_SYSTEM,
    PIPENV_DOTENV_LOCATION, PIPENV_SHELL
)

# Backport required for earlier versions of Python.
if sys.version_info < (3, 3):
    from backports.shutil_get_terminal_size import get_terminal_size
else:
    from shutil import get_terminal_size


xyzzy = """
 _______   __                                           __
/       \ /  |                                         /  |
$$$$$$$  |$$/   ______    ______   _______   __     __ $$ |
$$ |__$$ |/  | /      \  /      \ /       \ /  \   /  |$$ |
$$    $$/ $$ |/$$$$$$  |/$$$$$$  |$$$$$$$  |$$  \ /$$/ $$ |
$$$$$$$/  $$ |$$ |  $$ |$$    $$ |$$ |  $$ | $$  /$$/  $$/
$$ |      $$ |$$ |__$$ |$$$$$$$$/ $$ |  $$ |  $$ $$/    __
$$ |      $$ |$$    $$/ $$       |$$ |  $$ |   $$$/    /  |
$$/       $$/ $$$$$$$/   $$$$$$$/ $$/   $$/     $/     $$/
              $$ |
              $$ |
              $$/
"""

# Enable shell completion.
click_completion.init()

# Disable colors, for the soulless.
if PIPENV_COLORBLIND:
    crayons.disable()

# Disable spinner, for cleaner build logs (the unworthy).
if PIPENV_NOSPIN:
    @contextlib.contextmanager  # noqa: F811
    def spinner():
        yield


def load_heavy_command(func):
    from importlib import import_module
    from functools import wraps
    @wraps(func)
    def inner(*args, **kwargs):
        import pipenv.cli_heavy
        heavy_func = getattr(pipenv.cli_heavy, func.__name__)
        return heavy_func(*args, **kwargs)
    return inner


def format_help(help):
    """Formats the help string."""
    help = help.replace('Options:', str(crayons.normal('Options:', bold=True)))

    help = help.replace('Usage: pipenv', str('Usage: {0}'.format(crayons.normal('pipenv', bold=True))))

    help = help.replace('  graph', str(crayons.green('  graph')))
    help = help.replace('  open', str(crayons.green('  open')))
    help = help.replace('  check', str(crayons.green('  check')))
    help = help.replace('  uninstall', str(crayons.yellow('  uninstall', bold=True)))
    help = help.replace('  install', str(crayons.yellow('  install', bold=True)))
    help = help.replace('  lock', str(crayons.red('  lock', bold=True)))
    help = help.replace('  run', str(crayons.blue('  run')))
    help = help.replace('  shell', str(crayons.blue('  shell', bold=True)))
    help = help.replace('  update', str(crayons.yellow('  update')))

    additional_help = """
Usage Examples:
   Create a new project using Python 3.6, specifically:
   $ {1}

   Install all dependencies for a project (including dev):
   $ {2}

   Create a lockfile containing pre-releases:
   $ {6}

   Show a graph of your installed dependencies:
   $ {4}

   Check your installed dependencies for security vulnerabilities:
   $ {7}

   Install a local setup.py into your virtual environment/Pipfile:
   $ {5}

Commands:""".format(
        crayons.red('pipenv --three'),
        crayons.red('pipenv --python 3.6'),
        crayons.red('pipenv install --dev'),
        crayons.red('pipenv lock'),
        crayons.red('pipenv graph'),
        crayons.red('pipenv install -e .'),
        crayons.red('pipenv lock --pre'),
        crayons.red('pipenv check'),
    )

    help = help.replace('Commands:', additional_help)

    return help


def format_pip_error(error):
    error = error.replace('Expected', str(crayons.green('Expected', bold=True)))
    error = error.replace('Got', str(crayons.red('Got', bold=True)))
    error = error.replace('THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE', str(crayons.red('THESE PACKAGES DO NOT MATCH THE HASHES FROM Pipfile.lock!', bold=True)))
    error = error.replace('someone may have tampered with them', str(crayons.red('someone may have tampered with them')))

    error = error.replace('option to pip install', 'option to \'pipenv install\'')
    return error


def format_pip_output(out, r=None):
    def gen(out):
        for line in out.split('\n'):
            # Remove requirements file information from pip output.
            if '(from -r' in line:
                yield line[:line.index('(from -r')]
            else:
                yield line

    out = '\n'.join([l for l in gen(out)])
    return out


# |\/| /\ |) [-   ]3 `/
# . . .-. . . . . .-. .-. . .   .-. .-. .-. .-. .-.
# |<  |-  |\| |\| |-   |  |-|   |(  |-   |   |   /
# ' ` `-' ' ` ' ` `-'  '  ' `   ' ' `-' `-'  '  `-'

def warn_in_virtualenv():
    if PIPENV_USE_SYSTEM:
        # Only warn if pipenv isn't already active.
        if 'PIPENV_ACTIVE' not in os.environ:
            click.echo(
                '{0}: Pipenv found itself running within a virtual environment, '
                'so it will automatically use that environment, instead of '
                'creating its own for any project.'.format(
                    crayons.green('Courtesy Notice')
                ), err=True
            )


def kr_easter_egg(package_name):
    if package_name in ['requests', 'maya', 'crayons', 'delegator.py', 'records', 'tablib', 'background', 'clint']:

        # Windows built-in terminal lacks proper emoji taste.
        if PIPENV_HIDE_EMOJIS:
            click.echo(u'  PS: You have excellent taste!')
        else:
            click.echo(u'  PS: You have excellent taste! ✨ 🍰 ✨')


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.group(invoke_without_command=True, context_settings=CONTEXT_SETTINGS)
@click.option('--update', is_flag=True, default=False, help="Update Pipenv & pip to latest.")
@click.option('--where', is_flag=True, default=False, help="Output project home information.")
@click.option('--venv', is_flag=True, default=False, help="Output virtualenv information.")
@click.option('--py', is_flag=True, default=False, help="Output Python interpreter information.")
@click.option('--envs', is_flag=True, default=False, help="Output Environment Variable options.")
@click.option('--rm', is_flag=True, default=False, help="Remove the virtualenv.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--completion', is_flag=True, default=False, help="Output completion (to be eval'd).")
@click.option('--man', is_flag=True, default=False, help="Display manpage.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--site-packages', is_flag=True, default=False, help="Enable site-packages for the virtualenv.")
@click.option('--jumbotron', is_flag=True, default=False, help="An easter egg, effectively.")
@click.version_option(prog_name=crayons.normal('pipenv', bold=True), version=__version__)
@click.pass_context
def cli(*args, completion=False, **kwargs):
    if completion:
        if PIPENV_SHELL:
            os.environ['_PIPENV_COMPLETE'] = 'source-{0}'.format(PIPENV_SHELL.split(os.sep)[-1])
        else:
            click.echo(
                'Please ensure that the {0} environment variable '
                'is set.'.format(crayons.normal('SHELL', bold=True)), err=True)
            sys.exit(1)

        c = delegator.run('pipenv')
        click.echo(c.out)
        sys.exit(0)

    from pipenv.cli_heavy import cli
    return cli(*args, **kwargs)

@click.command(short_help="Installs provided packages and adds them to Pipfile, or (if none is given), installs all packages.", context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--dev', '-d', is_flag=True, default=False, help="Install package(s) in [dev-packages].")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--system', is_flag=True, default=False, help="System pip management.")
@click.option('--requirements', '-r', nargs=1, default=False, help="Import a requirements.txt file.")
@click.option('--code', '-c', nargs=1, default=False, help="Import from codebase.")
@click.option('--verbose', is_flag=True, default=False, help="Verbose mode.")
@click.option('--ignore-pipfile', is_flag=True, default=False, help="Ignore Pipfile when installing, using the Pipfile.lock.")
@click.option('--sequential', is_flag=True, default=False, help="Install dependencies one-at-a-time, instead of concurrently.")
@click.option('--skip-lock', is_flag=True, default=False, help=u"Ignore locking mechanisms when installing—use the Pipfile, instead.")
@click.option('--deploy', is_flag=True, default=False, help=u"Abort if the Pipfile.lock is out–of–date, or Python version is wrong.")
@click.option('--pre', is_flag=True, default=False, help=u"Allow pre–releases.")
@load_heavy_command
def install():
    pass

@click.command(short_help="Un-installs a provided package and removes it from Pipfile.")
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--system', is_flag=True, default=False, help="System pip management.")
@click.option('--verbose', is_flag=True, default=False, help="Verbose mode.")
@click.option('--lock', is_flag=True, default=True, help="Lock afterwards.")
@click.option('--all-dev', is_flag=True, default=False, help="Un-install all package from [dev-packages].")
@click.option('--all', is_flag=True, default=False, help="Purge all package(s) from virtualenv. Does not edit Pipfile.")
@load_heavy_command
def uninstall():
    pass

@click.command(short_help="Generates Pipfile.lock.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--verbose', is_flag=True, default=False, help="Verbose mode.")
@click.option('--requirements', '-r', is_flag=True, default=False, help="Generate output compatible with requirements.txt.")
@click.option('--dev', '-d', is_flag=True, default=False, help="Generate output compatible with requirements.txt for the development dependencies.")
@click.option('--clear', is_flag=True, default=False, help="Clear the dependency cache.")
@click.option('--pre', is_flag=True, default=False, help=u"Allow pre–releases.")
@load_heavy_command
def lock(three=None, python=False, verbose=False, requirements=False, dev=False, clear=False, pre=False):
    pass


@click.command(short_help="Spawns a shell within the virtualenv.", context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--fancy', is_flag=True, default=False, help="Run in shell in fancy mode (for elegantly configured shells).")
@click.option('--anyway', is_flag=True, default=False, help="Always spawn a subshell, even if one is already spawned.")
@click.argument('shell_args', nargs=-1)
@load_heavy_command
def shell(three=None, python=False, fancy=False, shell_args=None, anyway=False):
    pass

@click.command(
    add_help_option=False,
    short_help="Spawns a command installed into the virtualenv.",
    context_settings=dict(
        ignore_unknown_options=True,
        allow_interspersed_args=False,
        allow_extra_args=True
    )
)
@click.argument('command')
@click.argument('args', nargs=-1)
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@load_heavy_command
def run(command, args, three=None, python=False):
    pass

@click.command(short_help="Checks for security vulnerabilities and against PEP 508 markers provided in Pipfile.",  context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--unused', nargs=1, default=False, help="Given a code path, show potentially unused dependencies.")
@click.option('--style', nargs=1, default=False, help="Given a code path, show Flake8 errors.")
@click.argument('args', nargs=-1)
@load_heavy_command
def check(three=None, python=False, unused=False, style=False, args=None):
    pass

@click.command(short_help=u"Displays currently–installed dependency graph information.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--json', is_flag=True, default=False, help="Output JSON.")
@click.option('--reverse', is_flag=True, default=False, help="Reversed dependency graph.")
@load_heavy_command
def graph():
    pass


@click.command(short_help="View a given module in your editor.", name="open")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.argument('module', nargs=1)
@load_heavy_command
def run_open():
    pass


@click.command(short_help="Uninstalls all packages, and re-installs package(s) in [packages] to latest compatible versions.")
@click.argument('package_name', default=False)
@click.option('--verbose', '-v', is_flag=True, default=False, help="Verbose mode.")
@click.option('--dev', '-d', is_flag=True, default=False, help="Additionally install package(s) in [dev-packages].")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--dry-run', is_flag=True, default=False, help="Just output outdated packages.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--clear', is_flag=True, default=False, help="Clear the dependency cache.")
@click.option('--sequential', is_flag=True, default=False, help="Install dependencies one-at-a-time, instead of concurrently.")
@click.pass_context
@load_heavy_command
def update():
    pass

# Install click commands.
cli.add_command(graph)
cli.add_command(install)
cli.add_command(uninstall)
cli.add_command(update)
cli.add_command(lock)
cli.add_command(check)
cli.add_command(shell)
cli.add_command(run)
cli.add_command(run_open)

# Only invoke the "did you mean" when an argument wasn't passed (it breaks those).
if '-' not in ''.join(sys.argv) and len(sys.argv) > 1:
    cli = DYMCommandCollection(sources=[cli])

if __name__ == '__main__':
    cli()
