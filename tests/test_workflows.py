import json
import re
from pathlib import Path

from vpnmy.globalping import CHECKHOST_DEADLINE_SECONDS

ROOT = Path(__file__).resolve().parents[1]


def test_update_workflow_template_reserves_time_for_all_stages():
    workflow = (ROOT / "workflow-templates/update.yml").read_text(encoding="utf-8")
    match = re.search(r"^    timeout-minutes: (\d+)$", workflow, flags=re.MULTILINE)
    assert match is not None
    timeout_seconds = int(match[1]) * 60
    config = json.loads((ROOT / "config/subscription.json").read_text(encoding="utf-8"))
    # RU deadlines must leave at least ten minutes for setup, local/deep checks,
    # ASN lookup and publication, without overlapping the next 30-minute schedule.
    assert timeout_seconds >= config["ru_check_deadline_seconds"] + CHECKHOST_DEADLINE_SECONDS + 600
    assert timeout_seconds < 30 * 60


def test_update_template_preserves_active_workflow_except_job_timeout():
    # The template is installed manually: CI must work both before and after the
    # owner copies it into .github/workflows/update.yml. Keep all other steps intact.
    def normalize(workflow):
        return [
            line.rstrip()
            for line in workflow.splitlines()
            if line.strip()
            and not line.lstrip().startswith("#")
            and not re.fullmatch(r"    timeout-minutes: \d+", line)
        ]

    active = (ROOT / ".github/workflows/update.yml").read_text(encoding="utf-8")
    template = (ROOT / "workflow-templates/update.yml").read_text(encoding="utf-8")
    assert normalize(active) == normalize(template)
