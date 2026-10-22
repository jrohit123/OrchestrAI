"""Styles for Build with AI (classes start with bd- and ch-)."""

CSS = r"""
.bd-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.bd-card{display:flex;flex-direction:column;gap:6px;padding:14px;color:var(--ink);text-decoration:none}
.bd-card:hover{border-color:var(--brand)}
.bd{display:flex;flex-direction:column;gap:12px;padding:12px 16px 24px}
.bd-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.bd-name{font-size:20px;font-weight:700;border:1px solid transparent;background:transparent;border-radius:8px;padding:4px 8px;flex:1;min-width:200px;color:var(--ink)}
.bd-name:hover,.bd-name:focus{border-color:var(--line);background:var(--surface);outline:none}
.bd-sp{flex:0}
.bd-grid{display:grid;grid-template-columns:minmax(0,440px) minmax(0,1fr);gap:16px;align-items:start}
.bd-chat{background:var(--surface);border:1px solid var(--brand-line);border-radius:var(--r);display:flex;flex-direction:column;height:calc(100vh - var(--top-h) - 110px);min-height:460px;position:sticky;top:calc(var(--top-h) + 12px)}
.bd-log{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:8px}
.bd-msg{border-radius:12px;padding:8px 12px;max-width:92%;white-space:pre-wrap}
.bd-msg.you{align-self:flex-end;background:var(--brand);color:var(--on-brand)}
.bd-msg.ai{align-self:flex-start;background:var(--sunken)}
.bd-msg.ai.warn{background:var(--warn-soft)}
.bd-msg ul{margin:4px 0 0;padding-left:20px}
.bd-qs{display:flex;flex-direction:column;gap:8px;margin-top:8px}
.bd-q{background:var(--surface);border-radius:10px;padding:8px 10px;font-weight:600}
.bd-opts{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;font-weight:400}
.bd-hello{display:flex;flex-direction:column;gap:6px;color:var(--ink)}
.bd-in{display:flex;gap:8px;padding:10px;border-top:1px solid var(--line)}
.bd-in textarea{flex:1;min-width:0;resize:none;border:1px solid var(--line);border-radius:10px;padding:8px 10px;background:var(--bg);color:var(--ink);font:inherit}
.bd-side{display:flex;flex-direction:column;gap:12px;min-width:0}
.bd-lists{display:flex;flex-direction:column;gap:8px}
.bd-list{display:flex;gap:12px;align-items:center;justify-content:space-between;background:var(--brand-soft);border:1px solid var(--brand-line);border-radius:var(--r);padding:10px 12px}
.bd-probs{background:var(--bad-soft);border-radius:var(--r);padding:10px 12px}
.bd-probs ul{margin:4px 0;padding-left:20px}
.chart{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:20px 14px 26px;display:flex;flex-direction:column;align-items:center;text-align:center}
.ch-title{font-weight:700;font-size:16px;margin-bottom:12px}
.ch-box{background:var(--bg);border:2px solid var(--line);border-radius:12px;padding:8px 14px;min-width:180px;max-width:320px;font-weight:600}
.ch-start{background:var(--brand);border-color:var(--brand);color:var(--on-brand);border-radius:99px}
.ch-end{background:var(--sunken);border-radius:99px;min-width:80px;color:var(--muted)}
.ch-q{background:var(--warn-soft);border:2px solid var(--warn);border-radius:12px;padding:8px 14px;max-width:340px;font-weight:700}
.ch-arrow{color:var(--brand);font-size:18px;line-height:1.3}
.ch-split{display:grid;grid-template-columns:1fr 1fr;gap:16px;width:100%;max-width:660px;margin-top:4px}
.ch-lane{display:flex;flex-direction:column;align-items:center;min-width:0}
.ch-yes,.ch-no{font-size:12px;font-weight:700;border-radius:99px;padding:1px 10px}
.ch-yes{color:var(--t-ok);background:var(--ok-soft)} .ch-no{color:var(--t-warn);background:var(--warn-soft)}
.ch-join{font-size:12px;color:var(--muted)}
@media (max-width:900px){.bd-grid{grid-template-columns:minmax(0,1fr)}.bd-chat{position:static;height:520px}.ch-split{grid-template-columns:minmax(0,1fr)}}
"""
