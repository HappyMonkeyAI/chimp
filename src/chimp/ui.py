"""Minimal status dashboard HTML for GET /ui."""

from __future__ import annotations

from chimp import __version__


# Shared by both pages: the router key travels in the URL fragment (#key=...),
# which browsers never send to the server or write to access logs.
_AUTH_JS = """
    function routerKey() {
      return new URLSearchParams(location.hash.slice(1)).get("key");
    }
    function authHeaders(extra) {
      const key = routerKey();
      const headers = Object.assign({}, extra || {});
      if (key) headers.Authorization = "Bearer " + key;
      return headers;
    }
    function keepKey(link) {
      if (location.hash) link.href = link.getAttribute("href").split("#")[0] + location.hash;
    }
"""


def config_page_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>chimp config</title>
  <style>
    body {{ margin: 0; font-family: "Segoe UI", sans-serif; background: #12141a; color: #e8ecf4; }}
    main {{ padding: 1.5rem; max-width: 960px; margin: 0 auto; }}
    a {{ color: #6ea8fe; }}
    textarea {{
      width: 100%; min-height: 28rem; background: #1b1f29; color: #e8ecf4;
      border: 1px solid #2a3142; border-radius: 8px; padding: 0.75rem; font-family: ui-monospace, Consolas, monospace;
    }}
    button {{ margin-top: 0.75rem; padding: 0.45rem 0.9rem; border-radius: 8px; border: 1px solid #6ea8fe; background: transparent; color: #6ea8fe; cursor: pointer; }}
    .ok {{ color: #3dba7e; }} .bad {{ color: #e35d6a; }} .meta {{ color: #9aa3b5; }}
  </style>
</head>
<body>
  <main>
    <p><a id="back" href="/ui">← status</a></p>
    <h1>config.yaml</h1>
    <p class="meta">File: <code id="path">…</code>. Saves the gitignored local file after it validates. Restart chimp to apply. Reading and saving need the separate <code>admin_key</code> (not the inference <code>api_key</code>); open this page as <code>/ui/config#key=&lt;admin_key&gt;</code>. Do not commit secrets.</p>
    <p id="note"></p>
    <form id="cfg">
      <textarea id="body" spellcheck="false" placeholder="Loading…"></textarea>
      <div><button type="submit">Save</button></div>
    </form>
    <script>{_AUTH_JS}
      const note = document.getElementById("note");
      function show(text, ok) {{
        note.textContent = text;
        note.className = ok ? "ok" : "bad";
      }}
      async function errorText(res) {{
        try {{
          const data = await res.json();
          return (data.error && data.error.message) || res.statusText;
        }} catch (_) {{
          return res.statusText;
        }}
      }}
      async function load() {{
        const res = await fetch("/ui/config.yaml", {{ headers: authHeaders(), cache: "no-store" }});
        if (!res.ok) {{
          show("Could not load config (" + res.status + "): " + await errorText(res), false);
          return;
        }}
        document.getElementById("path").textContent = res.headers.get("x-chimp-config-path") || "(unset)";
        document.getElementById("body").value = await res.text();
      }}
      document.getElementById("cfg").addEventListener("submit", async (event) => {{
        event.preventDefault();
        const res = await fetch("/ui/config", {{
          method: "POST",
          headers: authHeaders({{ "content-type": "text/yaml" }}),
          body: document.getElementById("body").value,
        }});
        if (res.ok) {{
          show((await res.json()).message, true);
        }} else {{
          show("Not saved (" + res.status + "): " + await errorText(res), false);
        }}
      }});
      keepKey(document.getElementById("back"));
      load();
    </script>
  </main>
</body>
</html>
"""


def status_page_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>chimp status</title>
  <style>
    :root {{
      --bg: #12141a;
      --panel: #1b1f29;
      --text: #e8ecf4;
      --muted: #9aa3b5;
      --ok: #3dba7e;
      --bad: #e35d6a;
      --accent: #6ea8fe;
      --line: #2a3142;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "IBM Plex Sans", sans-serif;
      background: radial-gradient(1200px 600px at 10% -10%, #243049 0%, var(--bg) 55%);
      color: var(--text);
      min-height: 100vh;
    }}
    header {{
      padding: 1.5rem 1.75rem 0.5rem;
      display: flex;
      gap: 1rem;
      align-items: baseline;
      flex-wrap: wrap;
    }}
    h1 {{
      margin: 0;
      font-size: 1.6rem;
      letter-spacing: 0.04em;
    }}
    .meta {{ color: var(--muted); font-size: 0.95rem; }}
    main {{
      padding: 1rem 1.75rem 2.5rem;
      display: grid;
      gap: 1.25rem;
    }}
    section {{
      background: color-mix(in srgb, var(--panel) 92%, black);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 1rem 1.1rem;
    }}
    h2 {{
      margin: 0 0 0.75rem;
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      font-weight: 600;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }}
    th, td {{
      text-align: left;
      padding: 0.45rem 0.35rem;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 500; }}
    .pill {{
      display: inline-block;
      padding: 0.1rem 0.45rem;
      border-radius: 999px;
      font-size: 0.75rem;
      border: 1px solid var(--line);
    }}
    .ok {{ color: var(--ok); border-color: color-mix(in srgb, var(--ok) 40%, var(--line)); }}
    .bad {{ color: var(--bad); border-color: color-mix(in srgb, var(--bad) 40%, var(--line)); }}
    .models {{ color: var(--muted); font-size: 0.8rem; max-width: 28rem; }}
    .empty {{ color: var(--muted); font-size: 0.9rem; }}
    a {{ color: var(--accent); }}
    button {{
      background: transparent;
      color: var(--accent);
      border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--line));
      border-radius: 8px;
      padding: 0.35rem 0.7rem;
      cursor: pointer;
    }}
  </style>
</head>
<body>
  <header>
    <h1>chimp</h1>
    <div class="meta">v{__version__} · live from <a href="/status">/status</a></div>
    <button type="button" id="refresh">Refresh</button>
  </header>
  <main>
    <section>
      <h2>Endpoints</h2>
      <div id="endpoints" class="empty">Loading…</div>
    </section>
    <section>
      <h2>Sticky pins</h2>
      <div id="sticky" class="empty">Loading…</div>
    </section>
    <section>
      <h2>Recent placements</h2>
      <div id="recent" class="empty">Loading…</div>
    </section>
    <section>
      <h2>Config</h2>
      <p class="meta">Edit gitignored <code>config.yaml</code> at <a id="config-link" href="/ui/config">/ui/config</a> (needs <code>admin_key</code>; restart required). Prefer env placeholders for keys.</p>
    </section>
  </main>
  <script>{_AUTH_JS}
    async function load() {{
      const res = await fetch("/status", {{ headers: authHeaders() }});
      if (!res.ok) {{
        const hint = res.status === 401 ? " — open this page as /ui#key=<api_key>" : "";
        document.getElementById("endpoints").textContent = "Could not load /status (" + res.status + ")" + hint;
        return;
      }}
      const data = await res.json();
      renderEndpoints(data.endpoints || []);
      renderSticky(data.sticky || []);
      renderRecent(data.recent || []);
    }}
    function renderEndpoints(rows) {{
      if (!rows.length) {{
        document.getElementById("endpoints").innerHTML = '<p class="empty">No endpoints.</p>';
        return;
      }}
      const body = rows.map(ep => {{
        const health = ep.healthy
          ? '<span class="pill ok">healthy</span>'
          : '<span class="pill bad">down</span>';
        const models = (ep.models || []).map(m => {{
          const flag = m.loaded === true ? "warm" : (m.loaded === false ? "cold" : "?");
          return m.id + " (" + flag + ")";
        }}).join(", ") || "—";
        return `<tr>
          <td><strong>${{escapeHtml(ep.name)}}</strong><div class="models">${{escapeHtml(ep.kind)}} · ${{escapeHtml(ep.tier || "primary")}}</div></td>
          <td>${{health}}</td>
          <td>${{ep.inflight || 0}} / ${{ep.max_concurrent || 1}}</td>
          <td class="models">${{escapeHtml(models)}}</td>
        </tr>`;
      }}).join("");
      document.getElementById("endpoints").innerHTML = `<table>
        <thead><tr><th>Name</th><th>Health</th><th>Inflight</th><th>Models</th></tr></thead>
        <tbody>${{body}}</tbody></table>`;
    }}
    function renderSticky(rows) {{
      if (!rows.length) {{
        document.getElementById("sticky").innerHTML = '<p class="empty">No active pins.</p>';
        return;
      }}
      const body = rows.map(pin => `<tr>
        <td class="models">${{escapeHtml(pin.key)}}</td>
        <td>${{escapeHtml(pin.endpoint)}}</td>
        <td>${{escapeHtml(pin.model)}}</td>
        <td class="models">${{new Date(pin.expires_at * 1000).toLocaleString()}}</td>
      </tr>`).join("");
      document.getElementById("sticky").innerHTML = `<table>
        <thead><tr><th>Key</th><th>Endpoint</th><th>Model</th><th>Expires</th></tr></thead>
        <tbody>${{body}}</tbody></table>`;
    }}
    function renderRecent(rows) {{
      if (!rows.length) {{
        document.getElementById("recent").innerHTML = '<p class="empty">No placements yet.</p>';
        return;
      }}
      const body = rows.slice().reverse().map(row => `<tr>
        <td class="models">${{new Date((row.time || 0) * 1000).toLocaleTimeString()}}</td>
        <td>${{escapeHtml(row.requested || "")}}</td>
        <td>${{escapeHtml(row.endpoint || "")}}</td>
        <td>${{escapeHtml(row.model || "")}}</td>
        <td>${{escapeHtml(row.reason || "")}}</td>
      </tr>`).join("");
      document.getElementById("recent").innerHTML = `<table>
        <thead><tr><th>When</th><th>Requested</th><th>Endpoint</th><th>Model</th><th>Reason</th></tr></thead>
        <tbody>${{body}}</tbody></table>`;
    }}
    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, ch => ({{
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }})[ch]);
    }}
    keepKey(document.getElementById("config-link"));
    document.getElementById("refresh").addEventListener("click", load);
    load();
    setInterval(load, 5000);
  </script>
</body>
</html>
"""
