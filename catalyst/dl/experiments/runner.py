from typing import Any, Mapping, Dict, List
from abc import ABC, abstractmethod
from collections import OrderedDict  # noqa F401

import torch
from torch import nn, optim
from torch.utils.data import DataLoader  # noqa F401

from catalyst.dl.callbacks import Callback
from catalyst.dl.state import RunnerState
from catalyst.dl.utils import UtilsFactory
from . import Experiment, SupervisedExperiment

_Model = nn.Module
_Criterion = nn.Module
_Optimizer = optim.Optimizer
# noinspection PyProtectedMember
_Scheduler = optim.lr_scheduler._LRScheduler


class Runner(ABC):

    def __init__(
        self,
        model: nn.Module = None,
        device=None,
    ):
        """
        @TODO: write docs
        """
        # main
        self.model: nn.Module = model
        self.device = device
        self.experiment: Experiment = None
        self.state: RunnerState = None
        self.callbacks: List[Callback] = None

        # additional
        self._check_run = False

        if model is not None and device is None:
            self._prepare_model()

    def _batch2device(self, batch: Mapping[str, Any], device):
        res = {
            key: value.to(device) if torch.is_tensor(value) else value
            for key, value in batch.items()
        }
        return res

    def _prepare_model(self, stage: str = None):
        """
        Inner method for children's classes for model specific initialization.
        As baseline, checks device support and puts model on it.
        :return:
        """

        if stage is not None:
            self.model = self.experiment.get_model(stage)

        self.model, self.device = \
            UtilsFactory.prepare_model(self.model)

    def _prepare_state(self, stage: str):
        migrating_params = {}
        if self.state is not None:
            migrating_params.update({
                "step": self.state.step,
                "epoch": self.state.epoch + 1
            })

        self._prepare_model(stage)
        criterion, optimizer, scheduler = \
            self.experiment.get_model_stuff(self.model, stage)

        self.state = RunnerState(
            stage=stage,
            model=self.model,
            device=self.device,
            criterion=criterion,
            optimizer=optimizer,
            scheduler=scheduler,
            **self.experiment.get_state_params(stage),
            **migrating_params
        )

    def _run_event(self, event: str):

        if self.state is not None and hasattr(self.state, f"on_{event}_pre"):
            getattr(self.state, f"on_{event}_pre")()

        if self.callbacks is not None:
            for callback in self.callbacks:
                getattr(callback, f"on_{event}")(self.state)

        if self.state is not None and hasattr(self.state, f"on_{event}_post"):
            getattr(self.state, f"on_{event}_post")()

    @abstractmethod
    def predict_batch(self, batch: Mapping[str, Any]):
        pass

    def _run_batch(self, batch):
        self.state.step += self.state.batch_size
        batch = self._batch2device(batch, self.device)
        self.state.input = batch
        self.state.output = self.predict_batch(batch)

    def _run_loader(self, loader):
        self.state.batch_size = loader.batch_size
        self.state.step = (
            self.state.step
            or self.state.epoch * len(loader) * self.state.batch_size
        )
        # @TODO: remove time usage, use it under the hood
        self.state.timer.reset()

        self.state.timer.start("base/batch_time")
        self.state.timer.start("base/data_time")

        for i, batch in enumerate(loader):
            batch = self._batch2device(batch, self.device)
            self.state.timer.stop("base/data_time")

            self._run_event("batch_start")

            self.state.timer.start("base/model_time")
            self._run_batch(batch)
            self.state.timer.stop("base/model_time")

            self.state.timer.stop("base/batch_time")
            self._run_event("batch_end")

            self.state.timer.reset()

            if self._check_run and i >= 3:
                break

            self.state.timer.start("base/batch_time")
            self.state.timer.start("base/data_time")

    def _run_epoch(self, loaders):
        # @TODO: better solution with train/inference handling ?
        if not self.state.stage.startswith("infer"):
            assert self.state.valid_loader in loaders.keys(), \
                f"'{self.state.valid_loader}' " \
                f"should be in provided loaders: {list(loaders.keys())}"
        else:
            assert not any(x.startswith("train") for x in loaders.keys()), \
                "for inference no train loader should be passed"

        for loader_name in loaders:
            self.state.loader_name = loader_name
            self.state.loader_len = len(loaders[loader_name])
            self.state.need_backward = loader_name.startswith("train")
            self.model.train(self.state.need_backward)

            self._run_event("loader_start")
            self._run_loader(loaders[loader_name])
            self._run_event("loader_end")

    def _run_stage(self, stage: str):
        loaders = self.experiment.get_loaders(stage)
        self.callbacks = self.experiment.get_callbacks(stage)

        self._prepare_state(stage)
        self.state.stage = stage

        self._run_event("stage_start")
        for epoch in range(self.state.n_epochs):
            self.state.epoch = epoch

            self._run_event("epoch_start")
            self._run_epoch(loaders)
            self._run_event("epoch_end")

            if self._check_run and epoch >= 3:
                break
            if self.state.early_stop:
                self.state.early_stop = False
                break
        self._run_event("stage_end")

    def run_experiment(
        self,
        experiment: Experiment,
        check: bool = False
    ):
        self._check_run = check

        self.experiment = experiment
        for stage in self.experiment.stages:
            self._run_stage(stage)
        return self


class SupervisedRunner(Runner):
    """
    Runner for experiments with supervised model
    """
    _default_experiment = SupervisedExperiment

    def __init__(
        self,
        model: nn.Module = None,
        device=None,
        input_key: str = "features",
        output_key: str = "logits",
        input_target_key: str = "targets",
    ):
        """
        @TODO update docs

        :type output_key: str
        :type input_key: str

        :param input_key: Key in batch dict mapping to model input
        :param output_key: Key in output dict model output will be stored under
        """
        super().__init__(model=model, device=device)
        self.input_key = input_key
        self.output_key = output_key
        self.target_key = input_target_key

    def _batch2device(self, batch: Mapping[str, Any], device):
        if isinstance(batch, (tuple, list)):
            assert len(batch) == 2
            batch = {self.input_key: batch[0], self.target_key: batch[1]}
        batch = super()._batch2device(batch, device)
        return batch

    def predict_batch(self, batch: Mapping[str, Any]):
        output = self.model(batch[self.input_key])
        output = {self.output_key: output}
        return output

    def train(
        self,
        model: _Model,
        criterion: _Criterion,
        optimizer: _Optimizer,
        loaders: "OrderedDict[str, DataLoader]",
        logdir: str,
        callbacks: "List[Callback]" = None,
        scheduler: _Scheduler = None,
        n_epochs: int = 1,
        valid_loader: str = "valid",
        main_metric: str = "loss",
        minimize_metric: bool = True,
        verbose: bool = False,
        state_kwargs: Dict = None,
        check: bool = False
    ):
        experiment = self._default_experiment(
            stage="train",
            model=model,
            loaders=loaders,
            callbacks=callbacks,
            logdir=logdir,
            criterion=criterion,
            optimizer=optimizer,
            scheduler=scheduler,
            n_epochs=n_epochs,
            valid_loader=valid_loader,
            main_metric=main_metric,
            minimize_metric=minimize_metric,
            verbose=verbose,
            state_kwargs=state_kwargs
        )
        self.run_experiment(experiment, check=check)

    def infer(
        self,
        model: _Model,
        loaders: "OrderedDict[str, DataLoader]",
        callbacks: "List[Callback]" = None,
        verbose: bool = False,
        state_kwargs: Dict = None,
        check: bool = False
    ):
        experiment = self._default_experiment(
            stage="infer",
            model=model,
            loaders=loaders,
            callbacks=callbacks,
            verbose=verbose,
            state_kwargs=state_kwargs
        )
        self.run_experiment(experiment, check=check)
