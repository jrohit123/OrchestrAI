"""Styles for the Announcements screen and the flats on the People screen (classes start with ann- and fl-)."""

CSS = r"""
.ann-grid{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:16px;align-items:start}
.ann-side{position:sticky;top:calc(var(--top-h) + 12px)}
@media (max-width:1100px){.ann-grid{grid-template-columns:minmax(0,1fr)}.ann-side{position:static}}
.ann-tickline{cursor:pointer}
.ann-choices{display:flex;flex-wrap:wrap;gap:8px}
.ann-choice{display:inline-flex;align-items:stretch;border:1px solid var(--line);border-radius:10px;background:var(--surface)}
.ann-choice>button:first-child{display:grid;text-align:left;gap:1px;padding:8px 12px;background:none;border:0;font:inherit;color:inherit;cursor:pointer}
.ann-choice .x{border:0;background:none;color:var(--muted);padding:0 8px;cursor:pointer;font-size:16px}
.ann-choice.on{border-color:var(--brand);background:var(--brand-soft)}
.ann-group{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.ann-lbl{width:150px;font-weight:600;font-size:13px;color:var(--ink-2)}
@media (max-width:700px){.ann-lbl{width:100%}}
.ann-tick{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);border-radius:9px;padding:6px 11px;cursor:pointer;background:var(--surface);font-size:13.5px;user-select:none}
.ann-tick input{width:16px;height:16px;accent-color:var(--brand);margin:0}
.ann-tick.on{border-color:var(--brand);background:var(--brand-soft)}
.ann-sentence{font-size:14.5px}
.ann-count{font-size:26px;font-weight:750;color:var(--brand);line-height:1.15}
.ann-chan{display:flex;gap:10px;align-items:flex-start}
.ann-chan .ic{font-size:20px;width:26px;text-align:center}
.ann-msg{white-space:normal;background:var(--surface-2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:6px}
.ann-phone{border:7px solid #1f2430;border-radius:24px;overflow:hidden;background:#efeae2;max-width:360px;width:100%;margin:0 auto;color:#111}
.ann-phone .ph-head{background:#075e54;color:#fff;display:flex;gap:10px;align-items:center;padding:9px 12px}
.ann-phone.tg .ph-head{background:#2f6ea5}
.ann-phone .av{width:32px;height:32px;border-radius:50%;background:#cfe9dd;color:#075e54;display:flex;align-items:center;justify-content:center;font-weight:700}
.ann-phone .ph-body{padding:10px 9px 14px;min-height:300px}
.ann-day{text-align:center;margin:4px 0 9px}
.ann-day span{background:#fff;border-radius:7px;padding:2px 9px;font-size:12px;color:#555}
.ann-bub{background:#fff;border-radius:0 9px 9px 9px;padding:7px 9px 17px;max-width:90%;position:relative;font-size:14px;line-height:1.42;box-shadow:0 1px 1px rgba(0,0,0,.08);margin-bottom:5px;overflow-wrap:anywhere}
.ann-bub.tpl{background:#fffbe8}
.ann-bub .tm{position:absolute;right:8px;bottom:2px;font-size:10.5px;color:#888}
.ann-btn{background:#fff;max-width:90%;border-radius:9px;text-align:center;color:#1a8cd8;padding:7px;font-size:14px;margin-bottom:6px;box-shadow:0 1px 1px rgba(0,0,0,.08)}
.ann-doc{display:flex;gap:9px;align-items:center;background:#f1f1f1;border-radius:7px;padding:7px;margin:4px 0;color:#111}
.ann-doc .pdf{background:#e2453c;color:#fff;font-size:10px;font-weight:700;border-radius:4px;padding:5px 4px}
.ann-mail{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--surface)}
.ann-mail .mh{background:var(--surface-2);padding:9px 12px;font-size:13px;border-bottom:1px solid var(--line)}
.ann-mail .mb{padding:12px;font-size:14px}
.fl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}
.fl-card{border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:12px}
.fl-card h4{margin:0 0 8px;font-size:16px;display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.fl-who{display:flex;justify-content:space-between;gap:8px;align-items:center;border-radius:8px;padding:6px 8px;margin:4px 0;background:var(--surface-2);cursor:pointer;border:1px solid transparent}
.fl-who:hover{border-color:var(--brand)}
.fl-tags{display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end}
.imp-person{border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:grid;gap:6px;background:var(--surface)}
.imp-person.off{opacity:.6}
.imp-change{display:grid;grid-template-columns:22px 150px minmax(0,1fr);gap:8px;align-items:start;font-size:13px}
.imp-change .old{color:var(--muted);text-decoration:line-through}
.imp-change .warn{color:var(--t-warn);font-size:12.5px}
@media (max-width:700px){.imp-change{grid-template-columns:22px minmax(0,1fr)}.imp-change>:nth-child(3){grid-column:2}}
"""
