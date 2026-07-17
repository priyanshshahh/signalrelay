from __future__ import annotations

from types import SimpleNamespace

import pytest

import main as main_module
import agents.feature_agent as feature_agent
import pipelines.pipeline_runner as pipeline_runner


class _FakeFeatureAgent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.output_paths = {"artifact": "ok"}
        self.metrics = {
            "market_rows": 100,
            "onchain_rows": 40,
            "full_rows": 100,
            "final_kept_feature_count": 25,
        }

    def execute(self, max_retries: int = 1):
        return True


def test_cmd_features_runs_unified_feature_agent(monkeypatch, capsys):
    monkeypatch.setattr(main_module, "_get_cfg", lambda: {"_project_root": ".", "paths": {}})
    # main.cmd_features imports the unified FeatureAgent from agents.feature_agent.
    monkeypatch.setattr(feature_agent, "FeatureAgent", _FakeFeatureAgent)

    main_module.cmd_features(SimpleNamespace())
    output = capsys.readouterr().out

    assert "[features] Done." in output
    assert "FullRows=100" in output


class _FakeRunner:
    def __init__(self, cfg):
        self.cfg = cfg

    def run_full_pipeline(self):
        return {
            "universe": True,
            "market_data": True,
            "onchain": True,
            "clean": True,
            "features": True,
            "labels": True,
            "models": True,
            "portfolio": True,
            "backtest": True,
        }


def test_cmd_full_requires_all_stage_success(monkeypatch, capsys):
    monkeypatch.setattr(main_module, "_get_cfg", lambda: {"_project_root": ".", "paths": {}})
    monkeypatch.setattr(pipeline_runner, "PipelineRunner", _FakeRunner)

    main_module.cmd_full(SimpleNamespace())
    output = capsys.readouterr().out

    assert "[full] Pipeline completed successfully." in output


class _FailingRunner(_FakeRunner):
    def run_full_pipeline(self):
        results = super().run_full_pipeline()
        results["models"] = False
        return results


def test_cmd_full_exits_on_failed_stage(monkeypatch):
    monkeypatch.setattr(main_module, "_get_cfg", lambda: {"_project_root": ".", "paths": {}})
    monkeypatch.setattr(pipeline_runner, "PipelineRunner", _FailingRunner)

    with pytest.raises(SystemExit) as exc:
        main_module.cmd_full(SimpleNamespace())

    assert exc.value.code == 1
