import os
import sys
import shutil
import pathlib
from datetime import datetime
from importlib.util import spec_from_file_location, module_from_spec
from catalyst.utils.misc import import_module


def prepare_modules(expdir, dump_dir=None):
    expdir = expdir[:-1] if expdir.endswith("/") else expdir
    expdir_name = expdir.rsplit("/", 1)[-1]

    if dump_dir is not None:
        current_date = datetime.now().strftime("%y-%m-%d-%H-%M-%S-%M-%f")
        new_src_dir = f"/src-{current_date}/"

        # @TODO: hardcoded
        old_pro_dir = os.path.dirname(os.path.abspath(__file__)) + "/../../"
        new_pro_dir = dump_dir + f"/{new_src_dir}/catalyst/"
        shutil.copytree(old_pro_dir, new_pro_dir)

        old_expdir = os.path.abspath(expdir)
        expdir_ = expdir.rsplit("/", 1)[-1]
        new_expdir = dump_dir + f"/{new_src_dir}/{expdir_}/"
        shutil.copytree(old_expdir, new_expdir)

    pyfiles = list(
        map(lambda x: x.name[:-3],
            pathlib.Path(expdir).glob("*.py"))
    )

    modules = {}
    for name in pyfiles:
        module_name = f"{expdir_name}.{name}"
        module_src = expdir + "/" + f"{name}.py"

        module = import_module(module_name, module_src)
        modules[name] = module

    return modules


def import_experiment_and_runner(exp_dir: pathlib.Path):
    # @TODO: better PYTHONPATH handling
    sys.path.insert(0, str(exp_dir.absolute()))
    sys.path.insert(0, os.path.dirname(str(exp_dir.absolute())))
    s = spec_from_file_location(
        exp_dir.name,
        str(exp_dir.absolute() / "__init__.py"),
        submodule_search_locations=[exp_dir.absolute()]
    )
    m = module_from_spec(s)
    s.loader.exec_module(m)
    sys.modules[exp_dir.name] = m
    Experiment, Runner = m.Experiment, m.Runner
    return Experiment, Runner


def dump_code(expdir, logdir):
    expdir = expdir[:-1] if expdir.endswith("/") else expdir

    current_date = datetime.now().strftime("%y-%m-%d-%H-%M-%S-%M-%f")
    new_src_dir = f"/src-{current_date}/"

    # @TODO: hardcoded
    old_pro_dir = os.path.dirname(os.path.abspath(__file__)) + "/../../"
    new_pro_dir = logdir + f"/{new_src_dir}/catalyst/"
    shutil.copytree(old_pro_dir, new_pro_dir)

    old_expdir = os.path.abspath(expdir)
    expdir_ = expdir.rsplit("/", 1)[-1]
    new_expdir = logdir + f"/{new_src_dir}/{expdir_}/"
    shutil.copytree(old_expdir, new_expdir)
