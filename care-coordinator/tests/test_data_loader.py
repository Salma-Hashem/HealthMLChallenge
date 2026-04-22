"""
Tests for data_loader.parse_providers — Phase 1 and Phase 2 independently,
plus an integration test against the real data_sheet.txt.

Testing approach
----------------
Phase 1 (_extract_provider_blocks) is tested with fabricated line lists.
  - No dataclass objects are constructed; we just assert the shape of the
    returned blocks (length, first element of each block, etc.).
  - This isolates segmentation logic from object-construction logic.

Phase 2 (_build_provider) is tested with fabricated block lists (the kind
  _extract_provider_blocks produces).
  - No file I/O; we feed in a list of strings and assert the resulting
    Provider/Department fields.
  - Department counters and trailing-department saves are verified directly.

Integration tests run parse_providers against the real data_sheet.txt and
assert the exact 5-provider, 6-department structure expected from production.
"""

import os
import sys
import pytest

# Ensure the care-coordinator package root is on the path when running from
# the tests/ directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.loader import (
    _extract_provider_blocks,
    _build_provider,
    parse_providers,
    parse_hours_string,
    load_all_data,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATA_SHEET = os.path.join(os.path.dirname(__file__), "..", "data", "data_sheet.txt")


def _lines(*text: str):
    """Turn positional string args into a list of lines (adds newlines)."""
    return [line + "\n" for line in text]


# ---------------------------------------------------------------------------
# Phase 1: _extract_provider_blocks
# ---------------------------------------------------------------------------

class TestExtractProviderBlocks:

    def test_empty_input_returns_empty_list(self):
        # No lines at all → nothing to segment
        assert _extract_provider_blocks([]) == []

    def test_no_provider_section_returns_empty_list(self):
        # File has content but no "Provider Directory" header
        lines = _lines("Accepted Insurances:", "- Medicaid")
        assert _extract_provider_blocks(lines) == []

    def test_single_provider_no_terminator(self):
        # One provider, file ends without "Appointments:" — trailing save fires
        lines = _lines(
            "Provider Directory",
            "- Grey, Meredith",
            "  - certification: MD",
            "  - specialty: Primary Care",
        )
        blocks = _extract_provider_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0][0] == "- Grey, Meredith"
        assert "- certification: MD" in blocks[0]

    def test_single_provider_with_terminator(self):
        # "Appointments:" stops scanning before hitting end-of-file
        lines = _lines(
            "Provider Directory",
            "- Grey, Meredith",
            "  - certification: MD",
            "Appointments:",
            "  - some scheduling rule",
        )
        blocks = _extract_provider_blocks(lines)
        assert len(blocks) == 1
        # The "Appointments:" line and everything after must NOT appear
        for block in blocks:
            for line in block:
                assert "some scheduling rule" not in line

    def test_two_providers_produce_two_blocks(self):
        lines = _lines(
            "Provider Directory",
            "- Grey, Meredith",
            "  - certification: MD",
            "  - specialty: Primary Care",
            "- House, Gregory",
            "  - certification: MD",
            "  - specialty: Orthopedics",
            "Appointments:",
        )
        blocks = _extract_provider_blocks(lines)
        assert len(blocks) == 2
        assert blocks[0][0] == "- Grey, Meredith"
        assert blocks[1][0] == "- House, Gregory"

    def test_provider_without_dash_prefix(self):
        # "Brennan, Temperance" (no leading dash) must still be detected
        lines = _lines(
            "Provider Directory",
            "Brennan, Temperance",
            "  - certification: PhD, MD",
        )
        blocks = _extract_provider_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0][0] == "Brennan, Temperance"

    def test_blank_lines_inside_section_are_skipped(self):
        # Blank lines between providers must not break segmentation
        lines = _lines(
            "Provider Directory",
            "",
            "- Grey, Meredith",
            "  - certification: MD",
            "",
            "- House, Gregory",
            "  - specialty: Orthopedics",
            "Appointments:",
        )
        blocks = _extract_provider_blocks(lines)
        assert len(blocks) == 2

    def test_section_header_is_case_insensitive(self):
        # "provider directory" (all lower) should still trigger section start
        lines = _lines(
            "provider directory",
            "- Grey, Meredith",
            "  - certification: MD",
        )
        blocks = _extract_provider_blocks(lines)
        assert len(blocks) == 1

    def test_extra_whitespace_around_section_header(self):
        # "  Provider Directory  " should still be recognised
        lines = ["  Provider Directory  \n", "- Grey, Meredith\n"]
        blocks = _extract_provider_blocks(lines)
        assert len(blocks) == 1

    def test_provider_with_multiple_departments_stays_in_one_block(self):
        # All dept lines must land in the same block as their provider
        lines = _lines(
            "Provider Directory",
            "- House, Gregory",
            "  - certification: MD",
            "  - specialty: Orthopedics",
            "  - department:",
            "    - name: PPTH Orthopedics",
            "  - department:",
            "    - name: Jefferson Hospital",
            "Appointments:",
        )
        blocks = _extract_provider_blocks(lines)
        assert len(blocks) == 1
        block = blocks[0]
        assert any("PPTH Orthopedics" in l for l in block)
        assert any("Jefferson Hospital" in l for l in block)

    def test_lines_before_section_are_excluded(self):
        # Preamble before "Provider Directory" must be ignored
        lines = _lines(
            "Some preamble",
            "Provider Directory",
            "- Grey, Meredith",
        )
        blocks = _extract_provider_blocks(lines)
        assert len(blocks) == 1
        # Preamble must not appear in any block
        all_lines = [l for b in blocks for l in b]
        assert "Some preamble" not in all_lines

    def test_each_block_starts_with_provider_header(self):
        lines = _lines(
            "Provider Directory",
            "- Grey, Meredith",
            "  - certification: MD",
            "- House, Gregory",
            "  - certification: MD",
            "Appointments:",
        )
        blocks = _extract_provider_blocks(lines)
        for block in blocks:
            # First line of every block must match the provider header pattern
            import re
            assert re.match(r"^-?\s*[A-Za-z]+,\s+[A-Za-z]+\s*$", block[0]), block[0]


# ---------------------------------------------------------------------------
# Phase 2: _build_provider
# ---------------------------------------------------------------------------

class TestBuildProvider:

    def test_basic_provider_fields(self):
        block = [
            "- Grey, Meredith",
            "- certification: MD",
            "- specialty: Primary Care",
        ]
        provider, next_dept_id = _build_provider(block, provider_id=1, start_dept_id=0)
        assert provider.id == 1
        assert provider.last_name == "Grey"
        assert provider.first_name == "Meredith"
        assert provider.certification == "MD"
        assert provider.specialty == "Primary Care"
        assert next_dept_id == 0  # no departments → counter unchanged

    def test_provider_with_one_department(self):
        # Lines are pre-stripped (as _extract_provider_blocks produces them)
        block = [
            "- Grey, Meredith",
            "- certification: MD",
            "- specialty: Primary Care",
            "- department:",
            "- name: Sloan Primary Care",
            "- phone: (710) 555-2070",
            "- address: 202 Maple St, Winston-Salem, NC 27101",
            "- hours: M-F 9am-5pm",
        ]
        provider, next_dept_id = _build_provider(block, provider_id=1, start_dept_id=0)
        assert len(provider.departments) == 1
        dept = provider.departments[0]
        assert dept.id == 1          # start_dept_id 0 + 1
        assert dept.name == "Sloan Primary Care"
        assert dept.phone == "(710) 555-2070"
        assert dept.address == "202 Maple St, Winston-Salem, NC 27101"
        assert len(dept.hours) == 5  # M-F = 5 days
        assert next_dept_id == 1

    def test_provider_with_multiple_departments(self):
        # Lines are pre-stripped (as _extract_provider_blocks produces them).
        # House has PPTH Orthopedics (M-W) and Jefferson Hospital (Th-F).
        block = [
            "- House, Gregory",
            "- certification: MD",
            "- specialty: Orthopedics",
            "- department:",
            "- name: PPTH Orthopedics",
            "- phone: (445) 555-6205",
            "- address: 101 Pine St, Greensboro, NC 27401",
            "- hours: M-W 9am-5pm",
            "- department:",
            "- name: Jefferson Hospital",
            "- phone: (215) 555-6123",
            "- address: 202 Maple St, Claremont, NC 28610",
            "- hours: Th-F 9am-5pm",
        ]
        provider, next_dept_id = _build_provider(block, provider_id=2, start_dept_id=1)
        assert len(provider.departments) == 2
        assert provider.departments[0].name == "PPTH Orthopedics"
        assert provider.departments[0].id == 2    # start 1 + 1
        assert provider.departments[1].name == "Jefferson Hospital"
        assert provider.departments[1].id == 3    # start 1 + 2
        assert len(provider.departments[0].hours) == 3  # M, Tu, W
        assert len(provider.departments[1].hours) == 2  # Th, F
        assert next_dept_id == 3

    def test_provider_without_dash_prefix_on_header(self):
        # "Brennan, Temperance" has no leading dash in the real data sheet
        block = [
            "Brennan, Temperance",
            "- certification: PhD, MD",
            "- specialty: Orthopedics",
        ]
        provider, _ = _build_provider(block, provider_id=5, start_dept_id=0)
        assert provider.last_name == "Brennan"
        assert provider.first_name == "Temperance"
        assert provider.certification == "PhD, MD"

    def test_dept_id_counter_is_sequential_across_calls(self):
        # Simulate two consecutive providers: first ends with dept_id=2,
        # second must start from 2 and end at 3.
        block1 = [
            "- Grey, Meredith",
            "- department:",
            "  - name: Dept A",
            "- department:",
            "  - name: Dept B",
        ]
        _, dept_id_after_first = _build_provider(block1, provider_id=1, start_dept_id=0)
        assert dept_id_after_first == 2

        block2 = [
            "- House, Gregory",
            "- department:",
            "  - name: Dept C",
        ]
        provider2, dept_id_after_second = _build_provider(block2, provider_id=2, start_dept_id=dept_id_after_first)
        assert dept_id_after_second == 3
        assert provider2.departments[0].id == 3

    def test_trailing_department_is_always_saved(self):
        # The last department in a block must be appended even without a
        # following "department:" marker — this is the local trailing-save.
        # Lines are pre-stripped (as _extract_provider_blocks produces them).
        block = [
            "- Yang, Cristina",
            "- specialty: Surgery",
            "- department:",
            "- name: Last Dept",
            "- phone: (000) 000-0000",
        ]
        provider, _ = _build_provider(block, provider_id=3, start_dept_id=0)
        assert len(provider.departments) == 1
        assert provider.departments[0].name == "Last Dept"

    def test_provider_with_no_departments(self):
        block = [
            "- Grey, Meredith",
            "- certification: MD",
            "- specialty: Primary Care",
        ]
        provider, next_dept_id = _build_provider(block, provider_id=1, start_dept_id=5)
        assert provider.departments == []
        assert next_dept_id == 5   # unchanged

    def test_hours_are_parsed_into_office_hours_objects(self):
        # Lines are pre-stripped (as _extract_provider_blocks produces them)
        block = [
            "- Grey, Meredith",
            "- department:",
            "- name: Test Clinic",
            "- hours: Tu-Th 10am-4pm",
        ]
        provider, _ = _build_provider(block, provider_id=1, start_dept_id=0)
        hours = provider.departments[0].hours
        assert len(hours) == 3   # Tu, W, Th
        from datetime import time
        assert hours[0].open_time  == time(10, 0)
        assert hours[0].close_time == time(16, 0)


# ---------------------------------------------------------------------------
# Integration: parse_providers against the real data_sheet.txt
# ---------------------------------------------------------------------------

class TestParseProvidersIntegration:

    @pytest.fixture(scope="class")
    def providers(self):
        with open(DATA_SHEET) as f:
            lines = f.readlines()
        return parse_providers(lines)

    def test_correct_number_of_providers(self, providers):
        # data_sheet.txt has exactly 5 providers
        assert len(providers) == 5

    def test_provider_ids_are_sequential(self, providers):
        assert [p.id for p in providers] == [1, 2, 3, 4, 5]

    def test_provider_names(self, providers):
        names = [(p.last_name, p.first_name) for p in providers]
        assert ("Grey",    "Meredith")   in names
        assert ("House",   "Gregory")    in names
        assert ("Yang",    "Cristina")   in names
        assert ("Perry",   "Chris")      in names
        assert ("Brennan", "Temperance") in names

    def test_provider_specialties(self, providers):
        by_name = {p.last_name: p for p in providers}
        assert by_name["Grey"].specialty    == "Primary Care"
        assert by_name["House"].specialty   == "Orthopedics"
        assert by_name["Yang"].specialty    == "Surgery"
        assert by_name["Perry"].specialty   == "Primary Care"
        assert by_name["Brennan"].specialty == "Orthopedics"

    def test_total_department_count(self, providers):
        # Grey:1, House:2, Yang:1, Perry:1, Brennan:1 = 6 total
        total = sum(len(p.departments) for p in providers)
        assert total == 6

    def test_house_has_two_departments(self, providers):
        house = next(p for p in providers if p.last_name == "House")
        assert len(house.departments) == 2
        dept_names = {d.name for d in house.departments}
        assert "PPTH Orthopedics"  in dept_names
        assert "Jefferson Hospital" in dept_names

    def test_department_ids_are_sequential_across_providers(self, providers):
        all_dept_ids = [d.id for p in providers for d in p.departments]
        assert all_dept_ids == list(range(1, len(all_dept_ids) + 1))

    def test_grey_department_details(self, providers):
        grey = next(p for p in providers if p.last_name == "Grey")
        dept = grey.departments[0]
        assert dept.name    == "Sloan Primary Care"
        assert dept.phone   == "(710) 555-2070"
        assert "Winston-Salem" in dept.address
        assert len(dept.hours) == 5  # M-F

    def test_brennan_has_correct_hours(self, providers):
        # Brennan's block has no leading dash — tests the no-dash header path
        brennan = next(p for p in providers if p.last_name == "Brennan")
        assert brennan.certification == "PhD, MD"
        hours = brennan.departments[0].hours
        assert len(hours) == 3  # Tu-Th
        from datetime import time
        assert hours[0].open_time  == time(10, 0)
        assert hours[0].close_time == time(16, 0)

    def test_no_provider_has_empty_name(self, providers):
        for p in providers:
            assert p.first_name.strip() != ""
            assert p.last_name.strip()  != ""

    def test_no_department_has_empty_name(self, providers):
        for p in providers:
            for d in p.departments:
                assert d.name.strip() != "", \
                    f"{p.last_name} has a department with no name"
