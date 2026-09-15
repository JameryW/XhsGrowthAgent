"""Tests for provider-native structured output and its degradation chain (P1d).

The facility has one job: never let ``how the text was obtained`` decide
``whether the text was checked``. So the tests are split the same way — the
chain's shape (which levels exist, in what order, and how a mode is resolved)
versus the checks that every level is held to identically.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.config.models import ModelProvider
from backend.models.structured import (
    StructuredMode,
    StructuredOutputError,
    degradation_path,
    describe_validation_error,
    render_schema_instructions,
    resolve_structured_mode,
    validate_output,
)


class _Item(BaseModel):
    name: str
    count: int = 0
    score: float = 0.0
    flag: bool = False
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class TestDegradationPath:
    def test_from_native_schema_walks_the_whole_chain(self):
        assert degradation_path(StructuredMode.NATIVE_SCHEMA) == (
            StructuredMode.NATIVE_SCHEMA,
            StructuredMode.JSON_OBJECT,
            StructuredMode.PROMPTED,
        )

    def test_from_json_object_does_not_climb_back_up(self):
        """A weaker starting point must not include the stronger level.

        Relisting ``NATIVE_SCHEMA`` below ``JSON_OBJECT`` would make the chain
        try the level the provider already told us it cannot do.
        """
        assert degradation_path(StructuredMode.JSON_OBJECT) == (
            StructuredMode.JSON_OBJECT,
            StructuredMode.PROMPTED,
        )

    def test_from_prompted_has_nowhere_left_to_go(self):
        """The weakest level terminates the walk.

        A path that wrapped around would retry the same level forever — the
        exact failure the ``for level in …`` loop cannot detect on its own.
        """
        assert degradation_path(StructuredMode.PROMPTED) == (StructuredMode.PROMPTED,)

    def test_every_mode_starts_its_own_path(self):
        for mode in StructuredMode:
            assert degradation_path(mode)[0] is mode

    def test_paths_are_strictly_weaker_within_the_chain(self):
        order = list(StructuredMode)
        for mode in StructuredMode:
            indexes = [order.index(item) for item in degradation_path(mode)]
            assert indexes == sorted(indexes)


class TestResolveStructuredMode:
    def test_the_table_answers_when_nothing_overrides_it(self, monkeypatch: pytest.MonkeyPatch):
        for name in dir(ModelProvider):
            if name.startswith("_"):
                continue
            monkeypatch.delenv(f"XHS_STRUCTURED_MODE_{name}", raising=False)
        assert resolve_structured_mode(ModelProvider.OPENAI) is StructuredMode.NATIVE_SCHEMA
        assert resolve_structured_mode(ModelProvider.DEEPSEEK) is StructuredMode.JSON_OBJECT
        # The production default route (13 of 15 task types) is the one with no
        # verified contract, so it must not be resolving to a native claim.
        assert resolve_structured_mode(ModelProvider.XUNFEI) is StructuredMode.PROMPTED

    def test_explicit_override_beats_the_env_var(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XHS_STRUCTURED_MODE_OPENAI", "prompted")
        assert (
            resolve_structured_mode(ModelProvider.OPENAI, override=StructuredMode.JSON_OBJECT)
            is StructuredMode.JSON_OBJECT
        )

    def test_the_env_var_beats_the_table(self, monkeypatch: pytest.MonkeyPatch):
        """Correcting a provider's capability must not require a code release."""
        monkeypatch.setenv("XHS_STRUCTURED_MODE_XUNFEI", "json_object")
        assert resolve_structured_mode(ModelProvider.XUNFEI) is StructuredMode.JSON_OBJECT

    def test_the_env_var_is_lowercased_and_stripped(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XHS_STRUCTURED_MODE_XUNFEI", "  JSON_Object ")
        assert resolve_structured_mode(ModelProvider.XUNFEI) is StructuredMode.JSON_OBJECT

    def test_a_malformed_override_is_ignored_not_fatal(self):
        """A typo in an env var must not take the call down."""
        assert (
            resolve_structured_mode(ModelProvider.XUNFEI, override="yaml-ish")
            is StructuredMode.PROMPTED
        )

    def test_a_malformed_env_var_falls_back_to_the_table(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XHS_STRUCTURED_MODE_DEEPSEEK", "")
        assert resolve_structured_mode(ModelProvider.DEEPSEEK) is StructuredMode.JSON_OBJECT
        monkeypatch.setenv("XHS_STRUCTURED_MODE_DEEPSEEK", "native")
        assert resolve_structured_mode(ModelProvider.DEEPSEEK) is StructuredMode.JSON_OBJECT

    def test_one_provider_env_var_does_not_leak_to_another(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XHS_STRUCTURED_MODE_DASHSCOPE", "native_schema")
        assert resolve_structured_mode(ModelProvider.DASHSCOPE) is StructuredMode.NATIVE_SCHEMA
        assert resolve_structured_mode(ModelProvider.DEEPSEEK) is StructuredMode.JSON_OBJECT


class TestRenderSchemaInstructions:
    def test_it_marks_required_and_optional_fields(self):
        text = render_schema_instructions(_Item)
        assert "- name: string（必填" in text
        assert "- count: integer（可选" in text

    def test_it_translates_annotations_into_the_words_a_model_reads(self):
        text = render_schema_instructions(_Item)
        assert "tags: list[string]" in text
        assert "meta: object" in text
        assert "score: number" in text
        assert "flag: boolean" in text

    def test_it_carries_the_field_description(self):
        class _Described(BaseModel):
            topic: str = Field(description="选定的内容主题")

        text = render_schema_instructions(_Described)
        assert "选定的内容主题" in text

    def test_it_lists_exactly_the_model_fields(self):
        text = render_schema_instructions(_Item)
        assert text.count("- ") == len(_Item.model_fields)

    def test_it_asks_for_a_bare_object(self):
        text = render_schema_instructions(_Item)
        assert "JSON 对象" in text
        assert "markdown" in text


class _Note(BaseModel):
    title: str = Field(description="笔记标题")
    likes: int = 0


class _Report(BaseModel):
    notes: list[_Note] = Field(default_factory=list)
    headline: _Note | None = None
    payload: Any = None


class _Twice(BaseModel):
    first: _Note | None = None
    second: _Note | None = None


class _Node(BaseModel):
    label: str = ""
    children: list[_Node] = Field(default_factory=list)


class TestTheSchemaHintSpellsOutNestedModels:
    """A nested field is rendered as *its fields*, not as a class name.

    ``hot_topics: list[HotTopicItemOutput]`` is what the scouts actually return,
    and it is the case that matters: rendering it as ``list[object]`` leaves the
    model to guess the keys from the field name, and a guess that arrives as a
    list of strings is a retry — the cost this hint exists to avoid.
    """

    def test_a_nested_model_inside_a_list_is_expanded(self):
        text = render_schema_instructions(_Report)
        assert "notes: list[object]" in text
        assert "title: string" in text
        assert "likes: integer" in text

    def test_a_nested_model_behind_an_optional_is_expanded(self):
        """``_Note | None`` used to render as ``string`` — a wrapper read as a
        type. It compounds with the expand-once rule: the second field naming
        the same model gets no expansion to correct the mislabel with."""
        text = render_schema_instructions(_Twice)
        assert "first: object" in text
        assert "  first 的元素字段：" in text
        assert "title: string" in text

    def test_a_real_union_lists_every_label_it_can_be(self):
        class _Either(BaseModel):
            either: str | int = ""

        text = render_schema_instructions(_Either)
        assert "either: string | integer" in text

    def test_an_any_field_is_labelled_any_and_does_not_explode(self):
        text = render_schema_instructions(_Report)
        assert "payload: any" in text

    def test_a_nested_model_is_expanded_once_however_often_it_is_referenced(self):
        """Expanding per reference would make the hint grow with the number of
        fields sharing a type, for no extra information."""
        text = render_schema_instructions(_Report)
        assert text.count("title: string") == 1

    def test_a_self_referential_model_terminates(self):
        text = render_schema_instructions(_Node)
        assert "children: list[object]" in text
        assert text.count("- label: string") <= 2

    def test_the_expansion_is_indented_under_the_field_it_belongs_to(self):
        text = render_schema_instructions(_Report)
        assert "  notes 的元素字段：" in text


class TestDescribeValidationError:
    def test_it_names_the_field_that_failed(self):
        with pytest.raises(Exception) as excinfo:
            _Item.model_validate({"count": "not a number"})
        assert "name" in describe_validation_error(excinfo.value)

    def test_it_keeps_the_pydantic_reason(self):
        with pytest.raises(Exception) as excinfo:
            _Item.model_validate({"name": "x", "count": "not a number"})
        described = describe_validation_error(excinfo.value)
        assert "count" in described
        assert "int" in described or "number" in described

    def test_nested_paths_are_joined(self):
        class _Outer(BaseModel):
            inner: _Item

        with pytest.raises(Exception) as excinfo:
            _Outer.model_validate({"inner": {"count": 1}})
        assert "inner.name" in describe_validation_error(excinfo.value)


class TestValidateOutput:
    """Schema only — the semantic check is the caller's, and deliberately not
    folded in here (that collapsing is what would hide the difference between
    "unusable" and "usable but refused")."""

    def test_a_well_formed_payload_returns_the_instance(self):
        instance, correction = validate_output({"name": "a", "count": 2}, _Item)
        assert correction is None
        assert instance == _Item(name="a", count=2)

    def test_an_instance_the_provider_already_built_is_accepted(self):
        """A native structured-output call hands back the model itself.
        Demanding a dict there discarded every native answer."""
        instance, correction = validate_output(_Item(name="a"), _Item)
        assert correction is None
        assert instance == _Item(name="a")

    def test_an_unrelated_object_is_still_refused(self):
        """The acceptance above must not turn the gate decorative."""
        instance, correction = validate_output(object(), _Item)
        assert instance is None
        assert correction is not None

    def test_a_subclass_instance_is_accepted(self):
        class _Sub(_Item):
            pass

        instance, correction = validate_output(_Sub(name="a"), _Item)
        assert correction is None
        assert isinstance(instance, _Item)

    @pytest.mark.parametrize("payload", ["not json", ["a"], 42, None])
    def test_a_non_object_payload_is_refused_with_an_explanation(self, payload):
        instance, correction = validate_output(payload, _Item)
        assert instance is None
        assert correction is not None
        assert "JSON 对象" in correction

    def test_a_missing_required_field_is_refused(self):
        instance, correction = validate_output({}, _Item)
        assert instance is None
        assert correction is not None
        assert "name" in correction

    def test_a_wrongly_typed_field_is_refused(self):
        instance, correction = validate_output({"name": "a", "count": "many"}, _Item)
        assert instance is None
        assert correction is not None
        assert "count" in correction

    def test_the_correction_is_addressed_to_the_model_not_to_a_reader(self):
        """It has to read as an instruction — the retry works by telling the
        model exactly which field to change."""
        _, correction = validate_output({}, _Item)
        assert correction is not None
        assert "请" in correction


class TestStructuredOutputError:
    def test_it_reports_every_attempt(self):
        error = StructuredOutputError(
            _Item,
            [
                (StructuredMode.NATIVE_SCHEMA, "AttributeError: no tool calling"),
                (StructuredMode.PROMPTED, "name: Field required"),
            ],
        )
        assert error.output_model is _Item
        assert len(error.attempts) == 2
        assert error.attempts[0][0] is StructuredMode.NATIVE_SCHEMA
        assert "no tool calling" in str(error)
        assert "Field required" in str(error)
        assert "_Item" in str(error)

    def test_it_is_a_runtime_error(self):
        assert issubclass(StructuredOutputError, RuntimeError)

    def test_it_carries_no_partial_result(self):
        """A "mostly validated" payload is how bad data reaches state.

        There is no attribute holding a payload, on purpose — a caller that
        wants the last schema-valid answer must ask for it explicitly via
        ``accept_last_valid``, where it is visible.
        """
        error = StructuredOutputError(_Item, [(StructuredMode.PROMPTED, "nope")])
        assert not hasattr(error, "payload")


class _QuestionList(BaseModel):
    """A model whose *natural* answer is a bare array (P1d-S2b).

    The shape is declared rather than inferred because only the model can say
    it: to every other model in the package an array is a mistake, not a shape.
    """

    model_config = ConfigDict(extra="ignore")

    accepts_bare_list: ClassVar[bool] = True

    questions: list[_Item] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _a_bare_array_is_the_question_list(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"questions": data}
        return data


class TestABareArrayIsALegalRootOnlyWhereDeclared:
    """``validate_output`` used to refuse every non-dict payload.

    That was right for eleven of the twelve models and wrong for the one whose
    answer really is a list — ``_parse_json_response`` hands back a ``list`` for
    ``[{"field": …}]``, so migrating that call site without this would have
    turned "accepted" into "hard failure".
    """

    def test_the_array_is_accepted_where_the_model_declares_it(self):
        instance, correction = validate_output([{"name": "a"}], _QuestionList)
        assert correction is None
        assert isinstance(instance, _QuestionList)
        assert instance.questions == [_Item(name="a")]

    def test_the_same_array_is_still_refused_where_it_is_not_declared(self):
        instance, correction = validate_output([{"name": "a"}], _Item)
        assert instance is None
        assert correction is not None

    def test_the_object_spelling_still_validates_for_a_list_rooted_model(self):
        instance, correction = validate_output({"questions": [{"name": "a"}]}, _QuestionList)
        assert correction is None
        assert isinstance(instance, _QuestionList)

    def test_a_scalar_is_still_refused_for_a_list_rooted_model(self):
        instance, correction = validate_output("nope", _QuestionList)
        assert instance is None
        assert correction is not None

    def test_the_correction_names_the_shapes_this_model_accepts(self):
        """The correction *is* the retry mechanism, so it must not narrow a
        list-rooted model down to the spelling we did not need — and must not
        tell an object-rooted one that an array is welcome."""
        _, list_rooted = validate_output("nope", _QuestionList)
        _, object_rooted = validate_output("nope", _Item)

        assert list_rooted is not None and "数组" in list_rooted
        assert list_rooted is not None and "JSON 对象" in list_rooted
        assert object_rooted is not None and "数组" not in object_rooted

    def test_an_instance_the_provider_built_is_accepted_before_the_gate(self):
        """The bare-list gate must not shadow the instance check above it."""
        already = _QuestionList(questions=[_Item(name="a")])
        instance, correction = validate_output(already, _QuestionList)
        assert correction is None
        assert instance is already
