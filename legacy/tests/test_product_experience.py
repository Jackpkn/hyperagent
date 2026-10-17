"""Goal-first entry and source attribution, with no paid API requests."""

from unittest.mock import AsyncMock

import pytest

from hyperagent import claude_sys2
from hyperagent.evidence import EvidenceLedger, grounded_urls
from tests.test_server import FakeAgent, client, receive  # noqa: F401


def test_goal_only_start_uses_configured_entry_page(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("START_PAGE_URL", "https://search.test/")
    with client.websocket_connect('/ws/agent') as ws:
        ws.send_json({'command': 'START', 'goal': 'Research engineering careers', 'auto_run': False})
        result = receive(ws, 'STATE_SNAPSHOT')
        assert result['state']['page']['url'] == 'https://search.test/'
        assert result['state']['goal'] == 'Research engineering careers'


def test_observed_application_links_are_retained_with_their_source():
    ledger = EvidenceLedger()
    ledger.observe({'url': 'https://company.test/careers', 'title': 'Careers', 'text': 'Robotics engineer',
                    'actions': [{'label': 'Robotics engineer', 'href': 'https://jobs.test/opening/12'},
                                {'label': 'Unsafe', 'href': 'javascript:alert(1)'}]})
    assert ledger.sources[0]['links'] == [{'label': 'Robotics engineer', 'url': 'https://jobs.test/opening/12'}]


@pytest.mark.anyio
async def test_artifact_cannot_invent_an_application_url(monkeypatch):
    sources = [{'id': 's1', 'url': 'https://company.test/careers', 'title': 'Careers',
                'text': 'Robotics engineer', 'links': [{'label': 'Robotics engineer',
                                                      'url': 'https://jobs.test/opening/12'}]}]
    ref = {'source_id': 's1', 'field': 'text', 'quote': 'Robotics engineer'}
    response = {'executive_summary': 'An opening was observed.', 'evidence': [ref], 'rows': [
        {'data': {'role': 'Robotics engineer', 'application_url': 'https://invented.test/apply'}, 'evidence': [ref]},
    ]}
    monkeypatch.setattr(claude_sys2, '_request', AsyncMock(return_value=response))
    result = await claude_sys2.compile_final_deliverable('Find jobs', sources[0]['url'], [], [], evidence=sources)
    assert result['available'] is False
    response['rows'][0]['data']['application_url'] = 'https://jobs.test/opening/12'
    result = await claude_sys2.compile_final_deliverable('Find jobs', sources[0]['url'], [], [], evidence=sources)
    assert result['available'] is True


@pytest.mark.parametrize('url', ['//invented.test/apply', 'HTTPS://invented.test/apply',
                                  'javascript:alert(1)', '/invented', 'not a URL'])
def test_url_fields_require_observed_absolute_links(url):
    assert not grounded_urls({'application_url': url}, [])
    assert not grounded_urls({'application_links': [url]}, [])
    assert grounded_urls({'application_url': None}, [])


def test_protocol_relative_links_cannot_hide_in_prose_or_generic_fields():
    assert not grounded_urls('Apply at //invented.test/apply', [])
    assert not grounded_urls({'application': '//invented.test/apply'}, [])


@pytest.mark.anyio
async def test_reconciled_report_does_not_show_resolved_issues_as_outstanding():
    from unittest.mock import Mock

    from hyperagent.server import AgentSession

    session = AgentSession(Mock(send_json=AsyncMock()))
    try:
        await session.send_artifact({'unresolved_issues': ['A concern dismissed by verification']},
                                    {'satisfied': True, 'remaining_requirements': [], 'reason': 'All supported'}, [])
        result = session.ws.send_json.call_args.args[0]['deliverable']
        assert result['unresolved_issues'] == []
        assert result['reviewed_issues'] == ['A concern dismissed by verification']
    finally:
        session.executor.shutdown(wait=True)


@pytest.mark.anyio
async def test_summary_cannot_link_to_an_uncited_observation(monkeypatch):
    sources = [{'id': 's1', 'url': 'https://one.test/', 'text': 'Opening', 'title': 'One'},
               {'id': 's2', 'url': 'https://two.test/', 'text': 'Other opening', 'title': 'Two'}]
    response = {'executive_summary': 'Apply at https://two.test/', 'rows': [],
                'evidence': [{'source_id': 's1', 'field': 'text', 'quote': 'Opening'}]}
    monkeypatch.setattr(claude_sys2, '_request', AsyncMock(return_value=response))
    result = await claude_sys2.compile_final_deliverable('Find jobs', '', [], [], evidence=sources)
    assert result['available'] is False


@pytest.mark.anyio
async def test_verifier_cannot_complete_with_remaining_requirements(monkeypatch):
    monkeypatch.setattr(claude_sys2, '_request', AsyncMock(return_value={
        'satisfied': True, 'reason': 'Some results found', 'evidence_quotes': ['Opening'],
        'remaining_requirements': ['Founder details are missing'],
    }))
    result = await claude_sys2.verify_outcome('Find founders and jobs', 'Report both',
                                             {'text': 'Opening'}, [])
    assert result['satisfied'] is False
    assert 'Founder details' in result['reason']


@pytest.mark.anyio
async def test_benchmark_records_connection_failures(tmp_path, monkeypatch):
    import json
    from argparse import Namespace
    from unittest.mock import Mock

    from tools import benchmark

    monkeypatch.setattr(benchmark.websockets, 'connect', Mock(side_effect=OSError('Connection refused')))
    await benchmark.run(Namespace(output=str(tmp_path), endpoint='ws://offline.test', origin=None,
                                  goal='Research', url=None, timeout=1, max_actions=1))
    result = json.loads((tmp_path / 'result.json').read_text())
    assert result['terminal_event'] == 'transport_error'
    assert result['verified'] is False
    assert result['error_type'] == 'OSError'
