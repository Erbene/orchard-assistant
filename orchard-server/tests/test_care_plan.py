"""Care Plan engine: the deterministic size-scaling, the Agronomist draft
(LLM mocked), and the full generate -> baseline -> recurring-task flow against
``orchard_test``."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent import care_plan as cp
from app.agent.agronomist import _CarePlanModel, _PlanItem, rescale_template
from app.core import db
from app.dependencies import get_settings_dep
from app.main import app
from app.repositories.source_repository import SourceRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.task_template_repository import TaskTemplateRepository
from app.repositories.tree_repository import TreeRepository
from app.schemas.care_plan import BaselineAnswer, TaskTemplateUpdate
from app.services.care_plan_service import CarePlanService
from app.services.source_service import SourceService
from app.services.task_service import TaskService
from app.rag.vector_store import get_vector_store

from conftest import stack_settings


# --------------------------------------------------------------------------
# 1. deterministic engine - no DB, no model
# --------------------------------------------------------------------------

def test_canopy_volume_scales_with_size():
    small = cp.canopy_volume_m3(1.0, None)
    big = cp.canopy_volume_m3(4.0, None)
    assert big > small * 10          # volume ~ h^3 (spread tracks height)
    assert cp.canopy_volume_m3(None, None) == pytest.approx(
        cp.canopy_volume_m3(2.0, None)
    )                                # default height when unrecorded
    assert cp.canopy_volume_m3(0.0, None) > 0     # clamped, never zero


def test_scale_is_deterministic_and_size_aware():
    a = cp.scale("fertilize", "standard", height_m=2.0, spread_m=None)
    b = cp.scale("fertilize", "standard", height_m=2.0, spread_m=None)
    assert a == b                                        # pure

    big = cp.scale("fertilize", "standard", height_m=5.0, spread_m=None)
    assert big.estimated_minutes > a.estimated_minutes
    fert_a = next(r for r in a.resource_plan if "fertilizer" in r.name.lower())
    fert_big = next(r for r in big.resource_plan if "fertilizer" in r.name.lower())
    assert fert_big.quantity > fert_a.quantity

    heavy = cp.scale("fertilize", "heavy", height_m=2.0, spread_m=None)
    assert heavy.resource_plan[0].quantity > a.resource_plan[0].quantity


def test_scale_adds_pole_saw_for_tall_trees():
    short = cp.scale("prune", "standard", height_m=2.0, spread_m=None)
    tall = cp.scale("prune", "standard", height_m=4.0, spread_m=None)
    assert "Pole saw" not in short.required_resources
    assert "Pole saw" in tall.required_resources


def test_scale_minutes_snap_to_five():
    for cat in cp.CATEGORIES:
        s = cp.scale(cat, "standard", height_m=3.0, spread_m=2.0)
        assert s.estimated_minutes % 5 == 0 and s.estimated_minutes >= 5


def test_merge_duplicate_fertilize_products():
    n = cp.scale("fertilize", "standard", height_m=3.0, spread_m=None)
    k = cp.scale("fertilize", "light", height_m=3.0, spread_m=None)
    prune = cp.scale("prune", "standard", height_m=3.0, spread_m=None)
    templates = [
        {
            "name": "Nitrogen feed",
            "category": "fertilize",
            "rate_class": "standard",
            "interval_days": 90,
            "priority_score": 6.0,
            "resource_plan": [r.as_dict() for r in n.resource_plan],
            "required_resources": n.required_resources,
            "blocks": [],
            "valid_months": [3, 4, 5],
            "baseline_question": "When did you last fertilize?",
        },
        {
            "name": "Potassium feed",
            "category": "fertilize",
            "rate_class": "light",
            "interval_days": 60,
            "priority_score": 8.0,
            "resource_plan": [r.as_dict() for r in k.resource_plan],
            "required_resources": k.required_resources,
            "blocks": [{"category": "prune", "min_gap_days": 7}],
            "valid_months": [6],
        },
        {
            "name": "Structural prune",
            "category": "prune",
            "rate_class": "standard",
            "interval_days": 365,
            "priority_score": 4.0,
            "resource_plan": [r.as_dict() for r in prune.resource_plan],
            "required_resources": prune.required_resources,
            "blocks": [],
            "valid_months": [],
        },
    ]
    merged = cp.merge_duplicate_product_templates(templates)
    assert len(merged) == 2
    feed = next(t for t in merged if t["category"] == "fertilize")
    assert "Nitrogen feed" in feed["name"] and "Potassium feed" in feed["name"]
    assert feed["priority_score"] == 8.0
    assert feed["interval_days"] == 60
    assert feed["blocks"] == [{"category": "prune", "min_gap_days": 7}]
    assert set(feed["valid_months"]) == {3, 4, 5, 6}
    assert {t["category"] for t in merged} == {"fertilize", "prune"}
    products = [r["name"] for r in feed["resource_plan"] if r["unit"] != "ea"]
    assert products == ["Balanced fertilizer (8-3-9)"]


def test_scale_uses_recommended_product_name():
    defaulted = cp.scale("fertilize", "standard", height_m=3.0, spread_m=None)
    urea = cp.scale(
        "fertilize", "standard", height_m=3.0, spread_m=None, product="22-0-0"
    )
    assert defaulted.resource_plan[0].name == "Balanced fertilizer (8-3-9)"
    assert urea.resource_plan[0].name == "22-0-0"
    assert urea.resource_plan[0].quantity == defaulted.resource_plan[0].quantity
    assert urea.estimated_minutes == defaulted.estimated_minutes


def test_merge_keeps_distinct_fertilizer_products():
    balanced = cp.scale("fertilize", "standard", height_m=3.0, spread_m=None)
    urea = cp.scale(
        "fertilize", "standard", height_m=3.0, spread_m=None, product="22-0-0"
    )
    templates = [
        {
            "name": "Balanced feed",
            "category": "fertilize",
            "rate_class": "standard",
            "interval_days": 90,
            "priority_score": 6.0,
            "resource_plan": [r.as_dict() for r in balanced.resource_plan],
            "required_resources": balanced.required_resources,
            "blocks": [],
            "valid_months": [3, 4, 5],
        },
        {
            "name": "Nitrogen feed",
            "category": "fertilize",
            "rate_class": "standard",
            "interval_days": 90,
            "priority_score": 7.0,
            "resource_plan": [r.as_dict() for r in urea.resource_plan],
            "required_resources": urea.required_resources,
            "blocks": [],
            "valid_months": [3, 4, 5],
        },
    ]
    merged = cp.merge_duplicate_product_templates(templates)
    assert len(merged) == 2
    names = {t["name"] for t in merged}
    assert names == {"Balanced feed", "Nitrogen feed"}


def test_merge_same_analysis_written_differently():
    a = cp.scale("fertilize", "standard", height_m=3.0, spread_m=None)
    b = cp.scale(
        "fertilize",
        "standard",
        height_m=3.0,
        spread_m=None,
        product="8-3-9",
    )
    templates = [
        {
            "name": "Nitrogen feed",
            "category": "fertilize",
            "interval_days": 90,
            "priority_score": 6.0,
            "resource_plan": [r.as_dict() for r in a.resource_plan],
            "blocks": [],
            "valid_months": [],
        },
        {
            "name": "Potassium feed",
            "category": "fertilize",
            "interval_days": 90,
            "priority_score": 5.0,
            "resource_plan": [r.as_dict() for r in b.resource_plan],
            "blocks": [],
            "valid_months": [],
        },
    ]
    merged = cp.merge_duplicate_product_templates(templates)
    assert len(merged) == 1
    assert "Nitrogen" in merged[0]["name"] and "Potassium" in merged[0]["name"]


# --------------------------------------------------------------------------
# 2. service flow - LLM mocked
# --------------------------------------------------------------------------

_DRAFT = _CarePlanModel(items=[
    _PlanItem(name="Nitrogen feed", category="fertilize", rate_class="standard",
              interval_days=90, priority_score=6.0,
              baseline_question="When did you last fertilize?"),
    _PlanItem(name="Structural prune", category="prune", rate_class="light",
              interval_days=365, priority_score=4.0),
    _PlanItem(name="Pest scouting", category="scout", rate_class="standard",
              interval_days=30, priority_score=3.0),
])


@contextmanager
def fake_plan_llm(draft: _CarePlanModel = _DRAFT):
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=draft)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    with patch("app.agent.agronomist.chat_model", return_value=llm):
        yield


async def _link_note(svc: CarePlanService, tree_id: int) -> None:
    source = await svc._sources.ingest_text(
        "notes", "Routine mango care: fertilize in spring, prune after harvest."
    )
    await svc._sources.set_tree_sources(tree_id, [source.id])


def _link_note_http(client: TestClient, tree_id: int) -> None:
    src = client.post(
        "/api/v1/sources",
        data={"name": "notes", "text": "Routine mango care: fertilize in spring."},
    )
    assert src.status_code == 201
    linked = client.put(
        f"/api/v1/trees/{tree_id}/sources",
        json={"source_ids": [src.json()["id"]]},
    )
    assert linked.status_code == 200


def _run(body):
    settings = stack_settings()

    async def _wrap():
        try:
            get_vector_store(settings).clear()
            async with db.connection(settings) as conn:
                trees = TreeRepository(conn)
                templates = TaskTemplateRepository(conn)
                tasks_repo = TaskRepository(conn)
                sources = SourceService(
                    SourceRepository(conn), trees, get_vector_store(settings), settings
                )
                svc = CarePlanService(templates, tasks_repo, trees, sources, settings)
                tasks_svc = TaskService(tasks_repo, trees, templates)
                return await body(conn, trees, templates, tasks_repo, svc, tasks_svc)
        finally:
            await db.dispose_all()

    return asyncio.run(_wrap())


def test_generate_scales_from_height_then_baseline_materialises_tasks():
    async def body(conn, trees, templates, tasks_repo, svc, tasks_svc):
        tid = (await trees.create(
            {"species": "mango", "variety": "Kent", "height_m": 4.0}
        ))["tree_id"]
        await _link_note(svc, tid)

        with fake_plan_llm():
            plan = await svc.generate(tid)

        assert len(plan.templates) == 3
        assert plan.generated and plan.pending_task_count == 0
        # every template gets a baseline question (LLM phrasing or a default)
        assert {q.name for q in plan.baseline_questions} == {
            "Nitrogen feed", "Structural prune", "Pest scouting"
        }
        feed_q = next(q for q in plan.baseline_questions if q.name == "Nitrogen feed")
        assert feed_q.question == "When did you last fertilize?"   # LLM-supplied
        prune_q = next(q for q in plan.baseline_questions if q.name == "Structural prune")
        assert "prune" in prune_q.question.lower()                 # synthesized default
        feed = next(t for t in plan.templates if t.name == "Nitrogen feed")
        assert feed.estimated_minutes > 0
        assert any("fertilizer" in r.name.lower() for r in feed.resource_plan)

        # a taller tree would have produced bigger numbers
        small_tid = (await trees.create(
            {"species": "mango", "variety": "Kent", "height_m": 1.5}
        ))["tree_id"]
        await _link_note(svc, small_tid)
        with fake_plan_llm():
            small_plan = await svc.generate(small_tid)
        small_feed = next(t for t in small_plan.templates if t.name == "Nitrogen feed")
        assert feed.estimated_minutes >= small_feed.estimated_minutes

        # baseline: last fed 10 days ago -> first task due ~ 80 days out
        last = date.today() - timedelta(days=10)
        created = await svc.apply_baseline(
            tid, [BaselineAnswer(template_id=feed.id, last_done=last)]
        )
        assert len(created) == 3
        feed_task = next(t for t in created if t.template_id == feed.id)
        assert feed_task.scheduled_date.date() == last + timedelta(days=90)
        assert feed_task.estimated_minutes == feed.estimated_minutes

        # re-running baseline is idempotent (one open task per template)
        again = await svc.apply_baseline(tid, [])
        assert again == []

        # adjusting a date reschedules the existing open task, no duplicate
        newer = date.today() - timedelta(days=2)
        assert await svc.apply_baseline(
            tid, [BaselineAnswer(template_id=feed.id, last_done=newer)]
        ) == []
        open_feed = await tasks_repo.open_for_template(feed.id)
        assert open_feed["scheduled_date"].date() == newer + timedelta(days=90)
        rows = await tasks_repo.list(tree_id=tid)
        assert len([t for t in rows if t["template_id"] == feed.id]) == 1

    _run(body)


def test_generate_merges_nitrogen_and_potassium_feed():
    dupe = _CarePlanModel(items=[
        _PlanItem(name="Nitrogen feed", category="fertilize", rate_class="standard",
                  interval_days=90, priority_score=6.0),
        _PlanItem(name="Potassium feed", category="fertilize", rate_class="standard",
                  interval_days=90, priority_score=5.0),
        _PlanItem(name="Structural prune", category="prune", rate_class="light",
                  interval_days=365, priority_score=4.0),
    ])

    async def body(conn, trees, templates, tasks_repo, svc, tasks_svc):
        tid = (await trees.create(
            {"species": "mango", "variety": "Kent", "height_m": 3.0}
        ))["tree_id"]
        await _link_note(svc, tid)
        with fake_plan_llm(dupe):
            plan = await svc.generate(tid)
        feeds = [t for t in plan.templates if t.category == "fertilize"]
        assert len(feeds) == 1
        assert "Nitrogen" in feeds[0].name and "Potassium" in feeds[0].name
        products = [r.name for r in feeds[0].resource_plan if r.unit != "ea"]
        assert products == ["Balanced fertilizer (8-3-9)"]
        assert len(plan.templates) == 2

    _run(body)


def test_generate_keeps_distinct_fertilizer_products():
    distinct = _CarePlanModel(items=[
        _PlanItem(name="Nitrogen feed", category="fertilize", rate_class="standard",
                  interval_days=90, priority_score=6.0, product="22-0-0"),
        _PlanItem(name="Balanced feed", category="fertilize", rate_class="standard",
                  interval_days=90, priority_score=5.0, product="8-3-9"),
        _PlanItem(name="Structural prune", category="prune", rate_class="light",
                  interval_days=365, priority_score=4.0),
    ])

    async def body(conn, trees, templates, tasks_repo, svc, tasks_svc):
        tid = (await trees.create(
            {"species": "mango", "variety": "Kent", "height_m": 3.0}
        ))["tree_id"]
        await _link_note(svc, tid)
        with fake_plan_llm(distinct):
            plan = await svc.generate(tid)
        feeds = [t for t in plan.templates if t.category == "fertilize"]
        assert len(feeds) == 2
        products = {r.name for t in feeds for r in t.resource_plan if r.unit != "ea"}
        assert products == {"22-0-0", "8-3-9"}
        assert len(plan.templates) == 3

    _run(body)


def test_rescale_keeps_recommended_product():
    patch = rescale_template(
        {
            "category": "fertilize",
            "rate_class": "heavy",
            "resource_plan": [{"name": "22-0-0", "quantity": 0.4, "unit": "kg"}],
        },
        {"height_m": 3.0, "canopy_spread_m": None},
    )
    assert patch["resource_plan"][0]["name"] == "22-0-0"
    assert patch["resource_plan"][0]["quantity"] > 0.4


def test_edit_template_rescales_and_resyncs_open_task():
    async def body(conn, trees, templates, tasks_repo, svc, tasks_svc):
        tid = (await trees.create(
            {"species": "mango", "variety": "Kent", "height_m": 3.0}
        ))["tree_id"]
        await _link_note(svc, tid)
        with fake_plan_llm():
            plan = await svc.generate(tid)
        feed = next(t for t in plan.templates if t.category == "fertilize")
        await svc.apply_baseline(tid, [])

        # bump to heavy feeder + change interval
        updated = await svc.update_template(
            feed.id, TaskTemplateUpdate(rate_class="heavy", interval_days=60)
        )
        assert updated.estimated_minutes >= feed.estimated_minutes
        heavier = next(r for r in updated.resource_plan if "fertilizer" in r.name.lower())
        lighter = next(r for r in feed.resource_plan if "fertilizer" in r.name.lower())
        assert heavier.quantity > lighter.quantity

        open_task = await tasks_repo.open_for_template(feed.id)
        assert open_task["estimated_minutes"] == updated.estimated_minutes
        assert open_task["scheduled_date"].date() == date.today() + timedelta(days=60)

    _run(body)


def test_complete_respawns_next_from_completion_date():
    """Completing late must cooldown from completed_at, not scheduled_date."""
    frozen = date(2026, 5, 31)

    async def body(conn, trees, templates, tasks_repo, svc, tasks_svc):
        tid = (await trees.create(
            {"species": "mango", "variety": "Kent", "height_m": 2.5}
        ))["tree_id"]
        tmpl = await templates.create(tid, {
            "name": "Pest scouting",
            "category": "scout",
            "rate_class": "standard",
            "interval_days": 30,
            "estimated_minutes": 15,
            "priority_score": 3.0,
            "required_resources": [],
            "resource_plan": [],
            "blocks": [],
        })
        may1 = datetime(2026, 5, 1, tzinfo=timezone.utc)
        await tasks_repo.create({
            "tree_id": tid,
            "template_id": tmpl["id"],
            "action_type": tmpl["name"],
            "status": "pending",
            "priority_score": tmpl["priority_score"],
            "scheduled_date": may1,
            "estimated_minutes": tmpl["estimated_minutes"],
            "required_resources": tmpl["required_resources"],
        })
        open_row = await tasks_repo.open_for_template(tmpl["id"])
        with patch("app.services.task_service._now") as mock_now:
            mock_now.return_value = datetime.combine(
                frozen, datetime.min.time(), tzinfo=timezone.utc
            )
            await tasks_svc.mark_complete(open_row["id"])
        nxt = await tasks_repo.open_for_template(tmpl["id"])
        assert nxt["scheduled_date"].date() >= frozen + timedelta(days=30)

    _run(body)


def test_skip_respawns_from_today_not_completion():
    """Skip must not inherit a completion cooldown."""
    scheduled = date(2026, 5, 1)
    frozen = date(2026, 5, 31)

    async def body(conn, trees, templates, tasks_repo, svc, tasks_svc):
        tid = (await trees.create(
            {"species": "mango", "variety": "Kent", "height_m": 2.5}
        ))["tree_id"]
        tmpl = await templates.create(tid, {
            "name": "Pest scouting",
            "category": "scout",
            "rate_class": "standard",
            "interval_days": 30,
            "estimated_minutes": 15,
            "priority_score": 3.0,
            "required_resources": [],
            "resource_plan": [],
            "blocks": [],
        })
        await tasks_repo.create({
            "tree_id": tid,
            "template_id": tmpl["id"],
            "action_type": tmpl["name"],
            "status": "pending",
            "priority_score": tmpl["priority_score"],
            "scheduled_date": datetime.combine(
                scheduled, datetime.min.time(), tzinfo=timezone.utc
            ),
            "estimated_minutes": tmpl["estimated_minutes"],
            "required_resources": tmpl["required_resources"],
        })
        open_row = await tasks_repo.open_for_template(tmpl["id"])
        with patch("app.services.task_service.date") as mock_date:
            mock_date.today.return_value = frozen
            mock_date.side_effect = lambda *a, **k: date(*a, **k)
            await tasks_svc.skip_task(open_row["id"])
        nxt = await tasks_repo.open_for_template(tmpl["id"])
        assert nxt["scheduled_date"].date() == frozen + timedelta(days=30)

    _run(body)


def test_complete_respawns_next_from_template():
    async def body(conn, trees, templates, tasks_repo, svc, tasks_svc):
        tid = (await trees.create(
            {"species": "mango", "variety": "Kent", "height_m": 2.5}
        ))["tree_id"]
        await _link_note(svc, tid)
        with fake_plan_llm():
            plan = await svc.generate(tid)
        scout = next(t for t in plan.templates if t.category == "scout")
        await svc.apply_baseline(tid, [])

        first = await tasks_repo.open_for_template(scout.id)
        done = await tasks_svc.mark_complete(first["id"])
        assert done.status == "completed"

        nxt = await tasks_repo.open_for_template(scout.id)
        assert nxt is not None and nxt["id"] != first["id"]
        assert nxt["scheduled_date"].date() == date.today() + timedelta(
            days=scout.interval_days
        )

        # skip advances the recurrence too
        skipped = await tasks_svc.skip_task(nxt["id"])
        assert skipped.status == "skipped"
        assert (await tasks_repo.open_for_template(scout.id))["id"] not in (
            first["id"], nxt["id"],
        )

    _run(body)


def test_apply_baseline_safety_skip_after_flowering_cutoff():
    async def body(conn, trees, templates, tasks_repo, svc, tasks_svc):
        tid = (await trees.create({
            "species": "mango", "variety": "Kent", "height_m": 3.0,
            "expected_flowering_month": 9, "expected_harvest_month": 11,
            "expected_flowering_months": [9], "expected_harvest_months": [11],
        }))["tree_id"]
        tmpl = await templates.create(tid, {
            "name": "Nitrogen feed",
            "category": "fertilize",
            "rate_class": "standard",
            "interval_days": 30,
            "estimated_minutes": 20,
            "priority_score": 6.0,
            "required_resources": ["Balanced fertilizer (8-3-9)"],
            "resource_plan": [],
            "valid_months": [],
            "biological_anchor": "flowering",
            "anchor_offset_days": -30,
        })
        last = date(2026, 7, 15)
        await svc.apply_baseline(
            tid, [BaselineAnswer(template_id=tmpl["id"], last_done=last)]
        )
        open_task = await tasks_repo.open_for_template(tmpl["id"])
        assert open_task["scheduled_date"].date() == date(2026, 11, 1)

    _run(body)


def test_delete_template_removes_its_open_task():
    async def body(conn, trees, templates, tasks_repo, svc, tasks_svc):
        tid = (await trees.create({"species": "mango", "variety": "Kent"}))["tree_id"]
        await _link_note(svc, tid)
        with fake_plan_llm():
            plan = await svc.generate(tid)
        await svc.apply_baseline(tid, [])
        victim = plan.templates[0]

        await svc.delete_template(victim.id)
        assert await templates.get(victim.id) is None
        assert await tasks_repo.open_for_template(victim.id) is None
        remaining = await svc.get_plan(tid)
        assert len(remaining.templates) == 2

    _run(body)


def test_update_tree_phenology_month_lists():
    async def body(conn, trees, templates, tasks_repo, svc, tasks_svc):
        tid = (await trees.create(
            {"species": "mango", "variety": "Kent", "height_m": 2.0}
        ))["tree_id"]
        updated = await trees.update(tid, {
            "expected_flowering_months": [3, 9],
            "expected_harvest_months": [6, 12],
            "expected_flowering_month": 3,
            "expected_harvest_month": 6,
        })
        assert updated["expected_flowering_months"] == [3, 9]
        assert updated["expected_harvest_months"] == [6, 12]
        assert updated["expected_flowering_month"] == 3
        plan = await svc.get_plan(tid)
        assert plan.phenology.flowering_months == [3, 9]
        assert plan.phenology.harvest_months == [6, 12]

    _run(body)


# --------------------------------------------------------------------------
# 3. HTTP surface
# --------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path))
    app.dependency_overrides[get_settings_dep] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_care_plan_http_roundtrip(client):
    tree = client.post(
        "/api/v1/trees",
        json={"species": "mango", "variety": "Kent", "height_m": 3.5},
    ).json()
    tid = tree["tree_id"]
    assert tree["height_m"] == 3.5
    _link_note_http(client, tid)

    with fake_plan_llm():
        plan = client.post(f"/api/v1/trees/{tid}/care-plan/generate").json()
    assert len(plan["templates"]) == 3
    assert plan["baseline_questions"][0]["question"] == "When did you last fertilize?"

    tmpl_id = plan["templates"][0]["id"]
    patched = client.patch(
        f"/api/v1/care-plan/templates/{tmpl_id}", json={"priority_score": 9.5}
    )
    assert patched.status_code == 200 and patched.json()["priority_score"] == 9.5

    made = client.post(f"/api/v1/trees/{tid}/care-plan/baseline", json={"answers": []})
    assert made.status_code == 200 and len(made.json()) == 3

    inbox = client.get("/api/v1/tasks").json()
    assert len(inbox) == 3
    assert {t["template_category"] for t in inbox} == {"fertilize", "prune", "scout"}
    assert inbox[0]["priority_score"] >= inbox[-1]["priority_score"]

    first = inbox[0]["id"]
    done = client.post(f"/api/v1/tasks/{first}/complete")
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert len(client.get("/api/v1/tasks").json()) == 3   # respawned

    assert client.delete(f"/api/v1/care-plan/templates/{tmpl_id}").status_code == 204
    assert len(client.get(f"/api/v1/trees/{tid}/care-plan").json()["templates"]) == 2


def test_generate_care_plan_503_when_ollama_down(client):
    tid = client.post(
        "/api/v1/trees", json={"species": "mango", "variety": "Kent"}
    ).json()["tree_id"]
    _link_note_http(client, tid)

    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=llm)
    llm.ainvoke = AsyncMock(side_effect=RuntimeError("connection refused"))
    with patch("app.agent.agronomist.chat_model", return_value=llm):
        r = client.post(f"/api/v1/trees/{tid}/care-plan/generate")
    assert r.status_code == 503


def test_generate_care_plan_422_without_linked_sources(client):
    tid = client.post(
        "/api/v1/trees", json={"species": "mango", "variety": "Kent"}
    ).json()["tree_id"]
    r = client.post(f"/api/v1/trees/{tid}/care-plan/generate")
    assert r.status_code == 422
    assert "knowledge source" in r.json()["detail"].lower()
    assert client.get(f"/api/v1/trees/{tid}/care-plan").json()["generated"] is False
