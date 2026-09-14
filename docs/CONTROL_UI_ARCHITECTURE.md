# 6178 control UI boundaries

The 6178 control plane keeps backend behavior and browser presentation in separate modules. New pages and refactors should reuse the existing `lanzou_update_push_api_server/control_ui/` asset system instead of embedding complete CSS/JavaScript applications inside backend modules.

## Ownership

- `lanzou_update_push_api_server/control_ui/`
  - owns page renderers and reusable page markup
  - owns local browser assets under `control_ui/assets/`
  - exposes `ASSET_DIRECTORY`, mounted by the application at `/control-assets`
- backend/control modules such as `lolban_console.py`
  - own validation, persistence, runtime calls, secret handling, diagnostics, and route installation
  - may import a renderer from `control_ui`, but must not own a second copy of that page's CSS or JavaScript
- `control_navigation.py`
  - remains the compatibility decorator for legacy-style page shells until those pages are explicitly migrated to the shared console shell

## LOLBan console

The LOLBan console is split into:

- `control_ui/lolban.py` — page shell and stable DOM IDs
- `control_ui/assets/lolban.css` — page-specific presentation
- `control_ui/assets/lolban.js` — browser behavior and admin API calls
- `lolban_console.py` — backend configuration, redaction, token persistence/hot reload, runtime diagnostics, provider/formal tests, and route installation

The public route and admin API contract remain unchanged:

- `GET /query-console/lolban`
- `GET /admin/query-console/lolban`
- `POST /admin/query-console/lolban/save`
- `POST /admin/query-console/lolban/provider-secret`
- `POST /admin/query-console/lolban/4png-token`
- `POST /admin/query-console/lolban/test`

## Compatibility and regression rules

- Existing DOM IDs used by `lolban.js` are part of the page contract and should not be renamed casually.
- Provider Token controls remain dynamically rendered inside provider cards; they are verified in the JavaScript asset rather than by requiring application source code inside the HTML response.
- `tests/check_ui_assets.py` must validate the external JavaScript with `node --check` and verify required API/DOM markers.
- Structural tests must fail if the LOLBan backend starts embedding its page CSS or application JavaScript again.
- Moving existing inline browser event handlers to delegated listeners is a separate behavior/UI cleanup task; asset extraction itself must not silently change the page workflow.

## Security

- Browser assets never contain real provider secrets.
- Secret values remain server-side and use the existing masked round-trip and dedicated secret endpoints.
- UI refactors must not change control-page authentication or make neighboring `/admin/*` paths public.
- The static asset prefix is read-only and remains limited to `/control-assets`.
