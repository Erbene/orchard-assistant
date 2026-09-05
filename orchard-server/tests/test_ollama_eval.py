from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agent.ollama import chat_model
from app.config import Settings
from eval import report
from eval.harness import eval_settings


def test_chat_model_propagates_execution_options() -> None:
    settings = Settings(
        ollama_num_gpu=999,
        ollama_num_thread=16,
        ollama_keep_alive="10m",
    )
    with patch("app.agent.ollama.ChatOllama") as constructor:
        constructor.return_value = MagicMock()
        chat_model(
            settings,
            model="qwen3:8b",
            temperature=0.1,
            timeout=42.0,
            num_predict=123,
        )

    constructor.assert_called_once_with(
        model="qwen3:8b",
        base_url=settings.ollama_base_url,
        temperature=0.1,
        client_kwargs={"timeout": 42.0},
        num_gpu=999,
        num_thread=16,
        keep_alive="10m",
        num_predict=123,
    )


def test_role_models_remain_backward_compatible(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL", "fallback:model")
    for name in (
        "AGRONOMIST_MODEL",
        "CARE_PLAN_MODEL",
        "FOREMAN_MODEL",
        "IRRIGATION_MODEL",
        "JUDGE_MODEL",
        "GROUNDING_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.agronomist_model == "fallback:model"
    assert settings.care_plan_model == "fallback:model"
    assert settings.foreman_model == "fallback:model"
    assert settings.irrigation_model == "fallback:model"
    assert settings.judge_model == "fallback:model"
    assert settings.grounding_model == "fallback:model"


def test_eval_overrides_subject_without_changing_graders() -> None:
    settings = eval_settings(agent_model="gemma3:4b", ollama_num_gpu=0)
    assert settings.agent_model == "gemma3:4b"
    assert settings.judge_model == "qwen2.5:7b-instruct"
    assert settings.grounding_model == "qwen2.5:7b-instruct"
    assert settings.ollama_num_gpu == 0


def test_report_keeps_timing_and_run_metadata() -> None:
    rows = [
        {
            "id": "probe",
            "channel": "chat",
            "category": "routing",
            "exact_fails": [],
            "judge": None,
            "grounding": None,
            "error": None,
            "timing_ms": {
                "agent": 125.0,
                "judge": 0.0,
                "grounding": 0.0,
                "total": 150.0,
            },
        }
    ]
    _, summary = report.render(rows, metadata={"run_label": "cpu-probe"})
    assert summary["metadata"]["run_label"] == "cpu-probe"
    assert summary["timing_ms"]["agent"] == 125.0
    assert summary["rows"][0]["timing_ms"]["total"] == 150.0


def test_eval_cli_maps_gpu_and_model_overrides() -> None:
    from eval import __main__ as cli

    with (
        patch(
            "sys.argv",
            [
                "python -m eval",
                "--profile",
                "gpu",
                "--num-thread",
                "16",
                "--agent-model",
                "qwen3:8b",
                "--skip-judge",
            ],
        ),
        patch(
            "eval.__main__.run",
            new=MagicMock(return_value={"passed": True}),
        ) as run_mock,
        patch("eval.__main__.asyncio.run", side_effect=lambda value: value),
        pytest.raises(SystemExit) as exited,
    ):
        cli.main()

    assert exited.value.code == 0
    kwargs = run_mock.call_args.kwargs
    assert kwargs["num_gpu"] == 999
    assert kwargs["num_thread"] == 16
    assert kwargs["model_overrides"]["agent_model"] == "qwen3:8b"
    assert kwargs["skip_judge"] is True
