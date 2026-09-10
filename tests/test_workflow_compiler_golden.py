"""
tests/test_workflow_compiler_golden.py — golden regression suite for the
workflow-builder compile pipeline (workflow_compiler.py -> entity_schema/steps).

WHY THIS EXISTS:
Every bug in the compile pipeline this session (wrong column mapping,
duplicate resolve_entity dropping a filter, a free-text value crashing a
CHECK constraint) was caught by a human manually testing a live chat
conversation on Telegram, one workflow at a time — after the buggy code was
already deployed. That doesn't scale past a handful of workflows, and it
means every future prompt/compiler change is only as safe as whoever
happens to test it by hand next.

This suite runs a fixed set of representative, realistic workflow
descriptions through the REAL compiler (real LLM calls, no mocks) against
the REAL Godrej schema, and checks the output the same way a careful human
reviewer would: every entity_schema field actually points at a real
table/column, every field backed by a DB CHECK-constraint enum declares
that enum correctly, and workflow_validator.py's structural checks pass.
Run it after any change to workflow_compiler.py, workflow_compiler.txt,
schema_utils.py, or workflow_validator.py — a regression here means a
regression in every real chat conversation admins will have.

Deliberately NOT mocked: an LLM call is the thing actually being tested.
Mocking it would make this a test of the Python glue code only, which the
existing (mocked) test suite already covers — see "Run Your Code Generator
As A Test" (adventures.michaelfbryan.com) on why the generator itself needs
to run, not just be imported.

Costs real API calls and needs real DB credentials — excluded from the
default `pytest` run (see pytest.ini's `-m "not golden"`). Run explicitly:
    pytest -m golden -v
"""
import pytest
from app.db import init_db, close_db
from app.services.workflow_compiler import compile_workflow_spec
from app.services.workflow_validator import validate_workflow_config
from app.services.schema_utils import get_business_schema, get_enum_constraints

pytestmark = pytest.mark.golden

# Godrej Emerald — chosen because it has real, populated CHECK constraints
# (residents.residential_status, meetings.meeting_type, etc.) to validate
# enum propagation against, not because anything here is Godrej-specific.
ORG_ID = "793eead0-31b2-4538-b9b3-1885f9e94604"
SOURCE_KEY = "godrej"


@pytest.fixture(scope="module", autouse=True)
async def _db():
    await init_db()
    yield
    await close_db()


GOLDEN_CASES = [
    {
        "name": "insert_with_enum_field",
        # Regression target: residential_status must map with a correct
        # "enum" (this exact case crashed live in production before today's
        # fix — see git log for the CheckViolationError incident).
        "draft": {
            "purpose": "Add a new resident to the system",
            "workflow_type": "action",
            "raw_fields": [
                "name", "wing", "flat number",
                "residential status (first_owner, second_owner, or tenant)",
            ],
            "business_rules": "",
            "gates": [],
        },
    },
    {
        "name": "update_by_composite_match",
        # Regression target: matching an existing row by TWO columns
        # (wing + flat number) at once. The original bug this session was
        # two separate resolve_entity calls into the same alias silently
        # dropping the first filter — this must compile to ONE
        # resolve_entity using match_columns, not two calls.
        "draft": {
            "purpose": (
                "Update an existing resident's status — find them by wing "
                "and flat number, then change their residential status"
            ),
            "workflow_type": "action",
            "raw_fields": [
                "wing", "flat number",
                "new residential status (first_owner, second_owner, or tenant)",
            ],
            "business_rules": "",
            "gates": [],
        },
    },
    {
        "name": "read_only_list_workflow",
        # Regression target: workflow_type=read must produce a valid
        # sql_template that passes the compiler's own EXPLAIN dry-run.
        "draft": {
            "purpose": "Show all residents living in a given wing",
            "workflow_type": "read",
            "raw_fields": ["wing"],
            "business_rules": "",
            "gates": [],
        },
    },
    {
        "name": "insert_different_table_enum",
        # Regression target: enum-propagation must generalize beyond
        # residents — meetings.meeting_type is a differently-named,
        # differently-valued CHECK constraint on a different table.
        "draft": {
            "purpose": "Log that a meeting was held",
            "workflow_type": "action",
            "raw_fields": [
                "meeting type (general, committee, or agm)", "meeting date", "agenda",
            ],
            "business_rules": "",
            "gates": [],
        },
    },
    {
        "name": "conditional_branch_when_guard",
        # Regression target: one workflow that does different things
        # depending on an action field must use step-level "when" guards,
        # not silently only implement one branch.
        "draft": {
            "purpose": (
                "Committee approves or rejects a guest parking request. "
                "If approved, mark the parking slot as occupied by that "
                "visitor. If rejected, just record the rejection — don't "
                "touch the parking slot."
            ),
            "workflow_type": "action",
            "raw_fields": ["visitor name", "parking slot number", "decision (approve or reject)"],
            "business_rules": "",
            "gates": [],
        },
    },
    {
        "name": "insert_no_enum_plain_fields",
        # Baseline/control: a plain insert with no enum-constrained fields
        # at all, so the enum machinery correctly does nothing here.
        "draft": {
            "purpose": "Log a visitor entering the society",
            "workflow_type": "action",
            "raw_fields": ["visitor name", "phone number", "flat being visited", "purpose of visit"],
            "business_rules": "",
            "gates": [],
        },
    },
]


def _iter_entity_fields(entity_schema: dict):
    """Yield (field_label, field_spec) for top-level fields and any nested item_schema fields."""
    for name, spec in (entity_schema or {}).items():
        if not isinstance(spec, dict):
            continue
        yield name, spec
        item_schema = (spec.get("item_schema") or {}) if spec.get("type") == "array" else {}
        for iname, ispec in item_schema.items():
            if isinstance(ispec, dict):
                yield f"{name}[].{iname}", ispec


async def _assert_spec_is_grounded(spec: dict):
    """
    The checks a careful human reviewer would do by hand: does every
    non-computed field actually point at a real column, and does every
    enum-backed field declare the DB's real allowed values.
    """
    problems = validate_workflow_config(spec)
    assert not problems, f"validate_workflow_config found structural problems: {problems}"

    table_cols = await get_business_schema(source_key=SOURCE_KEY)
    enum_constraints = await get_enum_constraints(SOURCE_KEY)

    for field_label, fspec in _iter_entity_fields(spec.get("entity_schema") or {}):
        if fspec.get("computed"):
            continue
        table, column = fspec.get("table"), fspec.get("column")
        if not table or not column:
            continue
        assert table in table_cols, (
            f"entity_schema['{field_label}']: table '{table}' does not exist in the live schema"
        )
        assert column in table_cols[table], (
            f"entity_schema['{field_label}']: column '{table}.{column}' does not exist"
        )

        real_values = enum_constraints.get((table, column))
        if real_values:
            declared = set(fspec.get("enum") or [])
            assert declared == set(real_values), (
                f"entity_schema['{field_label}'] maps to {table}.{column}, which has a real "
                f"CHECK-constraint enum {sorted(real_values)}, but entity_schema declared "
                f"enum={sorted(declared) if declared else '(missing)'} — the runtime chat agent "
                f"won't know the valid options and will pass free text straight into an insert/update."
            )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c["name"] for c in GOLDEN_CASES])
async def test_golden_compile(case):
    spec = await compile_workflow_spec(case["draft"], ORG_ID, SOURCE_KEY)
    await _assert_spec_is_grounded(spec)
