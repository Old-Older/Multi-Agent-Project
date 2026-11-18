"""Loading the team from a role file (mas/team.py)."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from mas.team import DEFAULT_TOOLS, ROLE_FILE, load_team, parse_team

TEAM = """# Scenario 1: Software Development Team

The group consists of **4 agents**.

| Agent ID | Role |
|---|---|
| `lead` | Technical Lead |
| `dev` | Software Developer |
| `qa` | Test Engineer |

## Software Developer (dev)

```text
You are the software developer on a software development team. You build things.
```

## Technical Lead (lead)

```text
You are the technical lead of a software development team.
You coordinate delivery.
```

## Test Engineer (qa)

```text
You are the test engineer.
```
"""


class ParseTest(unittest.TestCase):
    def test_members_follow_the_table_and_carry_their_prompts(self):
        team = parse_team(TEAM)
        self.assertEqual(list(team), ["lead", "dev", "qa"])               # the table's order, not the headings'
        lead = team["lead"]
        self.assertEqual((lead.agent_id, lead.display_name), ("lead", "Technical Lead"))
        self.assertEqual(lead.system_prompt, "You are the technical lead of a software development team.\nYou coordinate delivery.")
        self.assertEqual(lead.capability, "You are the technical lead of a software development team. You coordinate delivery.")
        self.assertEqual(lead.tool_names, DEFAULT_TOOLS)
        self.assertIsNot(team["dev"].tool_names, team["qa"].tool_names)   # nobody shares a mutable list

    def test_tools_can_be_chosen(self):
        self.assertEqual(parse_team(TEAM, ["read_file"])["dev"].tool_names, ["read_file"])

    def test_a_long_prompt_is_clipped_for_the_teammates_but_kept_whole_for_its_owner(self):
        text = "## Big (big)\n\n```text\n" + "word " * 400 + "\n```\n"
        role = parse_team(text)["big"]
        self.assertLessEqual(len(role.capability), 500)
        self.assertTrue(role.capability.endswith("…"))
        self.assertEqual(len(role.system_prompt.split()), 400)

    def test_no_table_the_headings_give_the_order(self):
        text = "## B (b)\n\n```\nyou are b\n```\n\n## A (a)\n\n```\nyou are a\n```\n"
        self.assertEqual(list(parse_team(text)), ["b", "a"])

    def test_a_heading_without_a_prompt_is_not_a_member(self):
        text = "## Notes (see below)\n\nnothing fenced here\n\n## A (a)\n\n```\nyou are a\n```\n"
        self.assertEqual(list(parse_team(text)), ["a"])

    def test_bad_teams_are_refused(self):
        for bad, why in (("nothing here", "no members"),
                         ("## A (a)\n```\nx\n```\n## A again (a)\n```\ny\n```\n", "twice"),
                         ("## H (human)\n```\nx\n```\n", "cannot be an agent id"),
                         ("## O (orchestrator)\n```\nx\n```\n", "cannot be an agent id"),
                         ("## X (1x)\n```\nx\n```\n", "cannot be an agent id")):
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                parse_team(bad)


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_file_or_the_folder_that_holds_it(self):
        (self.tmp / ROLE_FILE).write_text(TEAM, encoding="utf-8")
        self.assertEqual(list(load_team(self.tmp)), ["lead", "dev", "qa"])
        self.assertEqual(list(load_team(self.tmp / ROLE_FILE)), ["lead", "dev", "qa"])

    def test_a_missing_file_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "team file not found"):
            load_team(self.tmp / "nope.md")


if __name__ == "__main__":
    unittest.main()
