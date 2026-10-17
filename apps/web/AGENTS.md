# HyperAgent console

Next.js 15 App Router, React, TypeScript and Tailwind CSS. The app exports static assets served by the Python service in Docker.

- Keep goals and URLs user-supplied. No site presets, simulated results or invented telemetry.
- Read actual WebSocket state; only acknowledge controls when the server acknowledges them.
- Keep all model and browser-provider credentials on the Python service.
- Use observed DOM rectangles for overlays. Never invent coordinates.
- Check `npm run lint`, `npm run typecheck`, and `npm run build`.
