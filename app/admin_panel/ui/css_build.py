"""Styles for the Flows editor (classes start with bd-, fx- and bt-)."""

CSS = r"""
.bd-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.bd-card{display:flex;flex-direction:column;gap:6px;padding:14px;color:var(--ink);text-decoration:none}
.bd-card:hover{border-color:var(--brand)}
.bd-card .row{display:flex;gap:8px;align-items:center;justify-content:space-between;margin-top:auto}
.bd-card-off{opacity:.75}
.bd-h3{margin:12px 0 0;font-size:16px}
.bd{display:flex;flex-direction:column;gap:12px;padding:12px 16px 24px}
.bd-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.bd-name{font-size:20px;font-weight:700;border:1px solid transparent;background:transparent;border-radius:8px;padding:4px 8px;flex:1;min-width:200px;color:var(--ink)}
.bd-name:hover,.bd-name:focus{border-color:var(--line);background:var(--surface);outline:none}
.bd-sp{flex:1}
.bd-tools{display:flex;gap:6px;align-items:center;flex:none}
.bd-spine{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin-top:8px}
.bd-sp-i{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:7px 10px;text-align:left;min-width:0;color:var(--ink);cursor:pointer}
.bd-sp-i b{display:flex;gap:6px;align-items:center;font-size:13px}
.bd-sp-i > span{display:block;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bd-sp-i .d{width:18px;height:18px;border-radius:50%;display:grid;place-items:center;font-size:11px;background:var(--sunken);color:var(--muted);flex:none}
.bd-sp-i.ok .d{background:var(--ok);color:var(--on-ok)}
.bd-sp-i.bad{border-color:var(--bad)} .bd-sp-i.bad .d{background:var(--bad);color:var(--on-bad)}
.bd-sp-i.todo .d{background:var(--warn);color:var(--surface)}
.bd-banner{border-radius:var(--r);padding:9px 14px;margin-top:8px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.bd-banner.draft{background:var(--warn-soft)} .bd-banner.live{background:var(--ok-soft)}
.bd-grid{display:grid;grid-template-columns:minmax(0,400px) minmax(0,1fr);gap:16px;align-items:start}
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
.bd-tabs{display:flex;gap:4px;align-items:center;flex-wrap:wrap;background:var(--sunken);border-radius:10px;padding:3px}
.bd-tabs > button{border:0;background:transparent;padding:6px 12px;border-radius:8px;color:var(--muted);font-weight:600;cursor:pointer}
.bd-tabs > button.on{background:var(--surface);color:var(--ink);box-shadow:var(--sh1)}
.bd-tabs label{margin-right:8px}
/* the Card */
.bd-sec{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);margin-bottom:12px}
.bd-sec-h{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line)}
.bd-sec-h .num{width:24px;height:24px;border-radius:50%;background:var(--brand);color:var(--on-brand);display:grid;place-items:center;font-size:12px;font-weight:700;flex:none}
.bd-sec-h .hint{color:var(--muted);font-size:12px;margin-left:auto}
.bd-sec-b{padding:12px 14px}
.bd-sub{margin-bottom:12px}
.bd-sub > b{display:inline-block;margin-bottom:6px}
.bd-sentence{display:flex;flex-wrap:wrap;align-items:center;gap:6px;line-height:2}
.bd-row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:4px 0}
.bd-days{display:inline-flex;gap:6px;flex-wrap:wrap}
.bd-q-row{display:flex;gap:8px;align-items:flex-start;padding:8px 10px;border:1px solid var(--line);border-radius:10px;margin-bottom:8px;background:var(--bg)}
.bd-q-row .grow{flex:1;min-width:0}
.bd-lab{font-weight:700;width:130px}
.bd-lst{display:flex;flex-direction:column;gap:8px}
.bd-step{border:1px solid var(--line);border-radius:12px;background:var(--bg);padding:8px 10px}
.bd-step.bad{border-color:var(--bad)}
.bd-step.bd-if{background:var(--surface)}
.bd-step-h{display:flex;gap:8px;align-items:flex-start}
.bd-step-h .ic{font-size:18px;line-height:2}
.bd-step-h .grow{flex:1;min-width:0}
.bd-tools > button{border:0;background:transparent;color:var(--muted);border-radius:6px;padding:2px 6px;cursor:pointer}
.bd-tools > button:hover{background:var(--sunken);color:var(--ink)}
.bd-tools > button.del:hover{color:var(--bad)}
.bd-tools > button:disabled{opacity:.35;cursor:default}
.bd-msgtxt{width:100%;min-height:52px;resize:vertical;border:1px solid var(--line);border-radius:8px;padding:6px 9px;background:var(--surface);color:var(--ink);font:inherit;margin-top:4px}
.bd-ins{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;align-items:center}
.bd-ins button,.bd-pill{font-size:12px;background:var(--brand-soft);color:var(--brand);border:0;border-radius:99px;padding:1px 9px;cursor:pointer}
.bd-map{display:flex;flex-direction:column;gap:2px;margin-top:4px}
.bd-col{font-weight:600;min-width:90px}
.bd-pickval{max-width:120px}
.bd-contract{display:flex;flex-wrap:wrap;gap:4px 8px;font-size:12px;margin-top:6px;align-items:center}
.bd-contract .k{color:var(--muted);font-weight:600}
.bd-contract .need,.bd-contract .give{border-radius:99px;padding:0 8px;font-weight:600}
.bd-contract .need.ok{background:var(--ok-soft);color:var(--t-ok)}
.bd-contract .need.bad{background:var(--bad-soft);color:var(--t-bad)}
.bd-contract .give{background:var(--brand-soft);color:var(--brand)}
.bd-prob{background:var(--bad-soft);border-radius:10px;padding:8px 10px;margin-top:8px;font-size:13px}
.bd-tech{font:12px/1.4 ui-monospace,Consolas,monospace;color:var(--muted);background:var(--sunken);border-radius:6px;padding:4px 8px;margin-top:6px;white-space:pre-wrap;word-break:break-all}
.bd-lanes{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;margin-top:8px}
.bd-lanes.one{grid-template-columns:minmax(0,1fr)}
.bd-lane{border-radius:10px;padding:8px;background:var(--sunken)}
.bd-lane .lh{font-size:13px;font-weight:700;margin-bottom:6px}
.bd-lane.yes .lh{color:var(--t-ok)} .bd-lane.no .lh{color:var(--t-warn)}
.bd-add{border:1px solid var(--line);background:transparent;border-radius:10px;padding:6px;color:var(--muted);font-size:13px;cursor:pointer;width:100%}
.bd-add:hover{border-color:var(--brand);color:var(--brand)}
.bd-flash{outline:3px solid var(--brand);outline-offset:2px}
.bd-ver{display:flex;gap:10px;align-items:center;padding:8px 10px;border:1px solid var(--line);border-radius:10px}
.bd-ver .grow{flex:1}
.bd-aibox{border:1px solid var(--brand-line);border-radius:12px;padding:10px 12px;background:var(--brand-soft)}
.bd-grp{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-top:6px}
.bd-acts{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:6px 0}
.bd-acts button{text-align:left;border:1px solid var(--line);background:var(--bg);border-radius:10px;padding:8px 9px;cursor:pointer;color:var(--ink)}
.bd-acts button:hover{border-color:var(--brand)}
.bd-acts small{display:block;color:var(--muted)}
/* colour per kind of step (always with its word), step numbers, "only when" bands, building blocks, hover info */
.bd-legend{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 8px;font-size:12px}
.bd-legend span{display:inline-flex;gap:5px;align-items:center;border:1px solid var(--line);border-radius:99px;padding:1px 9px 1px 4px;background:var(--surface)}
.bd-legend i{width:11px;height:11px;border-radius:50%;background:var(--c)}
.bd-step{position:relative;border-left:5px solid var(--c,var(--line));background:color-mix(in srgb,var(--c,transparent) 5%,var(--bg))}
.bd-cat{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;color:#fff;background:var(--c);border-radius:6px;padding:0 7px;line-height:18px}
.bd-num{position:absolute;left:-30px;top:8px;width:22px;height:22px;border-radius:50%;background:var(--ink);color:var(--bg);font-size:11px;font-weight:700;display:grid;place-items:center}
.bd-lst:has(> .bd-step > .bd-num){padding-left:26px}
.bd-band{margin:-8px -10px 6px -10px;padding:3px 10px;border-radius:0 11px 0 0;font-size:12px;font-weight:600;background:var(--warn-soft);color:var(--t-warn)}
.bd-band.never{background:var(--bad-soft);color:var(--t-bad)}
.bd-prob.warn{background:var(--warn-soft)}
.bd-given{font-size:12.5px;margin-top:4px;border:1px dashed var(--line);border-radius:8px;padding:3px 8px;background:var(--surface)}
.bd-toggle{border:0;background:none;color:#0d9488;font-weight:600;font-size:12.5px;padding:2px 0;cursor:pointer}
.bd-inside{margin:4px 0;padding-left:22px;font-size:13px}
.bd-inside li{margin:3px 0;padding-left:6px;border-left:3px solid var(--c)}
.bd-only{color:var(--t-warn);font-weight:600}
.bd-tip{visibility:hidden;opacity:0;position:absolute;left:-1px;top:100%;margin-top:4px;z-index:30;width:min(420px,90vw);background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--sh2,0 10px 30px rgba(0,0,0,.2));padding:8px 12px;font-size:13px;transition:opacity .1s,visibility 0s .1s;pointer-events:none}
.bd-step:hover:not(:has(.bd-step:hover)) > .bd-tip{visibility:visible;opacity:1;transition:opacity .15s .5s,visibility 0s .5s}
.bd-tip table{border-collapse:collapse;width:100%}
.bd-tip td{padding:2px 0;vertical-align:top}
.bd-tip td:first-child{color:var(--muted);font-weight:600;width:96px}
.bd-x-warn{color:var(--t-warn);font-weight:600}
.bd-explain ol{margin:4px 0;padding-left:22px}.bd-explain li{margin:3px 0}.bd-explain ul{list-style:none;padding-left:8px;margin:2px 0}
/* the flow as one chart, with the editor of the clicked box beside it */
.bd-grid.nochat{grid-template-columns:minmax(0,1fr)}
.bd-chat[hidden]{display:none}
.bd-tabs > button.on{background:var(--surface);color:var(--ink);box-shadow:var(--sh1)}
.fx-wrap{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;align-items:start}
.fx-wrap.with-ed{grid-template-columns:minmax(0,1fr) minmax(320px,400px)}
.fx{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:14px 12px 30px;overflow:auto;min-width:0}
.fx-flow{display:flex;flex-direction:column;align-items:center;min-width:max-content;margin:0 auto;padding-left:30px}
.fx-card{position:relative;width:360px;background:color-mix(in srgb,var(--c) 6%,var(--bg));border:1px solid var(--line);border-left:6px solid var(--c);border-radius:12px;padding:8px 12px 10px;cursor:pointer;text-align:left;color:var(--ink)}
.fx-lane .fx-card,.fx-only .fx-card,.fx-group .fx-card{width:310px}
.fx-card:hover{box-shadow:0 3px 12px rgba(0,0,0,.14);z-index:6}
.fx-card.sel{outline:3px solid var(--brand);outline-offset:1px}
.fx-card.bad{outline:2px solid var(--bad)}
.fx-card.sel.bad{outline-color:var(--brand)}
.fx-glow{outline:3px solid #34d399 !important;box-shadow:0 0 0 6px rgba(52,211,153,.25)}
.fx-num{position:absolute;left:-32px;top:8px;width:22px;height:22px;border-radius:50%;background:var(--ink);color:var(--bg);font-size:11px;font-weight:700;display:grid;place-items:center}
.fx-head{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.fx-kind{font-size:12px;color:var(--muted)}
.fx-words{margin-top:4px;font-weight:600;overflow-wrap:anywhere}
.fx-words.empty{color:var(--muted);font-style:italic;font-weight:400}
.fx-about{color:var(--muted);font-size:12.5px;margin-top:2px}
.fx-band{margin:-8px -12px 7px -12px;padding:3px 12px;border-radius:0 11px 0 0;font-size:12px;font-weight:600;background:var(--warn-soft);color:var(--t-warn)}
.fx-band.never{background:var(--bad-soft);color:var(--t-bad)}
.fx-chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.fx-chip{font-size:11.5px;border-radius:99px;padding:0 8px;border:1px solid var(--line);background:var(--surface)}
.fx-chip.need{color:var(--brand);cursor:help}.fx-chip.bad{color:var(--t-bad);background:var(--bad-soft);cursor:help}.fx-chip.give{color:var(--t-ok);background:var(--ok-soft)}
.fx-warn{margin-top:6px;color:var(--t-bad);font-size:12.5px}
.fx-conn{height:34px;width:2px;background:var(--line);position:relative;display:flex;align-items:center;justify-content:center;flex:none}
.fx-conn.short{height:14px}
.fx-plus{position:absolute;width:24px;height:24px;border-radius:50%;border:1px solid var(--line);background:var(--surface);color:var(--brand);font-weight:700;line-height:20px;padding:0;cursor:pointer}
.fx-plus:hover{background:var(--brand);color:var(--on-brand);border-color:var(--brand)}
.fx-split{display:flex;gap:16px;align-items:stretch}
.fx-lane{display:flex;flex-direction:column;align-items:center;border:1.5px dashed var(--line);border-radius:14px;padding:8px 10px 10px;min-width:330px}
.fx-lane .lh{font-weight:700;font-size:12.5px}
.fx-lane.yes .lh{color:var(--t-ok)}.fx-lane.no .lh{color:var(--t-warn)}
.fx-end{color:var(--muted);font-size:12px;margin-top:4px}
.fx-only{position:relative;display:flex;flex-direction:column;align-items:center;border:2px solid color-mix(in srgb,#ea580c 45%,var(--line));border-radius:14px;padding:0 12px 10px;background:color-mix(in srgb,#ea580c 4%,transparent)}
.fx-only.sel{outline:3px solid var(--brand)}
.fx-only-h{position:relative;align-self:stretch;margin:0 -12px 2px;border:0;border-radius:12px 12px 0 0;background:var(--warn-soft);color:var(--t-warn);font-weight:700;font-size:12.5px;padding:5px 12px;text-align:left;cursor:pointer}
.fx-only-h .fx-num{left:-44px;top:3px}
.fx-group{display:flex;flex-direction:column;align-items:center;border:1px dashed var(--line);border-radius:14px;padding:6px 12px 10px}
.fx-gh{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px}
.fx-block{display:flex;flex-direction:column;align-items:center;border:2px solid color-mix(in srgb,#0d9488 45%,var(--line));border-radius:16px;padding:6px}
.fx-block .bd-inside{align-self:stretch;margin:6px 10px 2px 22px}
.fx-done{margin-top:6px;color:var(--muted);font-size:12px;border-radius:99px;background:var(--sunken);padding:3px 12px}
.fx-tip{visibility:hidden;opacity:0;position:absolute;left:-1px;top:100%;padding-top:5px;z-index:40;cursor:default;transition:opacity .1s,visibility 0s .1s}
.fx-card:hover > .fx-tip{visibility:visible;opacity:1;transition:opacity .15s .45s,visibility 0s .45s}
.fx-tipbox{width:min(420px,80vw);background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.25);padding:8px 12px;font-size:13px;font-weight:400}
.fx-tipbox table{border-collapse:collapse;width:100%}.fx-tipbox td{padding:2px 0;vertical-align:top}.fx-tipbox td:first-child{color:var(--muted);font-weight:600;width:96px}
.fx-ed{position:sticky;top:calc(var(--top-h) + 12px);max-height:calc(100vh - var(--top-h) - 30px);overflow:auto;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:12px 14px;display:flex;flex-direction:column;gap:8px}
.fx-ed-h{display:flex;align-items:center;gap:8px}.fx-ed-h .grow{flex:1}
.fx-ed .bd-cat{background:var(--c)}
.fx-ed-b{display:flex;flex-direction:column;gap:4px}
.fx-run{border:1px solid color-mix(in srgb,#ea580c 40%,var(--line));background:color-mix(in srgb,#ea580c 5%,var(--surface));border-radius:10px;padding:8px 10px;font-size:13px}
.bd-flab{font-weight:600;font-size:13px;margin-top:4px}
.btn.danger{color:var(--t-bad)}
/* Try it */
.bt{background:var(--surface);border:1px solid var(--line);border-radius:16px;overflow:hidden;display:flex;flex-direction:column;height:560px}
.bt-h{background:#075E54;color:#fff;padding:8px 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.bt-h select{max-width:220px;background:#ffffff26;border:0;color:#fff;border-radius:8px;padding:3px 6px;font-weight:600}
.bt-h select option{color:#000}
.bt-h button{background:#ffffff26;border:0;color:#fff;border-radius:8px;padding:3px 9px;font-size:12.5px;cursor:pointer}
.bt-msgs{flex:1;overflow:auto;background:color-mix(in srgb,#075E54 8%,var(--bg));padding:12px;display:flex;flex-direction:column;gap:7px}
.bt-b{max-width:86%;padding:7px 10px;border-radius:10px;white-space:pre-wrap;font-size:14px}
.bt-b.bot{background:var(--surface);align-self:flex-start;box-shadow:var(--sh1)}
.bt-b.me{background:color-mix(in srgb,#25D366 22%,var(--surface));align-self:flex-end}
.bt-b.sys{align-self:center;background:var(--brand-soft);font-size:12.5px;max-width:96%}
.bt-b.other{align-self:flex-start;background:var(--warn-soft);font-size:13px}
.bt-btns{display:flex;flex-wrap:wrap;gap:6px;align-self:flex-start}
.bt-btns button{background:var(--surface);border:1px solid var(--line);color:var(--brand);border-radius:99px;padding:5px 12px;font-size:13px;cursor:pointer}
.bt-in{display:flex;gap:8px;padding:8px;border-top:1px solid var(--line)}
.bt-in input{flex:1;min-width:0;border:1px solid var(--line);border-radius:99px;padding:7px 12px;background:var(--bg);color:var(--ink)}
.bt-in button{border:0;background:#075E54;color:#fff;border-radius:99px;width:40px;cursor:pointer}
@media (max-width:1000px){.bd-spine{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:1250px){.fx-wrap.with-ed{grid-template-columns:minmax(0,1fr)}.fx-ed{position:static;max-height:none}}
@media (max-width:900px){.bd-grid{grid-template-columns:minmax(0,1fr)}.bd-chat{position:static;height:480px}.bd-lanes{grid-template-columns:minmax(0,1fr)}.bd-acts{grid-template-columns:1fr}.bd-spine{grid-template-columns:repeat(2,minmax(0,1fr))}.bd-q-row{flex-wrap:wrap}.bd-lab{width:100%}}
"""
