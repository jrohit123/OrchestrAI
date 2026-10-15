"""Styles for the calmer dashboard: the two-group menu, the screens that were reshaped (Home, Cases,
People, Roles & access, Flows) and the explanations that come with them. New class names only, so
nothing here can change how an older screen looks."""

CSS = r"""
/* ───── the menu and the page frame ───── */
.nav .navdot{width:8px;height:8px;border-radius:50%;background:var(--bad);margin-left:auto;flex:none;display:inline-block}
.nav .navdot[hidden],.nav .ct[hidden]{display:none}
body.rail .nav .navdot{display:none}
.words{padding:6px 8px}
.words dl{margin:10px 0 0;display:grid;gap:10px}
.words dt{font-weight:700}
.words dd{margin:0;color:var(--muted);font-size:13px}
"""
CSS += r"""
/* ───── Roles & access ───── */
.rl-grid{display:grid;grid-template-columns:290px minmax(0,1fr);gap:16px;align-items:start}
.rl .rl-row{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line);color:var(--ink);cursor:pointer;text-decoration:none}
.rl .rl-row:last-child{border-bottom:0}
.rl .rl-row:hover{background:var(--sunken);text-decoration:none}
.rl .rl-row.on{background:var(--brand-soft);box-shadow:inset 3px 0 0 var(--brand)}
.rl .rl-row .ico{color:var(--faint)}
.rl .rl-row .n{min-width:16px;text-align:right}
.rl-perm{display:grid;grid-template-columns:44px minmax(0,1fr);gap:10px;align-items:center;padding:11px 16px;border-bottom:1px solid var(--line)}
.rl-perm:last-child{border-bottom:0}
.rl-desc{display:block}
.rl-save{display:flex;align-items:center;gap:10px;padding:12px 16px;flex-wrap:wrap}
.rl-why{max-width:340px}
@media (max-width:1000px){.rl-grid{grid-template-columns:minmax(0,1fr)}}
"""
CSS += r"""
/* ───── Home ───── */
.nr{display:grid;grid-template-columns:42px minmax(0,1fr) auto;gap:14px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line)}
.nr:last-child{border-bottom:0}
.nr-i{--tc:var(--info);width:42px;height:42px;border-radius:12px;display:grid;place-items:center;background:color-mix(in srgb,var(--tc) 12%,var(--surface));color:var(--tc)}
.nr-i.warn{--tc:var(--warn)}.nr-i.bad{--tc:var(--bad)}.nr-i.ok{--tc:var(--ok)}
.nr-t b{display:block;font-size:15px}
.nr-more{padding:8px 12px;border-top:1px solid var(--line)}
.nr-more .extra{display:none;padding:4px 4px 8px;color:var(--ink-2);font-size:13.5px;gap:6px}
.nr-more.open .extra{display:grid}
.okline{display:flex;align-items:center;gap:12px;padding:16px}
.okline .d{width:12px;height:12px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 4px color-mix(in srgb,var(--ok) 20%,transparent);flex:none}
.okline .d.warn{background:var(--warn);box-shadow:0 0 0 4px color-mix(in srgb,var(--warn) 20%,transparent)}
.okline .d.bad{background:var(--bad);box-shadow:0 0 0 4px color-mix(in srgb,var(--bad) 20%,transparent)}
.setchip{cursor:pointer;border:0;font:inherit;font-weight:650;font-size:12.5px;padding:3px 12px}
@media (max-width:700px){.nr{grid-template-columns:42px minmax(0,1fr)}.nr .btn{grid-column:1/-1;justify-self:start}}
"""
CSS += r"""
/* ───── Cases ───── */
.pd{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:var(--faint)}
.pd.bad{background:var(--bad)}.pd.warn{background:var(--warn)}.pd.info{background:var(--info)}
.cs b{letter-spacing:.01em}
"""
CSS += r"""
/* ───── People ───── */
button.chip{cursor:pointer;font:inherit;font-size:12.5px}
.chip.on{background:var(--brand-soft);border-color:var(--brand-line);color:var(--brand);font-weight:650}
"""
CSS += r"""
/* ───── Flows ───── */
.hw{margin-bottom:16px}
.hw-h{display:flex;align-items:center;gap:10px;padding:10px 16px;border-bottom:1px solid var(--line);font-weight:650}
.hw-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}
.hw-st{display:grid;grid-template-columns:38px minmax(0,1fr);gap:12px;padding:16px;border-right:1px solid var(--line);position:relative}
.hw-st:last-child{border-right:0}
.hw-st:not(:last-child)::after{content:"→";position:absolute;right:-9px;top:50%;transform:translateY(-50%);background:var(--surface);color:var(--faint);width:18px;text-align:center;z-index:1}
.hw-st .gi{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;background:color-mix(in srgb,var(--kc) 13%,var(--surface));color:var(--kc)}
.hw-st .t{display:block}
.hw-st .s{color:var(--muted);font-size:13px}
@media (max-width:1000px){.hw-steps{grid-template-columns:minmax(0,1fr)}.hw-st{border-right:0;border-bottom:1px solid var(--line)}.hw-st::after{display:none}}
.nf-start{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.nf-card{display:grid;gap:6px;text-align:left;padding:16px;border:1px solid var(--line-2);background:var(--surface);border-radius:12px;color:inherit}
.nf-card:hover{border-color:var(--brand)}
.nf-card.on{border-color:var(--brand);background:var(--brand-soft)}
.nf-card .gi{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;background:var(--brand-soft);color:var(--brand)}
.nf-card.on .gi{background:var(--surface)}
.nf-card .t{font-size:14.5px}
.nf-card .s{color:var(--muted);font-size:12.5px}
@media (max-width:700px){.nf-start{grid-template-columns:minmax(0,1fr)}}
/* ───── the flow editor: a step's ⋯ and the first-time hint ───── */
.nd.nc .nd-more{position:absolute;top:-9px;right:-7px;width:20px;height:20px;border-radius:50%;background:var(--surface);border:1px solid var(--line-2);display:grid;place-items:center;color:var(--muted);padding:0;cursor:pointer;z-index:5;box-shadow:var(--sh1)}
.nd.nc .nd-more:hover,.nd.nc .nd-more:focus-visible{color:var(--brand);border-color:var(--brand)}
.cvhint{display:flex;align-items:center;gap:12px;margin:10px 14px 0;background:var(--surface);border:1px solid var(--brand-line);color:var(--ink-2);border-radius:12px;padding:8px 8px 8px 12px;box-shadow:var(--sh1);font-size:13px}
.cvhint .ico{color:var(--brand);flex:none}
.cvhint .btn{margin-left:auto;flex:none}
"""
CSS += r"""
.seg button[hidden]{display:none}
.nf-start{margin-top:10px}
"""
CSS += r"""
/* ───── Chat bot: AI notes ───── */
.promptbox.an-short{min-height:190px;font-family:inherit;font-size:14px;line-height:1.55}
.promptbox.an-mid{min-height:300px}
.an-notes:empty{display:none}
.an-ideas{margin:6px 0 0;padding-left:20px;color:var(--muted);font-size:13px;display:grid;gap:3px}
.an-adv{margin-top:6px}
.an-adv>summary{cursor:pointer;font-weight:600;color:var(--ink-2);padding:12px 2px}
.an-advnote{margin:0 0 12px 2px}
.wh-t{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--surface)}
.wh-hd,.wh-r{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr) minmax(0,1.3fr) minmax(0,.9fr);gap:10px;align-items:center;padding:10px 14px}
.wh-hd{font-size:12px;color:var(--muted);background:var(--surface-2);border-bottom:1px solid var(--line)}
.wh-r{border-bottom:1px solid var(--line);cursor:pointer;font-size:13.5px}
.wh-r:hover{background:var(--surface-2)}.wh-r.on{background:var(--brand-soft)}
.wh-r:focus-visible{outline:2px solid var(--brand);outline-offset:-2px}
.wh-name{display:flex;flex-direction:column;gap:2px;min-width:0}
.wh-kids{border:0;background:transparent;padding:0;font-size:11.5px;color:var(--brand);text-align:left;cursor:pointer;width:max-content}
.wh-same{grid-column:2 / span 3;color:var(--muted);font-style:italic}
.wh-own{font-weight:600;min-width:0}
.wh-ed{padding:14px 16px 16px;border-bottom:1px solid var(--line);background:var(--surface-2);display:flex;flex-direction:column;gap:8px}
.wh-sent{padding:9px 12px;background:var(--sunken);border-radius:8px;line-height:1.55;font-size:13.5px}
.wh-pr{display:flex;align-items:center;gap:8px;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}
.wh-pnm{flex:1;min-width:0}
.wh-note{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:8px 12px;border-radius:8px;background:var(--brand-soft);color:var(--ink-2);font-size:13px}
.wh-note.warm{background:var(--warn-soft)}
.wh-save{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 12px;border:1px solid var(--warn);border-radius:8px;background:var(--warn-soft);font-size:13px}
.wh-try{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.wh-sep{border-top:1px solid var(--line-2)}
@media (max-width:760px){.wh-hd,.wh-r{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.wh-hd div:nth-child(n+3){display:none}.wh-r>div:nth-child(n+3){display:none}.wh-same{grid-column:2}}
/* ───── WhatsApp form editor and phone preview ───── */
.wf-wrap{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:24px;align-items:start}
.wf-side{position:sticky;top:76px}
.wf-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.wf-field{border:1px solid var(--line);border-radius:10px;padding:12px;display:grid;gap:10px;background:var(--surface-2)}
.wf-field.off{opacity:.65}
.wf-status{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.wf-phone{position:relative;width:320px;height:620px;border-radius:30px;border:8px solid #1c1f26;background:#e5ddd5;overflow:hidden;display:flex;flex-direction:column;font:14px/1.4 -apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#111}
.wf-top{background:#075e54;color:#fff;padding:12px 14px;display:flex;gap:8px;align-items:baseline}.wf-top span{opacity:.75;font-size:12px}
.wf-chat{padding:14px;flex:1}
.wf-bubble{background:#fff;border-radius:0 10px 10px 10px;padding:10px 12px;max-width:85%;box-shadow:0 1px 1px rgba(0,0,0,.12);white-space:pre-wrap}
.wf-open{margin:10px -12px -10px;padding:10px;border-top:1px solid #e6e6e6;text-align:center;color:#027eb5;font-weight:600;cursor:pointer}
.wf-sheet{position:absolute;left:0;right:0;bottom:0;top:70px;background:#fff;border-radius:16px 16px 0 0;display:flex;flex-direction:column;box-shadow:0 -4px 16px rgba(0,0,0,.25)}
.wf-bar{display:flex;gap:12px;align-items:center;padding:12px 14px;border-bottom:1px solid #eee}.wf-bar .x{cursor:pointer;color:#555}
.wf-body{padding:12px 14px;overflow:auto;flex:1;display:grid;gap:12px;align-content:start}
.wf-l{font-size:13px;font-weight:600;margin-bottom:4px}
.wf-in{border:1px solid #cfd3d8;border-radius:8px;padding:9px 10px;min-height:38px;color:#777;display:flex;justify-content:space-between}
.wf-in.tall{min-height:70px}
.wf-h{font-size:12px;color:#777;margin-top:3px}
.wf-radios{display:grid;gap:8px}.wf-radio{display:flex;gap:10px;align-items:center}
.wf-radio .dot{width:16px;height:16px;border-radius:50%;border:2px solid #9aa0a6;display:inline-block}.wf-radio .dot.on{border-color:#128c7e;background:radial-gradient(#128c7e 45%,transparent 50%)}
.wf-photo{border:1px dashed #9aa0a6;border-radius:8px;padding:12px;display:grid;gap:2px;color:#128c7e}.wf-photo span{color:#777;font-size:12px}
.wf-foot{padding:10px 14px;border-top:1px solid #eee}
.wf-go{background:#128c7e;color:#fff;text-align:center;border-radius:20px;padding:10px;font-weight:600}
@media (max-width:1100px){.wf-wrap{grid-template-columns:minmax(0,1fr)}.wf-side{position:static}.wf-phone{margin:0 auto}}
.wf-edit{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:20px;align-items:start}
.wf-codewrap{display:flex;border-top:1px solid var(--line);background:var(--surface-2)}
.wf-gut{margin:0;padding:12px 8px;text-align:right;color:var(--faint);font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;overflow:hidden;height:560px;min-width:38px;user-select:none}
.wf-code{flex:1;min-width:0;height:560px;border:0;outline:0;resize:vertical;padding:12px;background:transparent;color:var(--ink);font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;white-space:pre;overflow:auto;tab-size:2}
.wf-code.small{height:auto;border:1px solid var(--line);border-radius:8px;width:100%}
.wf-errs{border-top:1px solid var(--line);padding:10px 14px;max-height:160px;overflow:auto}
.wf-eh{font-weight:650;margin-bottom:4px}.wf-e{color:var(--bad);font-size:12.5px;font-family:ui-monospace,Menlo,Consolas,monospace;padding:2px 0}
.wf-menu{display:grid;gap:2px;padding:4px}.wf-menu .btn{justify-content:flex-start;text-align:left}
.wf-result{margin-top:10px;font-size:12.5px}.wf-result pre{background:var(--sunken);padding:8px;border-radius:8px;overflow:auto;margin:6px 0 0}
.wf-empty{padding:30px 16px;text-align:center;color:#666;flex:1;background:#fff}
.wf-th{font-size:20px;font-weight:700}.wf-ts{font-size:16px;font-weight:650}.wf-tb{font-size:14px;color:#333}.wf-tc{font-size:12px;color:#777}
.wf-radio .dot.sq{border-radius:4px}
.wf-link{color:#027eb5;text-decoration:underline}.wf-unk{font-size:11px;color:#999;border:1px dashed #ccc;border-radius:6px;padding:4px 8px}
.wf-img{background:#eee;border-radius:8px;padding:20px;text-align:center;color:#888}.wf-img img{max-width:100%}
.wf-item{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:10px 2px;border-bottom:1px solid #eee;cursor:pointer}
.wf-managed{text-align:center;font-size:11px;color:#888;padding:6px;background:#fff}
@media (max-width:1100px){.wf-edit{grid-template-columns:minmax(0,1fr)}}
.imp-t td,.imp-t th{vertical-align:top;padding:8px 10px}.imp-t tr.off{opacity:.55}.imp-t tr.needs td{background:var(--bg-warn,rgba(250,200,60,.14))}
.imp-t select{max-width:190px}
/* ───── a ticket's time to fix (the time bar) ───── */
.tat{display:grid;gap:4px;min-width:170px}
.tbar{position:relative;height:8px;border-radius:6px;background:var(--sunken)}
.tat.big .tbar{height:14px;margin:4px 0}
.tbar i{display:block;height:100%;border-radius:6px;background:var(--ok)}
.tbar.warn i{background:var(--warn)}.tbar.late i{background:var(--bad)}.tbar.paused i{background:var(--faint)}.tbar.done i{background:var(--line-2)}
.tbar.none{background:repeating-linear-gradient(90deg,var(--line-2) 0 8px,transparent 8px 14px)}.tbar.none i{display:none}
.tmark{position:absolute;top:50%;width:10px;height:10px;border-radius:50%;transform:translate(-50%,-50%);border:2px solid var(--ink-2);background:var(--surface)}
.tat.big .tmark{width:18px;height:18px}
.tmark.done{background:var(--ink-2)}
.ttxt{font-size:12.5px;color:var(--muted)}.ttxt.late{color:var(--bad);font-weight:600}.ttxt.warn{color:var(--t-warn)}
td.tatcol{min-width:190px}
.wh-t.tat5 .wh-hd,.wh-t.tat5 .wh-r{grid-template-columns:minmax(0,1.4fr) minmax(0,1fr) minmax(0,1.2fr) minmax(0,.9fr) minmax(130px,.8fr)}
.wh-t.tat5 .wh-same{grid-column:2 / span 3}
.wh-r select{max-width:150px;padding:3px 6px;font-size:12.5px}
/* ───── Home: the set-up card and the time-to-fix card ───── */
.setbar{height:8px;border-radius:9px;background:var(--sunken);overflow:hidden}.setbar i{display:block;height:100%;background:var(--brand)}
.setcard .check{align-items:center}
.tfrow{display:grid;gap:4px;padding:8px 0;border-bottom:1px solid var(--line);color:inherit;text-decoration:none}
.tfrow:last-child{border-bottom:0}.tfrow:hover b{color:var(--brand)}
/* ───── Tickets → Reminders ───── */
.remstep{border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:grid;gap:8px;background:var(--surface-2)}
.remstep.late{border-left:3px solid var(--bad)}
.remstep input[type=number]{width:76px}
.remchip{gap:4px}.remchip .x{border:0;background:none;color:var(--faint);font-size:14px;line-height:1;padding:0 0 0 2px;cursor:pointer}
.remurg{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:12px}
.remex{display:grid;grid-template-columns:220px minmax(0,1fr);gap:16px;align-items:center;padding:4px 48px 30px 0}
.remexbar{position:relative;height:10px;border-radius:6px;background:linear-gradient(90deg,var(--ok) 0 40%,var(--warn) 40% 100%);opacity:.75}
.remexbar.none{background:repeating-linear-gradient(90deg,var(--line-2) 0 8px,transparent 8px 14px);height:24px;display:flex;align-items:center;opacity:1}
.remexbar.none span{background:var(--surface);padding:0 6px;font-size:12.5px;color:var(--muted)}
.remexstep{position:absolute;top:50%;transform:translate(-50%,-50%)}
.remexdot{display:block;width:14px;height:14px;border-radius:50%;background:var(--surface);border:2px solid var(--ink-2)}
.remexdot.late{border-color:var(--bad)}
.remexlab{position:absolute;top:16px;left:50%;transform:translateX(-50%);white-space:nowrap;font-size:11.5px;color:var(--ink-2);text-align:center;line-height:1.3}
@media (max-width:760px){.remex{grid-template-columns:1fr;padding-right:20px}}
/* ───── a ticket's clock (its page) ───── */
.clk{display:flex;gap:10px;align-items:flex-start;padding:8px 10px;border:1px solid var(--line);border-radius:9px;background:var(--surface)}
.clk.next{border-color:var(--brand);background:var(--brand-soft)}.clk.later{opacity:.7}.clk.failed{border-color:var(--bad)}
.clk-i{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-size:12px;flex:none;background:var(--sunken)}
.clk.done .clk-i{background:var(--ok);color:var(--on-ok)}.clk.next .clk-i{background:var(--brand);color:var(--on-brand)}
.wfb{padding:14px;display:grid;gap:12px}.wfb[hidden]{display:none}
.wfb-q{border:1px solid var(--line);border-radius:10px;padding:12px;display:grid;gap:10px;background:var(--surface-2)}
.wfb-lock{border-style:dashed;color:var(--muted);display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:13px}
.wfb-f{display:grid;gap:4px}.wfb-f input,.wfb-f textarea{width:100%}
.wfb-tools{gap:4px}.wfb-name{width:160px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.tpl-phone{height:auto;min-height:300px}
.tpl-h{font-weight:700;margin-bottom:4px}.tpl-f{font-size:12px;color:#777;margin-top:6px}.tpl-t{font-size:11px;color:#999;text-align:right;margin-top:4px}
.tpl-b{margin:8px -12px -10px;padding:9px;border-top:1px solid #e6e6e6;text-align:center;color:#027eb5;font-weight:600}.tpl-b+.tpl-b{margin-top:0;margin-bottom:-10px}
.wf-codewrap[hidden]{display:none}
/* ───── Chat bot > Menu: the tree editor and the chat preview ───── */
.cm-wrap{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:20px;align-items:start}
.cm-side{position:sticky;top:76px}
.cm-group{border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:12px;display:grid;gap:10px}
.cm-group.l2{background:var(--surface-2);border-radius:10px}
.cm-group.off,.cm-entry.off{opacity:.6}
.cm-ghead{display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap}
.cm-gname{display:grid;gap:6px;flex:1;min-width:220px}
.cm-kids{display:grid;gap:8px}
.cm-entry{display:flex;gap:10px;align-items:center;flex-wrap:wrap;border:1px solid var(--line);border-radius:9px;padding:8px 10px;background:var(--surface)}
.cm-entry input[type=text]{flex:1;min-width:140px}
.cm-name{flex:1.2;min-width:160px;display:grid;gap:2px}
.cm-shown{display:flex;gap:6px;align-items:center}
.cm-add{padding-top:2px}
.cm-save{position:sticky;bottom:0;display:none;gap:10px;align-items:center;padding:12px 16px;margin-top:16px;border:1px solid var(--line);border-radius:12px;background:var(--surface);box-shadow:0 -4px 16px rgba(0,0,0,.08)}
.cm-save.on{display:flex}
.cm-phone{background:#e5ddd5;border-radius:14px;padding:12px;display:grid;gap:10px;color:#111;font:14px/1.4 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.cm-bubble{background:#fff;border-radius:0 10px 10px 10px;padding:10px 12px;max-width:90%;box-shadow:0 1px 1px rgba(0,0,0,.12)}
.cm-open{margin:10px -12px -10px;padding:10px;border-top:1px solid #e6e6e6;text-align:center;color:#027eb5;font-weight:600}
.cm-sheet{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 -2px 8px rgba(0,0,0,.15)}
.cm-sheet-h{padding:10px 14px;border-bottom:1px solid #eee;font-weight:600}
.cm-row{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:10px 14px;border-bottom:1px solid #f1f1f1;cursor:pointer}
.cm-row:hover,.cm-row:focus{background:#f5f7f7;outline:0}.cm-row.back{color:#027eb5}
.cm-row .muted{color:#777}
@media (max-width:1100px){.cm-wrap{grid-template-columns:minmax(0,1fr)}.cm-side{position:static}}
/* ───── Flows, one box per use case ───── */
.ucb{margin-bottom:14px;overflow:hidden}.ucb.off{opacity:.65}
.ucb-h{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line)}
.ucb-ic{font-size:20px}
.ucb-row{display:flex;align-items:center;gap:10px;padding:8px 16px;border-top:1px solid var(--line)}
.ucb-row:first-of-type{border-top:0}.ucb-row.off a{color:var(--muted)}
.ucb-row select{width:auto;max-width:170px;font-size:12.5px}
.ucb-blocks>summary{padding:8px 16px;cursor:pointer;color:var(--muted);font-size:13px;border-top:1px solid var(--line)}
"""
