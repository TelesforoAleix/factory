# ruff: noqa: F811 - shared pytest fixtures
"""PR reviews use read runs and preserve the existing record-only merge policy."""
import pytest
from test_run_api_runner import PLAN, block, current, edit, item, pr_reply, setup  # noqa: F401


@pytest.mark.parametrize('verdict', ['pass', 'fix', 'missing'])
def test_review_records_verdict_and_retains_owner_gate(setup, verdict):
    r, api, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=True))
    r.run()
    api.finish(current(r), 'done', 'handover', pr_reply())
    r.run()
    review = r.jobs['voice/W1']['requests']['review-1']['run_id']
    answer = {'verdict': 'pass', 'title': 'Reviewed', 'body': 'Passed'} if verdict == 'pass' else dict(verdict='fix', **PLAN)
    api.finish(review, body=block(answer, 'Following prose.') if verdict != 'missing' else 'Malformed verdict')
    gh.checks.return_value = ('green', '')
    r.run()
    assert r.jobs['voice/W1']['review_verdict'] == verdict
    assert item(r)['attention']['kind'] == 'merge'
    gh.merge.assert_not_called()
    edit(r, lambda s: s['attention'].update(approved=True))
    r.run()
    gh.merge.assert_called_once()
