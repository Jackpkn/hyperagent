"""Offline UI integration checks. Run with CONSOLE_URL pointing at a local frontend."""
import json
import os
import re

import pytest
from playwright.async_api import async_playwright, expect

pytestmark = pytest.mark.skipif(not os.environ.get("CONSOLE_URL"), reason="Set CONSOLE_URL to test the frontend")


@pytest.fixture
async def console_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 960}, color_scheme="dark")
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        sent = []
        sockets = []

        def connect(ws):
            sockets.append(ws)
            ws.on_message(lambda message: sent.append(json.loads(message)))
            ws.send(json.dumps({"type": "hello", "session_id": "ui-check", "model": "test-model",
                                "models": ["test-model"], "max_steps": 30}))

        await page.context.route_web_socket("**/ws/agent", connect)
        base = os.environ["CONSOLE_URL"].rstrip("/")
        await page.goto(base)
        await page.evaluate("""async () => {
          const db = await new Promise((resolve, reject) => {
            const r = indexedDB.open('hyperagent', 1);
            r.onupgradeneeded = () => {
              for (const name of ['chats', 'frames', 'kv']) {
                if (!r.result.objectStoreNames.contains(name))
                  r.result.createObjectStore(name, name === 'chats' ? {keyPath:'id'} : undefined);
              }
            };
            r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error);
          });
          await new Promise((resolve, reject) => {
            const tx = db.transaction(['chats','kv'], 'readwrite');
            for (const [id,title] of [['c-first','First saved chat'],['c-second','Second saved chat']]) {
              tx.objectStore('chats').put({id,title,createdAt:1,updatedAt:2,turns:[{
                id:'t-'+id,goal:title,startedAt:1,run:'done',mode:'risky',plan:[],steps:[],feed:[],
                findings:[],usage:null,result:null,frameSteps:[]
              }]});
            }
            tx.objectStore('kv').put('c-second','activeChatId');
            tx.oncomplete=resolve; tx.onerror=()=>reject(tx.error);
          }); db.close();
        }""")
        await page.reload()
        yield page, base, sent, sockets
        await browser.close()
        assert not errors, errors


async def test_sidebar_chat_urls_and_browser_history(console_page):
    page, base, _, _ = console_page
    await expect(page.get_by_role("heading", name="What should the agent")).to_be_visible()
    first = page.get_by_role("link", name="First saved chat", exact=True)
    await expect(first).to_be_visible()
    await first.click()
    await expect(page).to_have_url(base + "/c/c-first")
    await expect(page.locator(".run-shell")).to_be_visible()
    await expect(page.get_by_role("dialog")).to_have_count(0)
    await page.go_back()
    await expect(page).to_have_url(base + "/")
    await expect(page.get_by_label("Your goal")).to_be_visible()

    await page.go_forward()
    await expect(page).to_have_url(base + "/c/c-first")
    await expect(page.locator(".run-shell")).to_be_visible()
    await page.reload()
    await expect(page.locator(".run-shell")).to_be_visible()
    icon = page.locator('link[rel="icon"]')
    await expect(icon).to_have_attribute('href', '/hyperagent-icon.svg')
    response = await page.request.get(base + '/hyperagent-icon.svg')
    assert response.status == 200
    assert 'image/svg+xml' in response.headers['content-type']
    assert '#60a5fa' in await response.text()
    await page.goto(base + "/c/c-second")
    await expect(page.locator(".run-shell")).to_contain_text("Second saved chat")
    await page.goto(base + "/c/missing-chat")
    await expect(page.get_by_role("alert").filter(has_text="not available")).to_be_visible()
    await expect(page.get_by_label("Your goal")).to_be_visible()


async def test_run_header_details_and_controls(console_page):
    page, _, sent, sockets = console_page
    goal = "Review the latest release notes and compile a detailed report with source links and outstanding questions"
    await page.get_by_label('Your goal').fill(goal)
    await page.get_by_role('button', name='Start agent').click()
    sockets[-1].send(json.dumps({'type':'status','state':'running','step':7,'detail':'Reading sources'}))
    sockets[-1].send(json.dumps({'type':'usage','llm_calls':2,'input_tokens':100,'output_tokens':50,
                                'cost_usd':0.09,'elapsed_s':67,'fast_calls':4,'fast_ms_total':1660}))
    header = page.locator('header.top-bar')
    await expect(header.get_by_role('button', name='Profile', exact=True)).to_have_count(0)
    await expect(header.get_by_role('button', name='Memory', exact=True)).to_have_count(0)
    centers = await header.evaluate("""el =>
      ['.brand-btn', '.run-status-pill', '.goal-pill', '.telemetry-bar',
       '.mode-select-wrap', '.control-actions', '.run-details'].map(selector => {
        const rect = el.querySelector(selector).getBoundingClientRect();
        return rect.y + rect.height / 2;
      })""")
    assert max(centers) - min(centers) < 2, centers
    assert (await header.bounding_box())['height'] <= 52
    await page.screenshot(path='/private/tmp/hyperagent-header-single-row.png', full_page=True)

    await expect(header.get_by_text('Estimated tokens saved')).not_to_be_visible()
    await header.get_by_role('button', name='Run details', exact=True).click()
    panel = header.get_by_role('region', name='Run details')
    await expect(panel).not_to_contain_text('tokens saved')
    await expect(panel).to_contain_text('Jev decisions')
    await expect(panel).to_contain_text('415ms')
    await page.keyboard.press('Escape')
    await expect(panel).not_to_be_visible()
    assert not any(m['type'] == 'pause' for m in sent)
    await header.get_by_label('Approval mode').select_option('always')
    await header.get_by_role('button', name='Pause', exact=True).click()
    await page.wait_for_timeout(100)
    assert any(m['type'] == 'pause' for m in sent)
    assert any(m['type'] == 'set_mode' and m['approval_mode'] == 'always' for m in sent)
    sockets[-1].send(json.dumps({'type':'status','state':'paused','step':7,'detail':'Paused'}))
    await header.get_by_role('button', name='Resume', exact=True).click()
    await page.set_viewport_size({'width':320,'height':960})
    await header.get_by_role('button', name='Stop', exact=True).click()
    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    await header.get_by_role('button', name='Confirm stop', exact=True).click()
    sockets[-1].send(json.dumps({'type':'status','state':'stopped','step':7,'detail':'Stopped'}))
    await expect(header.get_by_role('button', name='New task', exact=True)).to_be_visible()
    await expect(header.get_by_role('button', name='Pause', exact=True)).to_have_count(0)
    await header.get_by_role('button', name='Show full task').click()
    await expect(header.locator('.goal-drawer-text')).to_have_text(goal)
    for width in [320, 375, 768, 1440]:
        await page.set_viewport_size({'width':width,'height':960})
        await header.get_by_role('button', name='Run details', exact=True).click()
        await expect(panel).to_be_visible()
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        bounds = await panel.bounding_box()
        assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
        await page.screenshot(path=f'/private/tmp/hyperagent-header-{width}.png', full_page=True)
        await page.keyboard.press('Escape')
    await header.get_by_role('button', name='New task', exact=True).click()
    await expect(page.get_by_label('Your goal')).to_be_visible()


async def test_unknown_outcome_is_not_shown_as_verified(console_page):
    page, _, _, sockets = console_page
    await page.get_by_label('Your goal').fill('Check a control')
    await page.get_by_role('button', name='Start agent').click()
    sockets[-1].send(json.dumps({'type':'status','state':'running','step':1}))
    step = {'type':'step','id':'s1','n':1,'status':'ok','started_at':1,'ended_at':2,
            'action':{'name':'click','args':{},'label':'Open panel'},
            'verification':{'status':'unverified','detail':'Confirm the result from the page.'}}
    sockets[-1].send(json.dumps(step))
    card = page.get_by_role('article', name='Step 1: Open panel', exact=True)
    await expect(card).to_contain_text('Unverified')
    await expect(card.locator('.stream-bullet.is-solid')).to_have_text('?')
    sockets[-1].send(json.dumps({**step,'verification':{'status':'verified','detail':'Control state confirmed.'}}))
    await expect(card).to_contain_text('Verified')
    await expect(card.locator('.stream-bullet.is-solid')).to_have_text('✓')


async def test_browser_settings_and_start_navigation(console_page):
    page, base, sent, sockets = console_page
    await expect(page.get_by_label("Start at a URL (optional)")).not_to_be_visible()
    await page.get_by_role("button", name="Browser settings").click()
    await page.get_by_label("Start at a URL (optional)").fill("https://example.invalid")
    await page.get_by_role("radio", name="Ask before every action").check()
    await page.get_by_role("switch", name="Keep logins").click()
    await page.keyboard.press("Escape")
    await expect(page.get_by_label("Start at a URL (optional)")).not_to_be_visible()
    await page.get_by_label("Your goal").fill("UI verification")
    await page.get_by_label("Your goal").press("Control+Enter")
    await expect(page).to_have_url(re.compile(r"/c/c-[a-z0-9-]+$"))
    path = page.url
    starts = [m for m in sent if m['type'] == 'start']
    assert len(starts) == 1
    assert starts[0]['approval_mode'] == 'always'
    assert starts[0]['persist_session'] is True
    assert starts[0]['start_url'] == 'https://example.invalid'
    await page.go_back()
    await expect(page.get_by_role('status').filter(has_text='Stopping')).to_be_visible()
    assert len([m for m in sent if m['type'] == 'stop']) == 1
    sockets[-1].send(json.dumps({'type':'result','summary':'Saved before leaving','success':False,
                                'columns':[],'rows':[],'sources':[],'issues':[]}))
    sockets[-1].send(json.dumps({'type':'status','state':'stopped','step':0,'detail':'Stopped'}))
    await expect(page.get_by_label('Your goal')).to_be_visible()
    await expect(page).to_have_url(base + '/')
    await page.go_forward()
    await expect(page).to_have_url(path)
    await expect(page.locator('.run-shell')).to_contain_text('Saved before leaving')


async def test_inline_answers_progress_and_chat_usage(console_page):
    page, _, sent, sockets = console_page
    await page.evaluate("""async () => {
      const db = await new Promise(resolve => { const r=indexedDB.open('hyperagent',1);
        r.onsuccess=()=>resolve(r.result); });
      await new Promise((resolve,reject) => {
        const tx=db.transaction('chats','readwrite'), store=tx.objectStore('chats');
        const request=store.get('c-first');
        request.onsuccess=()=>{ const chat=request.result;
          chat.turns[0].usage={llm_calls:1,input_tokens:30,output_tokens:20,cost_usd:0.01,elapsed_s:1};
          store.put(chat); };
        tx.oncomplete=resolve; tx.onerror=()=>reject(tx.error);
      }); db.close();
    }""")
    await page.reload()
    await page.get_by_label('Your goal').fill('First task')
    await page.get_by_role('button', name='Start agent').click()
    await expect(page.locator('header.top-bar')).to_be_visible()
    def emit(message):
        sockets[-1].send(json.dumps(message))
    def usage(input_tokens, output_tokens, cost):
        emit({'type':'usage','llm_calls':1,'input_tokens':input_tokens,
              'output_tokens':output_tokens,'cost_usd':cost,'elapsed_s':5})
    step = {'type':'step','id':'s1','n':1,'status':'running','started_at':1,
            'action':{'name':'ask_user','args':{},'label':'Confirm the destination'}}
    emit(step)
    emit({'type':'plan','items':[{'text':'Confirm destination','status':'active'},
                                {'text':'Compare options','status':'pending'}]})
    emit({'type':'question','step_id':'s1','question':'Which city should I use?'})
    emit({'type':'status','state':'awaiting_user','step':1,'detail':'Waiting for destination'})
    card = page.get_by_role('region', name='Agent question')
    await expect(card).to_contain_text('Which city should I use?')
    await page.screenshot(path='/private/tmp/hyperagent-inline-question.png', full_page=True)
    await card.get_by_label('Your answer').fill('Bengaluru')
    await card.get_by_role('button', name='Send answer').click()
    await expect(card).to_contain_text('Bengaluru')
    await expect(card.get_by_role('button', name='Send answer')).to_have_count(0)
    await expect(page.locator('.guidance-bubble').filter(has_text='Bengaluru')).to_have_count(0)
    assert any(m['type'] == 'guide' and m['text'] == 'Bengaluru' for m in sent)
    emit({**step,'status':'ok','ended_at':2,'result':'You answered: Bengaluru'})
    emit({'type':'plan','items':[{'text':'Confirm destination','status':'done'},
                                {'text':'Compare options','status':'active'}]})
    await expect(page.get_by_label('Agent plan')).to_contain_text('Confirm destination')
    await expect(page.get_by_label('Agent plan').locator('li[data-status="done"]')).to_contain_text('✓')
    await expect(page.locator('.stream-step[data-status="ok"] .stream-line-action')).to_contain_text('✓')
    usage(100, 50, 0.01)
    usage(100, 50, 0.01)  # cumulative snapshots must never be added twice
    emit({'type':'status','state':'done','step':1,'detail':'Done'})
    await expect(page.get_by_role('button', name='New task', exact=True)).to_be_visible()
    await page.get_by_label('Follow-up or new task goal').fill('Second task')
    await page.locator('.sidebar-composer').get_by_role('button', name='Send', exact=True).click()
    await expect(page.locator('header.top-bar .goal-pill')).to_contain_text('Second task')
    usage(200, 100, 0.02)
    emit({'type':'status','state':'done','step':1,'detail':'Done'})
    header = page.locator('header.top-bar')
    await header.get_by_role('button', name='Run details').click()
    table = page.get_by_role('table', name='Token and cost totals')
    await expect(table.get_by_role('row').filter(has_text='This task')).to_contain_text('300')
    await expect(table.get_by_role('row').filter(has_text='This chat')).to_contain_text('450')
    await expect(table.get_by_role('row').filter(has_text='All saved chats')).to_contain_text('500')
    await page.screenshot(path='/private/tmp/hyperagent-usage-totals.png', full_page=True)
    await page.reload()
    await page.get_by_role('button', name='Run details', exact=True).click()
    totals = page.get_by_role('table', name='Token and cost totals')
    await expect(totals.get_by_role('row').filter(has_text='This chat')).to_contain_text('450')
    await expect(totals.get_by_role('row').filter(has_text='All saved chats')).to_contain_text('500')
    await page.keyboard.press('Escape')
    await page.get_by_role('button', name='Show 1 step', exact=True).click()
    await expect(page.get_by_role('region', name='Agent question')).to_contain_text('Bengaluru')


async def test_switching_and_deleting_chats_preserves_other_conversations(console_page):
    page, base, _, _ = console_page
    await page.get_by_role('link', name='First saved chat', exact=True).click()
    await expect(page.locator('.run-shell')).to_contain_text('First saved chat')
    await page.get_by_role('button', name='Expand chat sidebar', exact=True).click()
    await page.get_by_role('link', name='Second saved chat', exact=True).click()
    await expect(page.locator('.run-shell')).to_contain_text('Second saved chat')
    await page.get_by_role('link', name='First saved chat', exact=True).click()
    await expect(page.locator('.run-shell')).to_contain_text('First saved chat')
    await page.get_by_role('button', name='Delete chat: First saved chat', exact=True).click()
    await expect(page).to_have_url(base + '/')
    await expect(page.get_by_label('Your goal')).to_be_visible()
    await page.reload()
    await expect(page.get_by_role('link', name='Second saved chat', exact=True)).to_be_visible()
    await expect(page.get_by_role('link', name='First saved chat', exact=True)).to_have_count(0)


async def test_settings_validation_and_mobile_navigation(console_page):
    page, _, sent, _ = console_page
    await page.get_by_role('button', name='Browser settings').click()
    await page.get_by_label('Start at a URL (optional)').fill('invalid')
    await page.keyboard.press('Escape')
    await page.get_by_label('Your goal').fill('UI verification')
    await page.get_by_role('button', name='Start agent').click()
    await expect(page.get_by_label('Start at a URL (optional)')).to_be_focused()
    assert not any(m['type'] == 'start' for m in sent)
    await page.get_by_label('Start at a URL (optional)').fill('')
    await page.keyboard.press('Escape')
    for width in [320, 375, 768, 1440]:
        await page.set_viewport_size({'width':width,'height':960})
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await page.get_by_role('button', name='Browser settings').click()
        await expect(page.get_by_role('radio', name='Fully autonomous')).to_be_visible()
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        panel = await page.locator('#browser-settings-panel').bounding_box()
        assert panel and panel['y'] >= 0 and panel['y'] + panel['height'] <= 960
        await page.screenshot(path=f'/private/tmp/hyperagent-settings-{width}.png', full_page=True)
        await page.keyboard.press('Escape')
    await page.set_viewport_size({'width':375,'height':900})
    await page.reload()
    await expect(page.get_by_role('link', name='First saved chat', exact=True)).not_to_be_visible()
    await page.get_by_role('button', name='Expand chat sidebar', exact=True).click()
    await page.get_by_role('link', name='First saved chat', exact=True).click()
    await expect(page.locator('.run-shell')).to_be_visible()


async def test_forward_while_stopping_keeps_url_and_chat_in_sync(console_page):
    page, base, _, sockets = console_page
    await page.get_by_label('Your goal').fill('UI verification')
    await page.get_by_role('button', name='Start agent').click()
    await expect(page).to_have_url(re.compile(r'/c/c-[a-z0-9-]+$'))
    path = page.url
    await page.go_back()
    await expect(page.get_by_role('status').filter(has_text='Stopping')).to_be_visible()
    await page.go_forward()
    await expect(page).to_have_url(path)
    sockets[-1].send(json.dumps({'type':'result','summary':'Saved after Forward','success':False,
                                'columns':[],'rows':[],'sources':[],'issues':[]}))
    sockets[-1].send(json.dumps({'type':'status','state':'stopped','step':0,'detail':'Stopped'}))
    await expect(page.locator('.navigation-notice')).to_have_count(0)
    await expect(page.locator('.run-shell')).to_contain_text('Saved after Forward')
    await expect(page).to_have_url(path)
    await page.go_back()
    await expect(page).to_have_url(base + '/')
    await expect(page.get_by_label('Your goal')).to_be_visible()


async def test_reopening_reads_changes_saved_by_another_tab(console_page):
    page, _, _, _ = console_page
    # A separate tab changes the shared IndexedDB after this tab has loaded its sidebar.
    other = await page.context.new_page()
    await other.goto(os.environ['CONSOLE_URL'])
    await other.evaluate("""async () => {
      const db = await new Promise(resolve => { const r=indexedDB.open('hyperagent',1);
        r.onsuccess=()=>resolve(r.result); });
      await new Promise((resolve, reject) => {
        const tx=db.transaction('chats','readwrite'), store=tx.objectStore('chats');
        const r=store.get('c-first');
        r.onsuccess=()=>{ const chat=r.result;
          chat.turns.push({...chat.turns[0],id:'t-external',goal:'Saved in another tab'});
          store.put(chat);
        };
        tx.oncomplete=resolve; tx.onerror=()=>reject(tx.error);
      }); db.close();
    }""")
    await other.close()
    await page.get_by_role('link', name='First saved chat', exact=True).click()
    await expect(page.locator('.run-shell')).to_contain_text('Saved in another tab')
