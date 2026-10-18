# Chat navigation and browser settings implementation plan

**Goal:** Implement the approved sidebar chat list, `/c/<id>` URLs, history navigation, and compact browser settings without changing the palette or agent execution protocol.

**Architecture:** Keep the existing static Next export and browser-local IndexedDB store. The application handles history navigation, while FastAPI and the development server serve the app shell at chat URLs. Flush pending chat saves before changing conversation; wait for terminal status when leaving a live run.

**Spec:** Approved design in this conversation: `/` is the launcher, `/c/<id>` is a chat, browser Back/Forward works, chat list replaces the popup, settings contain Start URL, Keep logins, and approval choices.

**Constraints:** No paid API tests, no commits/pushes, retain existing styling, no changes to WebSocket messages.

## Tasks
- [x] Add failing HTTP route tests, then serve the shell for chat deep links without swallowing missing assets or API routes. Add development rewrites.
- [x] Add browser navigation coverage; implement URL-driven selection and reliable save/stop-before-switch behavior. Verify root reload, chat reload, Back/Forward, unknown IDs, quick switching, and deletion.
- [x] Extract shared collapsible sidebar and compact settings panel; wire existing controls and preserve start payload. Verify keyboard/pointer controls and responsive layouts.
- [x] Run ruff, pytest, frontend lint/typecheck/build, isolated browser checks, and final review.

## Verification notes
- HTTP deep-link test reproduced 404 before the route and now passes (3 tests).
- Sidebar/history browser tests reproduced the old popup-only navigation and now pass.
- Six offline browser tests cover URL restore, Back/Forward, stop-before-switch saving, deletion, settings validation, viewport placement, and changes from another tab.
- Final review found two navigation/storage races; both were reproduced and fixed. The asynchronous navigation regression also exposed an empty restored-frame dereference, fixed with an explicit null guard.
- Production lint/typecheck/build passed. Final ruff check and all 91 tests passed, including six browser integration tests against the Python-served production build.
- The production deletion test exposed an unawaited storage transaction; deletion now commits before navigation finishes, and the immediate-reload regression passes.
