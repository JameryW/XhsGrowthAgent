"""P2c-S4: ``workflow.py`` is the api layer, and it has to stay one.

Three claims, all machine-checked.

**1. The wire shape survived the split.**  ``/status`` had the most to lose --
248 lines, every stage key inline.  ``_STATUS_SHAPE`` is the payload's complete
field shape under a checkpoint that fills every nested stage key.  It was
captured by running ``_status_shape()`` against ``ec64fa86`` (pre-split, with
the patch targets rewritten to that tree's single module) and against this tree;
``diff`` between the two runs was empty.  Values are already pinned field-by-field
by ``test_legacy_read_faces.py``; what this test pins is the *shape*, which is the
ticket's wording ("``/status`` 的响应形状与拆分前逐字段相同").

**2. A handler cannot do anything else.**  Every ``@router.*`` function in
``workflow.py`` is exactly one statement -- ``return await
_wf_<layer>.<same name>(...)`` -- and its signature and docstring are AST-equal
to the implementation's.  So the api layer cannot grow a second responsibility,
and the two sides cannot drift apart, without this test going red.  The handler
count is also checked against what FastAPI actually registered, so a route lost
in the move cannot hide behind a green suite.

**3. The layer table in ``workflow.py``'s own docstring is asserted, not
trusted.**  Same reason ``docs/execution-plane.md``'s anchors are: a published
description that nothing checks rots silently.
"""

from __future__ import annotations

import ast
import copy
import inspect
import re
from importlib import import_module
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes import workflow as api_module
from backend.api.routes.workflow import router as workflow_router

ROUTES_DIR = Path(__file__).resolve().parents[3] / "backend" / "api" / "routes"
API_LAYER = ROUTES_DIR / "workflow.py"

#: The layers that own endpoint implementations.  ``runtime`` / ``artifacts`` /
#: ``models`` sit *below* these -- a handler reaching straight into one of them
#: would mean the layering is broken, so the set is deliberately closed.
IMPLEMENTATION_LAYERS = ("_wf_application", "_wf_actions")

#: ``layer`` -> the role it plays in the table published in ``workflow.py``.
PUBLISHED_LAYERS = {
    "api": "workflow.py",
    "application": "_wf_application.py",
    "runtime": "_wf_runtime.py",
    "artifacts": "_wf_artifacts.py",
    "actions": "_wf_actions.py",
    "models": "_wf_models.py",
}

#: ``(handler, METHOD, path)`` for every route the api layer publishes.  A set of
#: bare paths would not be enough: swapping two handlers' decorators keeps the
#: path set intact while rewiring the wire, so the handler name is part of the key.
PUBLISHED_ROUTES = frozenset(
    {
        ("start_workflow", "POST", "/start"),
        ("get_workflow_status", "GET", "/status/{thread_id}"),
        ("get_checkpoint_history", "GET", "/history/{thread_id}"),
        ("pause_workflow", "POST", "/pause/{thread_id}"),
        ("resume_workflow", "POST", "/resume/{thread_id}"),
        ("recover_workflow", "POST", "/recover/{thread_id}"),
        ("cancel_workflow", "POST", "/cancel/{thread_id}"),
        ("stream_workflow_progress", "GET", "/stream/{thread_id}"),
        ("list_workflows_endpoint", "GET", "/list"),
        ("workflow_account_totals", "GET", "/account-totals"),
        ("delete_workflow", "DELETE", "/{thread_id}"),
        ("retry_ripple_analysis", "POST", "/ripple-retry/{thread_id}"),
        ("extract_brief_file", "POST", "/brief/extract"),
        ("upload_brief_file", "POST", "/brief/upload/{thread_id}"),
        ("export_shooting_plan", "GET", "/brief/export/{thread_id}"),
        ("upload_images", "POST", "/images/upload/{thread_id}"),
        ("trigger_analytics", "POST", "/trigger-analytics/{thread_id}"),
        ("retry_publish", "POST", "/publish-retry/{thread_id}"),
    }
)

#: Every handler is async def, i.e. ast.AsyncFunctionDef -- a sibling of
#: ast.FunctionDef, not a subclass, so both have to be named explicitly.
_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_HTTP_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})

_LAYER_TABLE_ROW = re.compile(r"^\|\s*(\w+)\s*\|\s*``([A-Za-z0-9_.]+)``", re.MULTILINE)


# ── AST helpers ──────────────────────────────────────────────────────────────


def _api_tree() -> ast.Module:
    return ast.parse(API_LAYER.read_text(encoding="utf-8"))


def _is_route_decorator(node: ast.expr) -> bool:
    return _decorator_route(node) is not None


def _decorator_route(node: ast.expr) -> tuple[str, str] | None:
    """``(METHOD, path)`` for ``@router.<verb>("…")``; ``None`` for anything else."""
    if not isinstance(node, ast.Call):
        return None
    target = node.func
    if not (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "router"
        and target.attr in _HTTP_VERBS
    ):
        return None
    if not (node.args and isinstance(node.args[0], ast.Constant)):
        return None
    path = node.args[0].value
    if not isinstance(path, str):
        return None
    return target.attr.upper(), path


def _ast_routes() -> set[tuple[str, str, str]]:
    routes = set()
    for node in _api_tree().body:
        if not isinstance(node, _FUNC):
            continue
        for dec in node.decorator_list:
            route = _decorator_route(dec)
            if route is not None:
                routes.add((node.name, *route))
    return routes


def _live_routes() -> set[tuple[str, str, str]]:
    """What FastAPI actually registered, keyed the same way as ``_ast_routes``."""
    return {
        (route.endpoint.__name__, method.upper(), route.path)
        for route in workflow_router.routes
        for method in route.methods
    }


def _api_handlers() -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    handlers = {
        node.name: node
        for node in _api_tree().body
        if isinstance(node, _FUNC) and any(map(_is_route_decorator, node.decorator_list))
    }
    assert handlers, "no @router.* handler found -- every check below would be vacuous"
    return handlers


def _docstring_node(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Expr | None:
    first = fn.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return first
    return None


def _body_without_docstring(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    return list(fn.body[1:] if _docstring_node(fn) else fn.body)


def _forward_of(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, str]:
    """``(layer_module, attribute)`` for a handler shaped as one forwarding return.

    Raises ``AssertionError`` with the reason when the shape is anything else.
    """
    body = _body_without_docstring(fn)
    assert len(body) == 1 and isinstance(body[0], ast.Return), (
        f"{fn.name}: the body is {len(body)} statement(s) after the docstring; "
        "an api handler is exactly one `return`"
    )
    value = body[0].value
    assert isinstance(value, ast.Await) and isinstance(value.value, ast.Call), (
        f"{fn.name}: returns `{ast.unparse(value)}`; an api handler returns "
        "`await <layer>.<name>(...)`"
    )
    func = value.value.func
    assert isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name), (
        f"{fn.name}: forwards to `{ast.unparse(func)}`; the callee must be `_wf_<layer>.<name>`"
    )
    layer, attr = func.value.id, func.attr
    assert layer in IMPLEMENTATION_LAYERS, (
        f"{fn.name}: forwards into `{layer}`, which is not one of the implementation "
        f"layers {IMPLEMENTATION_LAYERS} -- lower layers are not reachable from api"
    )
    assert attr == fn.name, (
        f"{fn.name}: forwards to `{layer}.{attr}`; the implementation must keep the name, "
        "otherwise the two sides can no longer be compared"
    )
    return layer, attr


def _shell(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """A function reduced to what both sides must share: name, signature, docstring.

    The body is dropped (api forwards, the implementation is the body) and so are
    the decorators (the route decorator stays on the handler, by design).
    """
    clone = copy.deepcopy(fn)
    clone.decorator_list = []
    doc = _docstring_node(fn)
    clone.body = [copy.deepcopy(doc)] if doc is not None else []
    return ast.dump(clone, include_attributes=False)


def _module_functions(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, _FUNC)
    }


# ── 2. the forward + shell invariants ────────────────────────────────────────


def test_every_published_route_survived_the_move():
    """The wire is the same wire: same paths, same methods, same handler names.

    Checked twice -- against the decorators in the source and against what FastAPI
    really registered.  Either side alone can be fooled: a handler that lost its
    decorator drops out of *both* counts, and a decorator that never got applied
    (duplicate function name, say) shows up in the source but not in the router.
    """
    from_source = _ast_routes()
    from_router = _live_routes()

    assert from_source == PUBLISHED_ROUTES, (
        "the route decorators no longer match the published inventory\n"
        f"  gone:   {sorted(PUBLISHED_ROUTES - from_source)}\n"
        f"  added:  {sorted(from_source - PUBLISHED_ROUTES)}"
    )
    assert from_router == PUBLISHED_ROUTES, (
        "the router no longer serves the published inventory\n"
        f"  gone:   {sorted(PUBLISHED_ROUTES - from_router)}\n"
        f"  added:  {sorted(from_router - PUBLISHED_ROUTES)}"
    )


def test_every_route_is_one_forward_to_the_implementation_layer():
    for fn in _api_handlers().values():
        _forward_of(fn)  # raises with the reason


def test_the_api_layer_does_not_re_export_the_implementation_symbols():
    """The absence is the point: a re-export would silently revive stale patches.

    ``patch`` resolves against the module that *reads* the name.  Splitting the
    module moved ~125 patch targets off ``routes.workflow``; if the api layer
    re-exported the implementation symbols, those old targets would "work" again
    -- while the code they mean to disable now reads its own module's copy.  That
    failure is silent (the patch succeeds and changes nothing), so the absence of
    the names is asserted rather than left to review.

    Only symbols *defined* in the layer count, and only names the api layer does
    not already publish on purpose: a handler and the implementation it forwards
    to share their name, so those collisions are the design, not a leak.  What is
    left is exactly the set that went stale -- ``assert_thread_owned``,
    ``_load_history_file``, ``db_get`` ...
    """
    published = set(_api_handlers())
    leaked: list[str] = []
    for layer in IMPLEMENTATION_LAYERS:
        module_name = f"backend.api.routes.{layer}"
        for name, obj in vars(import_module(module_name)).items():
            if not (inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            if getattr(obj, "__module__", None) != module_name:
                continue
            if name not in published and hasattr(api_module, name):
                leaked.append(f"backend.api.routes.workflow.{name}")

    assert not leaked, (
        "the api layer now re-exports implementation symbols, which makes every "
        'stale `patch("backend.api.routes.workflow.X")` target silently work '
        "again:\n  " + "\n  ".join(sorted(set(leaked)))
    )


def test_the_handler_shell_matches_the_implementation_shell():
    handlers = _api_handlers()
    by_layer = {
        layer: _module_functions(ROUTES_DIR / f"{layer}.py") for layer in IMPLEMENTATION_LAYERS
    }

    complaints: list[str] = []
    for name, fn in handlers.items():
        layer, attr = _forward_of(fn)
        impl = by_layer[layer].get(attr)
        if impl is None:
            complaints.append(f"{name}: {layer} has no function named {attr!r}")
            continue
        if _shell(impl) != _shell(fn):
            complaints.append(
                f"{name}: signature or docstring drifted from {layer}.{attr}\n"
                f"    api:           {ast.unparse(fn).splitlines()[0].strip()}\n"
                f"    {layer}: {ast.unparse(impl).splitlines()[0].strip()}"
            )

    assert not complaints, "\n  ".join(complaints)


# ── 3. the published layer table ─────────────────────────────────────────────


def test_the_published_layer_table_lists_exactly_the_layers_on_disk():
    doc = ast.get_docstring(_api_tree())
    assert doc, f"{API_LAYER.name} lost its module docstring, table included"

    published = dict(_LAYER_TABLE_ROW.findall(doc))
    assert published == PUBLISHED_LAYERS, (
        "the layer table published in the module docstring no longer matches the "
        f"layers this test knows: {published} != {PUBLISHED_LAYERS}"
    )
    for module in published.values():
        assert (ROUTES_DIR / module).is_file(), f"the table publishes {module}, which is not there"

    undocumented = {p.name for p in ROUTES_DIR.glob("_wf_*.py")} - set(published.values())
    assert not undocumented, (
        f"layer file(s) missing from the published table: {sorted(undocumented)}"
    )


# ── 1. the /status wire shape ────────────────────────────────────────────────

#: A checkpoint that touches every nested stage key, so the nested part of the
#: shape is not vacuously empty.  ``next=("review_gate",)`` + ``phase="reviewing"``
#: take the live branch of ``/status`` (not the history-file fallback).
_CHECKPOINT: dict[str, Any] = {
    "session_id": "xhs_acct_s4shape",
    "account_id": "acc1",
    "phase": "reviewing",
    "current_agent": "copywriter",
    "created_at": "2026-09-01T08:00:00",
    "updated_at": "2026-09-01T08:30:00",
    "error": None,
    "pause_reason": None,
    "prev_phase": "planning",
    "_last_node": "copywriter",
    "performance_log": [
        {
            "kind": "node",
            "agent": "trend_scout",
            "started_at": "2026-09-01T08:00:05",
            "completed_at": "2026-09-01T08:00:08",
            "duration_seconds": 3.0,
            "status": "success",
        },
        {
            "kind": "llm",
            "agent": "copywriter",
            "started_at": "2026-09-01T08:01:00",
            "completed_at": "2026-09-01T08:01:05",
            "duration_seconds": 5.0,
            "status": "success",
        },
    ],
    "trend_data": {"hot_topics": [{"topic": "早八人咖啡", "heat": 88}]},
    "content_plan": {
        "selected_topic": "早八人咖啡指南",
        "key_points": ["提神", "平价"],
        "target_audience": "通勤白领",
        "content_angle": "便利店平价咖啡横评",
        "ripple_prediction": {"estimated_reach": 120, "verdict": "值得一试"},
        "ripple_pmf": {"pmf_score": 0.72},
    },
    "copy_content": {
        "selected_title": "早八人的咖啡自救指南",
        "body_text": "三块钱的便利店咖啡，凭什么赢过三十块的生椰拿铁？",
        "hashtags": ["#咖啡", "#早八人"],
    },
    "draft_content": {"body_text": "用户微调后的正文"},
    "optimization_analysis": {"gaps": ["缺少场景感"]},
    "content_versions": [{"version_id": "A", "title": "早八人的咖啡自救指南"}],
    "visual_plan": {"layout_style": "clean", "image_count": 4, "color_palette": ["#FFFFFF"]},
    "publish_result": {
        "status": "published",
        "post_url": "https://www.xiaohongshu.com/explore/s4shape",
        "published_at": "2026-09-01T09:00:00",
    },
    "analytics": {"views": 100, "likes": 12},
    "ripple_comparison": {"actual_reach": 96},
    "ripple_prediction": {"estimated_reach": 120, "verdict": "值得一试"},
    "ripple_pmf": {"pmf_score": 0.72},
    "ripple_reason": "预测与实际差距在可接受区间内",
    "workflow_mode": "trend",
    "shooting_plan": {"sections": ["开场", "主体"]},
    "brief_content": {"brand_name": "悦己咖啡"},
    "brief_clarification": {"questions": ["预算区间？"]},
    "blogger_candidates": [{"nickname": "咖啡猎人", "followers": 12000}],
    "selected_blogger": {"nickname": "咖啡猎人"},
    "blogger_notes": [{"note": "均价 15 元"}],
    "reselect_count": 2,
}


def _type_name(value: Any) -> str:
    return "None" if value is None else type(value).__name__


def _describe(value: Any, depth: int = 0) -> Any:
    """The value's *shape*: nesting and types, no data."""
    if isinstance(value, dict):
        if depth >= 2:
            return {key: _type_name(item) for key, item in sorted(value.items())}
        return {key: _describe(item, depth + 1) for key, item in sorted(value.items())}
    if isinstance(value, list):
        if value and isinstance(value[0], (dict, list)):
            return {"[0]": _describe(value[0], depth + 1), "__len>0": True}
        return {"__list_of": _type_name(value[0]) if value else "empty"}
    return _type_name(value)


def _status_shape() -> dict[str, Any]:
    store = MagicMock(name="store")
    store.aget = AsyncMock(side_effect=AssertionError("the probe must not hit the artifact store"))
    snapshot = MagicMock()
    snapshot.values = dict(_CHECKPOINT)
    snapshot.next = ("review_gate",)
    snapshot.tasks = ()
    snapshot.interrupts = ()
    graph = MagicMock()
    graph.store = store
    graph.aget_state = AsyncMock(return_value=snapshot)

    app = FastAPI()
    app.include_router(workflow_router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user

    with (
        patch("backend.api.routes._wf_application.assert_thread_owned", new_callable=AsyncMock),
        patch("backend.api.routes._wf_application.is_pool_ready", return_value=False),
        patch(
            "backend.api.routes._wf_application._db_upsert",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.api.routes._wf_application.db_get", new_callable=AsyncMock),
    ):
        resp = TestClient(app).get("/api/workflow/status/t-s4-shape")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body["data"]
    return {
        "envelope": sorted(body.keys()),
        "top": sorted(data.keys()),
        "shape": _describe(data),
    }


#: The pre-split shape, taken with the same fixture through the same probe.
#: ``top`` is left out on purpose: it is exactly ``sorted(shape)``, which the
#: test asserts instead of storing 40 duplicated lines.
_STATUS_SHAPE: dict[str, Any] = {
    "envelope": ["data", "error", "request_id", "success", "timestamp"],
    "shape": {
        "account_id": "str",
        "agent_timeline": {
            "[0]": {
                "agent": "str",
                "completed_at": "str",
                "duration_seconds": "float",
                "error": "None",
                "started_at": "str",
                "status": "str",
            },
            "__len>0": True,
        },
        "analytics": {"likes": "int", "views": "int"},
        "blogger_candidate_limit": "int",
        "blogger_candidates": {"[0]": {"followers": "int", "nickname": "str"}, "__len>0": True},
        "blogger_note_limit": "int",
        "blogger_notes": {"[0]": {"note": "str"}, "__len>0": True},
        "brief_clarification": {"questions": {"__list_of": "str"}},
        "brief_content": {"brand_name": "str"},
        "checkpoint_lost": "bool",
        "content_plan": {
            "content_angle": "str",
            "key_points": {"__list_of": "str"},
            "ripple_pmf": {"pmf_score": "float"},
            "ripple_prediction": {"estimated_reach": "int", "verdict": "str"},
            "selected_topic": "str",
            "target_audience": "str",
        },
        "content_versions": {"[0]": {"title": "str", "version_id": "str"}, "__len>0": True},
        "copy_content": {
            "body_text": "str",
            "hashtags": {"__list_of": "str"},
            "selected_title": "str",
        },
        "created_at": "str",
        "current_agent": "str",
        "draft_content": {"body_text": "str"},
        "error": "None",
        "label": "str",
        "next_steps": {"__list_of": "str"},
        "optimization_analysis": {"gaps": {"__list_of": "str"}},
        "orphan": "bool",
        "pause_reason": "None",
        "phase": "str",
        "progress_percent": "int",
        "publish_result": {"post_url": "str", "published_at": "str", "status": "str"},
        "reselect_count": "int",
        "ripple_comparison": {"actual_reach": "int"},
        "ripple_pmf": {"pmf_score": "float"},
        "ripple_prediction": {"estimated_reach": "int", "verdict": "str"},
        "ripple_progress": {},
        "ripple_reason": "str",
        "selected_blogger": {"nickname": "str"},
        "shooting_plan": {"sections": {"__list_of": "str"}},
        "status": "str",
        "thread_id": "str",
        "trend_data": {"hot_topics": {"[0]": {"heat": "int", "topic": "str"}, "__len>0": True}},
        "updated_at": "str",
        "visual_plan": {
            "color_palette": {"__list_of": "str"},
            "image_count": "int",
            "layout_style": "str",
        },
        "workflow_mode": "str",
    },
}


def _flat(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_flat(item, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: value}


def test_the_status_wire_shape_is_what_it_was_before_the_split():
    probed = _status_shape()

    # The dropped `top` is reconstructible from `shape`, so dropping it from the
    # frozen constant loses nothing.  Without this the loss would be silent.
    assert probed["top"] == sorted(probed["shape"]), (
        "`top` is no longer `sorted(shape)` -- the frozen constant below is missing a field"
    )

    actual = {"envelope": probed["envelope"], "shape": probed["shape"]}
    before, after = _flat(_STATUS_SHAPE), _flat(actual)

    complaints = [f"gone: {k} == {before[k]!r}" for k in sorted(before.keys() - after.keys())]
    complaints += [f"new: {k} == {after[k]!r}" for k in sorted(after.keys() - before.keys())]
    complaints += [
        f"changed: {k}: {before[k]!r} -> {after[k]!r}"
        for k in sorted(before.keys() & after.keys())
        if before[k] != after[k]
    ]

    assert not complaints, (
        "the /status payload shape drifted from the pre-split baseline (ec64fa86).\n  "
        + "\n  ".join(complaints)
    )
