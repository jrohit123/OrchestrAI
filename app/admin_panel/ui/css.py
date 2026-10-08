"""The admin panel's stylesheet: one design system (tokens, shell, components), the screens, and
the flow canvas. Dark mode is the same tokens redefined, so it is written once and used twice."""

_LIGHT = r"""
  color-scheme:light;
  --bg:#f3f4f8; --surface:#ffffff; --surface-2:#f8f9fc; --sunken:#edeff5;
  --ink:#0f1320; --ink-2:#2f3647; --muted:#5b6578; --faint:#98a1b3;
  --line:#e3e6ee; --line-2:#cdd3df;
  --brand:#4338ca; --brand-soft:#eceeff; --brand-line:#c3c8ff; --on-brand:#ffffff;
  --ok:#15803d; --warn:#a15c07; --bad:#c0262d; --info:#1d4ed8;
  --on-ok:#ffffff; --on-bad:#ffffff;
  --t-muted:#525c70; --t-ok:#126c34; --t-warn:#8d5006; --t-bad:#b2232a; --t-violet:#7135d8; --t-teal:#096a62; --t-pink:#af1f5f; --t-orange:#a33d08;
  --k-trigger:#4f46e5; --k-look:#2563eb; --k-save:#059669; --k-tell:#ea580c; --k-approve:#db2777;
  --k-other:#64748b; --k-block:#0d9488; --k-ai:#7c3aed; --k-stop:#dc2626;
  --sh1:0 1px 2px rgba(15,19,32,.06);
  --sh2:0 10px 30px -10px rgba(15,19,32,.22),0 2px 8px rgba(15,19,32,.06);
"""

_DARK = r"""
  color-scheme:dark;
  --bg:#0c0f16; --surface:#141923; --surface-2:#10141d; --sunken:#1b2230;
  --ink:#e8ebf2; --ink-2:#c3c9d6; --muted:#97a1b3; --faint:#6b7587;
  --line:#242c3b; --line-2:#323c50;
  --brand:#9aa2ff; --brand-soft:#1d2140; --brand-line:#3a4190; --on-brand:#0c0f16;
  --ok:#4ade80; --warn:#fbbf24; --bad:#f87171; --info:#7cb0ff;
  --on-ok:#0c0f16; --on-bad:#0c0f16;
  --t-muted:#97a1b3; --t-ok:#4ade80; --t-warn:#fbbf24; --t-bad:#f87171; --t-violet:#a78bfa; --t-teal:#2dd4bf; --t-pink:#f472b6; --t-orange:#fb923c;
  --k-trigger:#8b93ff; --k-look:#6aa2ff; --k-save:#34d399; --k-tell:#fb923c; --k-approve:#f472b6;
  --k-other:#94a3b8; --k-block:#2dd4bf; --k-ai:#a78bfa; --k-stop:#f87171;
  --sh1:0 1px 2px rgba(0,0,0,.4);
  --sh2:0 12px 32px -10px rgba(0,0,0,.6),0 2px 8px rgba(0,0,0,.4);
"""

_TOKENS = (
    ":root{"
    + _LIGHT
    + """
  --r:12px; --top-h:56px; --nw:392px;
  /* the names the older screens still use */
  --panel:var(--surface); --line2:var(--line-2); --mute-soft:var(--sunken); --brand-ink:var(--on-brand);
  --ok-soft:color-mix(in srgb,var(--ok) 14%,var(--surface)); --warn-soft:color-mix(in srgb,var(--warn) 14%,var(--surface));
  --bad-soft:color-mix(in srgb,var(--bad) 12%,var(--surface)); --info-soft:color-mix(in srgb,var(--info) 12%,var(--surface));
  --violet:var(--k-ai); --violet-soft:color-mix(in srgb,var(--k-ai) 13%,var(--surface));
  --radius:var(--r); --shadow:var(--sh1);
}
:root[data-theme="dark"]{"""
    + _DARK
    + """}
@media (prefers-color-scheme: dark){:root:not([data-theme]){"""
    + _DARK
    + """}}
"""
)

_BASE = r"""
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
h1,h2,h3,h4{margin:0;line-height:1.25}
h1{font-size:24px;letter-spacing:-.01em}
h2{font-size:16px}
h3{font-size:14px}
p{margin:0}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}
button,input,select,textarea{font:inherit;color:inherit}
button{cursor:pointer}
:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.ico{width:18px;height:18px;flex:none;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.ico.sm{width:15px;height:15px}.ico.xs{width:13px;height:13px}.ico.lg{width:22px;height:22px}
.boot{padding:40px;color:var(--muted)}
.muted{color:var(--muted)}.faint{color:var(--muted)}.small{font-size:12.5px}.tiny{font-size:11.5px}.bold{font-weight:650}
.row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.row.flat{flex-wrap:nowrap}
.between{justify-content:space-between}.grow{flex:1;min-width:0}.sp{flex:1}
.stack{display:grid;grid-template-columns:minmax(0,1fr);gap:12px}.stack.s8{gap:8px}.stack.s16{gap:16px}
.hide{display:none!important}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.nowrap{white-space:nowrap}
.ell{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
"""

_SHELL = r"""
.app{display:grid;grid-template-columns:var(--side-w,252px) minmax(0,1fr);min-height:100vh;transition:grid-template-columns .2s ease}
body.rail .app{--side-w:68px}
.side{position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:6px;padding:14px 12px;background:var(--surface);border-right:1px solid var(--line);overflow-y:auto;overflow-x:hidden;z-index:35}
.sbrand{display:flex;align-items:center;gap:10px;padding:2px 6px 10px}
.logo{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,var(--brand),#7c3aed);color:#fff;font-weight:800;display:grid;place-items:center;flex:none;overflow:hidden}
.logo img{width:100%;height:100%;object-fit:contain;background:#fff}
.sbrand b{display:block;font-size:14px;line-height:1.2}
.sbrand small{color:var(--muted);font-size:12px}
.jump{display:flex;align-items:center;gap:8px;width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:var(--surface-2);color:var(--muted);text-align:left}
.jump:hover{border-color:var(--line-2)}
.kbd{margin-left:auto;font:11px ui-monospace,monospace;border:1px solid var(--line-2);border-radius:5px;padding:0 5px;background:var(--surface);color:var(--muted)}
.navlabel{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);padding:16px 10px 6px;white-space:nowrap}
.nav{display:grid;gap:2px}
.nav a,.nav .soon{display:flex;align-items:center;gap:11px;padding:8px 10px;border-radius:10px;color:var(--ink-2);font-weight:550;text-decoration:none;position:relative;white-space:nowrap}
.nav a:hover{background:var(--sunken);text-decoration:none}
.nav a.active{background:var(--brand-soft);color:var(--brand)}
.nav a .ico{color:var(--muted)}
.nav a.active .ico{color:var(--brand)}
.nav .soon{opacity:.55;cursor:default}
.nav .soon .ico{color:var(--faint)}
.nav .ct{margin-left:auto;background:var(--bad);color:var(--on-bad);border-radius:999px;font-size:11px;font-weight:700;padding:0 7px;line-height:18px}
.navtag{margin-left:auto;font-size:10px;font-weight:800;letter-spacing:.04em;padding:1px 6px;border-radius:5px;background:var(--sunken);color:var(--muted);text-transform:uppercase}
.side .grow{flex:1;min-height:12px}
.sidefoot{border-top:1px solid var(--line);padding-top:10px;display:grid;gap:2px}
.sidefoot a,.sidefoot button{display:flex;align-items:center;gap:11px;padding:8px 10px;border-radius:10px;border:0;background:none;color:var(--ink-2);font-weight:550;text-align:left;text-decoration:none;white-space:nowrap}
.sidefoot a:hover,.sidefoot button:hover{background:var(--sunken);text-decoration:none}
.sidefoot .ico{color:var(--muted)}
body.rail .sbrand b,body.rail .sbrand small,body.rail .jump span,body.rail .jump .kbd,body.rail .navtag,body.rail .nav .ct{display:none!important}
/* the words of the narrow menu are hidden by eye but stay for a screen reader: display:none would leave the icons with no name */
body.rail .nav .tx,body.rail .sidefoot .tx{position:absolute!important;width:1px!important;height:1px!important;margin:-1px!important;padding:0!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
body.rail .navlabel{height:1px;background:var(--line);margin:10px 8px;padding:0;font-size:0;overflow:hidden}
body.rail .nav a,body.rail .nav .soon,body.rail .sidefoot a,body.rail .sidefoot button{justify-content:center;padding:10px}
body.rail .jump{justify-content:center;padding:9px}
body.rail .sbrand{justify-content:center;padding:2px 0 10px}
.col{min-width:0;display:flex;flex-direction:column}
.topbar{position:sticky;top:0;z-index:30;height:var(--top-h);display:flex;align-items:center;gap:12px;padding:0 22px;background:color-mix(in srgb,var(--surface) 90%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.crumbs{display:flex;align-items:center;gap:8px;font-weight:650;min-width:0}
.crumbs .sep{color:var(--muted);font-weight:400}
.crumbs a{color:var(--muted);font-weight:550}
.iconbtn{width:36px;height:36px;border-radius:10px;border:1px solid transparent;background:none;display:grid;place-items:center;color:var(--ink-2)}
.iconbtn:hover{background:var(--sunken)}
.menubtn{display:none}
.main{flex:1;min-width:0}
.main:focus{outline:none}
.skip{position:fixed;left:12px;top:-64px;z-index:200;padding:10px 16px;border-radius:10px;background:var(--brand);color:var(--on-brand);font-weight:700;text-decoration:none;box-shadow:var(--sh2);transition:top .12s}
.skip:focus{top:12px;outline:2px solid var(--ink);outline-offset:2px;text-decoration:none}
.screen{padding:26px 30px 96px;max-width:1320px;margin:0 auto;animation:fade .18s ease}
.screen.bleed{padding:0;max-width:none}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.ph{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:18px}
.ph .sub{color:var(--muted);margin-top:3px;max-width:70ch}
.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:18px}
.page-head .sub{color:var(--muted);margin-top:3px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media (max-width:1000px){.app{--side-w:68px}.screen{padding:20px 16px 90px}}
@media (max-width:700px){
  .app{grid-template-columns:minmax(0,1fr)}
  .side{position:fixed;left:0;top:0;bottom:0;width:260px;transform:translateX(-102%);transition:transform .18s;box-shadow:var(--sh2)}
  body.menu-open .side{transform:none}
  body.rail .sbrand b,body.rail .sbrand small,body.rail .jump span,body.rail .jump .kbd,body.rail .navtag,body.rail .nav .ct{display:revert!important}
  body.rail .nav .tx,body.rail .sidefoot .tx{position:static!important;width:auto!important;height:auto!important;margin:0!important;overflow:visible!important;clip:auto!important}
  .menubtn{display:grid}
  .topbar{padding:0 12px}
}
"""

_COMPONENTS = r"""
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--sh1);min-width:0}
.card-h{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:13px 16px;border-bottom:1px solid var(--line);font-weight:650}
.card-h .muted{font-weight:400}
.card-b{padding:16px}
.card-b.flush{padding:0}
.grid{display:grid;gap:14px}
.g2{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--line-2);background:var(--surface);color:var(--ink);border-radius:10px;padding:7px 13px;font-weight:600;white-space:nowrap;text-decoration:none;line-height:1.3}
.btn:hover{background:var(--sunken);text-decoration:none}
.btn.primary{background:var(--brand);border-color:var(--brand);color:var(--on-brand)}
.btn.primary:hover{filter:brightness(1.08);background:var(--brand)}
.btn.ghost{border-color:transparent;background:transparent}
.btn.ghost:hover{background:var(--sunken)}
.btn.danger{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 45%,var(--line))}
.btn.danger.solid{background:var(--bad);border-color:var(--bad);color:var(--on-bad)}
.btn.sm{padding:4px 10px;font-size:13px;border-radius:8px}
.btn.icon{padding:7px;width:34px;height:34px}
.btn.sm.icon{width:28px;height:28px;padding:5px}
.btn[disabled]{opacity:.5;cursor:not-allowed}
.badge{--tc:var(--t-muted);display:inline-flex;align-items:center;gap:5px;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:650;line-height:20px;background:color-mix(in srgb,var(--tc) 13%,var(--surface));color:var(--tc-ink,var(--tc));white-space:nowrap}
.badge.ok{--tc:var(--ok);--tc-ink:var(--t-ok)}.badge.warn{--tc:var(--warn);--tc-ink:var(--t-warn)}.badge.bad{--tc:var(--bad);--tc-ink:var(--t-bad)}.badge.info{--tc:var(--info)}
.badge.brand{--tc:var(--brand)}.badge.violet{--tc:var(--k-ai);--tc-ink:var(--t-violet)}.badge.teal{--tc:var(--k-block);--tc-ink:var(--t-teal)}.badge.pink{--tc:var(--k-approve);--tc-ink:var(--t-pink)}.badge.orange{--tc:var(--k-tell);--tc-ink:var(--t-orange)}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--surface);border-radius:999px;padding:2px 10px;font-size:12.5px;color:var(--ink-2)}
.chip.sunk{background:var(--sunken);border-color:transparent}
.chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.seg{display:inline-flex;background:var(--sunken);border-radius:10px;padding:3px;gap:2px}
.seg button{border:0;background:none;padding:5px 12px;border-radius:8px;font-weight:600;color:var(--muted);display:inline-flex;gap:6px;align-items:center}
.seg button.on,.seg button[aria-pressed="true"]{background:var(--surface);color:var(--ink);box-shadow:var(--sh1)}
.fcard .fname{font:inherit;font-weight:700;margin:0}
.fcard .fname a{color:inherit;text-decoration:none}
.fcard .fname a:hover{text-decoration:underline}
.fcard:focus-within{outline:2px solid var(--brand);outline-offset:2px}
.switch{position:relative;display:inline-block;width:38px;height:22px;flex:none}
.switch input{opacity:0;width:0;height:0;position:absolute}
.switch span{position:absolute;inset:0;background:var(--line-2);border-radius:999px;transition:.15s;cursor:pointer}
.switch span::before{content:"";position:absolute;left:3px;top:3px;width:16px;height:16px;border-radius:50%;background:#fff;transition:.15s;box-shadow:0 1px 2px rgba(0,0,0,.3)}
.switch input:checked+span{background:var(--ok)}
.switch input:checked+span::before{transform:translateX(16px)}
.switch input:disabled+span{opacity:.5;cursor:not-allowed}
.switch.sm{width:32px;height:18px}.switch.sm span::before{width:12px;height:12px}.switch.sm input:checked+span::before{transform:translateX(14px)}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin:0 0 18px;overflow-x:auto}
.tab{padding:9px 14px;border:0;background:none;border-bottom:2px solid transparent;color:var(--muted);font-weight:650;white-space:nowrap;display:inline-flex;gap:7px;align-items:center;text-decoration:none}
.tab:hover{color:var(--ink);text-decoration:none}
.tab.active,.tab[aria-selected="true"]{color:var(--brand);border-color:var(--brand)}
.tab[disabled]{opacity:.55;cursor:not-allowed}
table.t{width:100%;border-collapse:collapse}
.t th{text-align:left;font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);padding:10px 14px;border-bottom:1px solid var(--line);white-space:nowrap;background:var(--surface-2)}
.t td{padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:top}
.t tr:last-child td{border-bottom:0}
.t tr.click{cursor:pointer}
.t tr.click:hover td{background:var(--brand-soft)}
.t td.num,.t th.num{text-align:right}
.t td.wide,.t th.wide{min-width:250px}
.tablewrap{overflow-x:auto}
.avatar,.av{width:28px;height:28px;border-radius:50%;display:inline-grid;place-items:center;color:#fff;font-weight:700;font-size:12px;flex:none}
.person{display:inline-flex;align-items:center;gap:8px;min-width:0}
.person .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.filters>*{min-width:0}
input[type=text],input[type=search],input[type=number],input[type=date],input[type=email],input[type=password],select,textarea,.input,.select,.textarea{border:1px solid var(--line-2);background:var(--surface);border-radius:9px;padding:7px 10px;min-width:0}
textarea{width:100%;resize:vertical;min-height:70px;line-height:1.5}
.input,.select{width:100%}
.input.sm,.select.sm{padding:4px 8px;font-size:13px;border-radius:8px}
input:focus,select:focus,textarea:focus{outline:2px solid var(--brand-line);border-color:var(--brand)}
.field{display:grid;gap:5px;margin-bottom:12px}
.field>label,.field>.lbl,.lbl{font-size:12.5px;font-weight:650;color:var(--ink-2)}
.field .hint,.hint{font-size:12px;color:var(--muted)}
.field input[type=text],.field input[type=number],.field input[type=date],.field select{width:100%}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.empty{padding:34px 16px;text-align:center;color:var(--muted)}
.empty b{display:block;color:var(--ink);margin-bottom:4px}
.notice{display:flex;gap:10px;align-items:flex-start;padding:10px 13px;border-radius:10px;background:color-mix(in srgb,var(--tc,var(--info)) 10%,var(--surface));color:var(--ink-2);border:1px solid color-mix(in srgb,var(--tc,var(--info)) 25%,var(--line));margin-bottom:14px}
.notice .ico{color:var(--tc,var(--info));margin-top:2px}
.notice.warn{--tc:var(--warn)}.notice.bad{--tc:var(--bad)}.notice.ok{--tc:var(--ok)}
.stack>.notice,.card-b>.notice{margin-bottom:0}
.kv{display:grid;grid-template-columns:130px 1fr;gap:9px 14px;font-size:13.5px;margin:0}
.kv dt{color:var(--muted)}.kv dd{margin:0;min-width:0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:12px;margin-bottom:16px}
.kpi{padding:14px 16px;cursor:pointer;border-radius:var(--r);background:var(--surface);border:1px solid var(--line);box-shadow:var(--sh1);display:grid;gap:2px;text-align:left;font:inherit;color:inherit;align-content:start;transition:border-color .12s}
.kpi:hover{border-color:var(--brand-line)}
.kpi .d{font-size:12px;font-weight:650}
.kpi svg.sp{display:block;width:100%;height:26px;margin-top:6px}
.kpi .n{font-size:28px;font-weight:750;line-height:1.1;letter-spacing:-.02em;font-variant-numeric:tabular-nums;order:2}
.kpi .l{color:var(--muted);order:1}
.kpi .d,.kpi svg.sp{order:3}
.kpi.warn .n{color:var(--warn)}.kpi.bad .n{color:var(--bad)}.kpi.ok .n{color:var(--ok)}.kpi.info .n{color:var(--info)}
.bar{display:grid;grid-template-columns:minmax(80px,150px) 1fr 34px;gap:10px;align-items:center;margin:7px 0;font-size:13px}
.bar .track{background:var(--sunken);border-radius:999px;height:10px;overflow:hidden}
.bar .fill{display:block;height:100%;background:var(--brand);border-radius:999px}
.bar .lbl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar .v{text-align:right;color:var(--muted)}
.x{border:0;background:none;font-size:22px;line-height:1;cursor:pointer;color:var(--muted);padding:2px 6px}
.dot{color:var(--brand);font-size:16px}
.code{background:var(--sunken);border-radius:9px;padding:10px 12px;overflow:auto;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;margin:0;white-space:pre-wrap}
.quote{white-space:pre-wrap;background:var(--sunken);border-radius:9px;padding:8px 11px;margin-top:5px}

/* overlays */
.scrim{position:fixed;inset:var(--top-h) 0 0 0;background:rgba(10,12,20,.32);z-index:50}
.scrim.top{inset:0;z-index:60}
.drawer{position:fixed;top:var(--top-h);right:0;bottom:0;width:min(640px,100%);background:var(--bg);border-left:1px solid var(--line);z-index:51;box-shadow:var(--sh2);display:flex;flex-direction:column}
.drawer .dh{padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:flex-start}
.drawer .dh h2{margin:0;font-size:17px;line-height:1.3}
.drawer .db{padding:16px 18px 40px;overflow:auto;display:grid;gap:14px;align-content:start}
.modal{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);width:min(560px,calc(100% - 24px));max-height:calc(100% - 24px);background:var(--surface);border-radius:14px;z-index:61;display:flex;flex-direction:column;box-shadow:var(--sh2);border:1px solid var(--line)}
.modal.wide{width:min(780px,calc(100% - 24px))}
.modal .mh{padding:14px 18px;border-bottom:1px solid var(--line);font-weight:700;font-size:16px;display:flex;align-items:center}
.modal .mb{padding:16px 18px;overflow:auto}
.modal .mf{padding:12px 18px;border-top:1px solid var(--line);display:flex;gap:8px;justify-content:flex-end;align-items:center;flex-wrap:wrap}
.modal .err{color:var(--bad);margin-right:auto;font-size:13px}
.pop{position:fixed;z-index:70;background:var(--surface);border:1px solid var(--line-2);border-radius:12px;box-shadow:var(--sh2);padding:6px;min-width:220px;max-height:min(72vh,560px);overflow:auto}
.pop .mi{display:flex;align-items:center;gap:10px;width:100%;padding:8px 10px;border:0;background:none;border-radius:8px;text-align:left;color:var(--ink-2)}
.pop .mi:hover{background:var(--sunken)}
.pop .mi small{display:block;color:var(--muted);font-size:12px}
.pop .ml{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding:8px 10px 4px}
.toasts{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:90;display:grid;gap:8px;justify-items:center}
.toast{display:flex;align-items:center;gap:10px;background:#111827;color:#fff;padding:9px 16px;border-radius:10px;box-shadow:var(--sh2);font-weight:550;animation:fade .2s;max-width:min(460px,92vw)}
.toast .tclose{flex:none;margin-left:6px;width:26px;height:26px;border:0;border-radius:7px;background:color-mix(in srgb,currentColor 20%,transparent);color:inherit;font-size:18px;line-height:1;cursor:pointer}
.toast .tclose:hover{background:color-mix(in srgb,currentColor 34%,transparent)}
.toast.bad{background:var(--bad);color:var(--on-bad)}.toast.ok{background:var(--ok);color:var(--on-ok)}
#tip{position:fixed;z-index:120;max-width:240px;background:#111827;color:#fff;font-size:12px;line-height:1.4;padding:8px 10px;border-radius:8px;box-shadow:var(--sh2);pointer-events:none;display:none}
.cmdk{position:fixed;inset:0;z-index:95;background:rgba(10,12,20,.4);display:flex;align-items:flex-start;justify-content:center;padding-top:14vh}
.cmdk .box{width:min(560px,92vw);background:var(--surface);border:1px solid var(--line-2);border-radius:14px;box-shadow:var(--sh2);overflow:hidden}
.cmdk input{width:100%;border:0;border-bottom:1px solid var(--line);border-radius:0;padding:14px 16px;background:none;outline:none;font-size:15px}
.cmdk .res{max-height:50vh;overflow:auto;padding:6px}
.cmdk .res button{display:flex;align-items:center;gap:10px;width:100%;padding:9px 10px;border:0;background:none;border-radius:8px;text-align:left}
.cmdk .res button.sel,.cmdk .res button:hover{background:var(--brand-soft)}
.cmdk .grp{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding:8px 10px 3px}

/* pickers, timelines, chat transcripts (older screens) */
.tcell{display:grid;gap:3px}
.tcell input{width:100%;max-width:140px}
.picker{position:relative}
.picker .results{position:absolute;left:0;right:0;top:100%;margin-top:4px;background:var(--surface);border:1px solid var(--line-2);border-radius:10px;box-shadow:var(--sh2);z-index:70;max-height:260px;overflow:auto}
.picker .opt{padding:8px 10px;cursor:pointer;display:flex;gap:8px;align-items:center;justify-content:space-between}
.picker .opt:hover,.picker .opt.on{background:var(--brand-soft)}
.picked{display:flex;align-items:center;gap:8px;border:1px solid var(--line-2);border-radius:9px;padding:5px 8px;background:var(--surface)}
.timeline{display:grid;gap:0}
.tl{display:grid;grid-template-columns:18px 1fr;gap:10px;padding-bottom:14px;position:relative}
.tl:before{content:"";position:absolute;left:8px;top:14px;bottom:-2px;width:2px;background:var(--line)}
.tl:last-child:before{display:none}
.tl .dot{width:10px;height:10px;border-radius:50%;background:var(--brand);margin:5px 0 0 4px;font-size:0}
.tl.comment .dot{background:var(--k-ai)}.tl.assignment .dot{background:var(--info)}.tl.status_change .dot,.tl.reopen .dot{background:var(--ok)}
.tl .when{color:var(--muted);font-size:12px}
.thread{display:grid;gap:12px;padding:4px 2px;max-height:68vh;overflow:auto;align-content:start}
.msg{display:grid;gap:3px;max-width:80%}
.msg.them{justify-self:end}.msg.bot{justify-self:start}
.msg .who{font-size:11.5px;color:var(--muted);padding:0 6px}
.msg.them .who{text-align:right}
.msg .b{white-space:pre-wrap;overflow-wrap:anywhere;padding:9px 13px;border-radius:16px;font-size:14px;line-height:1.45}
.msg.them .b{background:var(--brand-soft);border-bottom-right-radius:4px}
.msg.bot .b{background:var(--sunken);border-bottom-left-radius:4px}
.seatgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.rule{padding:14px 16px;display:grid;gap:8px}
.rule.off{opacity:.6}
.sentence{font-size:15px;line-height:1.7}
.sentence b{background:var(--brand-soft);padding:1px 7px;border-radius:6px;font-weight:600}
.matrix th,.matrix td{text-align:center}
.matrix th:first-child,.matrix td:first-child{text-align:left}
.cols{display:grid;grid-template-columns:1fr auto;gap:10px}
.spark{display:block;width:100%;height:110px}
.cols-21{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:14px;align-items:start}
.cols-2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;align-items:start}
@media (max-width:1000px){.cols-21,.cols-2{grid-template-columns:1fr}}
@media (max-width:900px){.two{grid-template-columns:1fr}.kv{grid-template-columns:100px 1fr}}
"""

_FORMS = r"""
/* the forms that edit one step or one part of a workflow (shared by the canvas panel) */
.maprow{display:grid;grid-template-columns:minmax(110px,.7fr) minmax(0,1.3fr) auto;gap:8px;align-items:start}
.cond{display:grid;grid-template-columns:minmax(0,1.2fr) 120px minmax(0,1fr) auto;gap:8px;align-items:start}
.tags{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.tags input{min-width:130px;flex:1}
.tags .chip .x{font-size:15px;padding:0 2px}
.checks{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:4px 12px}
.vp{display:grid;gap:6px}
.vp select,.vp input,.vp textarea{width:100%}
.subcfg{display:grid;gap:8px;padding:10px;border:1px dashed var(--line-2);border-radius:10px}
.prob{font-size:12.5px;padding:2px 0}
.prob.bad{color:var(--bad)}.prob.warn{color:var(--warn)}
.techlabel{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:12px;color:var(--muted);font-weight:600;margin-bottom:3px}
.vals{font-size:12px;color:var(--muted);margin:4px 0 0;padding-left:16px}
.trace{display:grid;gap:5px}
.tr{display:grid;grid-template-columns:22px 1fr;gap:8px;padding:7px 9px;border-radius:9px;background:var(--sunken);font-size:13px}
.tr .ic{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;color:#fff;background:var(--sc,var(--faint));font-size:11px;font-weight:700}
.tr.ran{--sc:var(--k-save)}.tr.would{--sc:var(--k-look)}.tr.skipped{--sc:var(--faint);opacity:.7}.tr.failed{--sc:var(--k-stop);background:color-mix(in srgb,var(--k-stop) 10%,var(--surface))}
.tr .dt{font-size:12px;color:var(--muted)}
.proposal{margin-top:8px;display:grid;gap:6px}
.diff{border-radius:9px;overflow:hidden;border:1px solid var(--line);font-size:12.5px}
.dl{padding:4px 10px;white-space:pre-wrap}
.dl.add{background:color-mix(in srgb,var(--ok) 14%,var(--surface))}
.dl.del{background:color-mix(in srgb,var(--bad) 12%,var(--surface));text-decoration:line-through;color:var(--muted)}
@media (max-width:700px){.maprow,.cond{grid-template-columns:1fr}}
"""

_SCREENS = r"""
/* settings: a menu, and one card per topic with a label on the left and its control on the right */
.setgrid{display:grid;grid-template-columns:200px minmax(0,1fr);gap:24px;align-items:start}
.setnav{position:sticky;top:calc(var(--top-h) + 20px);display:grid;gap:2px}
.setnav a{padding:8px 11px;border-radius:9px;color:var(--ink-2);font-weight:550;text-decoration:none;cursor:pointer}
.setnav a:hover{background:var(--sunken)}
.setnav a.on{background:var(--brand-soft);color:var(--brand)}
.srow{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,420px);gap:18px;padding:14px 0;border-bottom:1px solid var(--line);align-items:center}
.srow:last-child{border-bottom:0}
.srow:first-child{padding-top:2px}
.sctl{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.sctl input[type=number]{width:96px}
.sctl input[type=text]{width:100%;max-width:240px}
.sctl .dflt{flex-basis:100%;text-align:right;font-size:12px;color:var(--muted)}
.sctl .dflt.badtx{color:var(--bad)}
input.bad{border-color:var(--bad)}
.logo.lg{width:44px;height:44px;font-size:18px}
.logo.sm{width:24px;height:24px;font-size:12px;border-radius:7px}
/* messages: groups | the messages of one group | editor with a phone preview */
.msgs{display:grid;grid-template-columns:230px minmax(0,1fr) 400px;gap:14px;align-items:start}
@media (max-width:1250px){.msgs{grid-template-columns:200px minmax(0,1fr)}.msgs>.card:last-child{grid-column:1/-1}}
@media (max-width:760px){.msgs{grid-template-columns:minmax(0,1fr)}}
.mgroup{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:9px 12px;border-radius:10px;border:0;background:none;width:100%;text-align:left;color:var(--ink-2);font-weight:550;cursor:pointer}
.mgroup:hover{background:var(--sunken)}
.mgroup.on{background:var(--brand-soft);color:var(--brand)}
.mgroup .c{font-size:12px;color:var(--muted);font-weight:600}
.mi2{display:grid;gap:3px;padding:12px 16px;border:0;border-bottom:1px solid var(--line);border-left:3px solid transparent;cursor:pointer;width:100%;text-align:left;background:none;color:inherit;min-width:0}
.mi2:hover{background:var(--surface-2)}
.mi2.on{background:var(--brand-soft);border-left-color:var(--brand)}
.mi2 .row{min-width:0}
/* AI instructions: the layers one after the other, and the editor */
.aiwrap{display:grid;grid-template-columns:340px minmax(0,1fr);gap:14px;align-items:start}
.aiwrap>.notice{grid-column:1/-1}
@media (max-width:1000px){.aiwrap{grid-template-columns:minmax(0,1fr)}}
.lyrs{display:grid;gap:0}
.lyr{display:flex;align-items:center;gap:12px;padding:13px 14px;border-radius:12px;border:1px solid var(--line);background:var(--surface);position:relative;--lc:var(--k-other);text-align:left;width:100%;color:inherit;cursor:pointer;min-width:0}
.lyr.l1{--lc:var(--k-trigger)}.lyr.l2{--lc:var(--k-look)}.lyr.l3{--lc:var(--k-save)}.lyr.l4{--lc:var(--k-tell)}
.lyr:hover{background:var(--surface-2)}
.lyr.on{border-color:var(--brand-line);background:var(--brand-soft)}
.lyr.auto{cursor:default}.lyr.auto:hover{background:var(--surface)}
.lyr::before{content:"";position:absolute;left:0;top:10px;bottom:10px;width:4px;border-radius:0 4px 4px 0;background:var(--lc)}
.lyr .ln{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:color-mix(in srgb,var(--lc) 14%,var(--surface));color:var(--lc);font-weight:800;flex:none}
.lyr .badge{flex:none}
.lplus{display:grid;place-items:center;height:22px;color:var(--faint);font-weight:700}
.promptbox{font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;min-height:460px;width:100%;resize:vertical;white-space:pre-wrap}
.promptview{margin:0;max-height:62vh;overflow:auto;padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--surface-2);font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.difflist{border:1px solid var(--line);border-radius:10px;overflow:auto;max-height:62vh;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.difflist .dl.gap{color:var(--muted);text-align:center;font-style:italic;background:var(--surface-2);text-decoration:none}
.msgabout{padding:10px 16px;border-bottom:1px solid var(--line)}
.msgtotal{padding:10px 12px 2px;border-top:1px solid var(--line);margin-top:4px}
.msgtext{width:100%;min-height:140px;line-height:1.5;resize:vertical}
.phone{width:100%;max-width:340px;margin:6px auto 0;border:1px solid var(--line-2);border-radius:24px;background:var(--sunken);overflow:hidden;box-shadow:var(--sh1)}
.phone .pbar{display:flex;align-items:center;gap:8px;padding:10px 14px;background:var(--surface);border-bottom:1px solid var(--line);font-weight:650;font-size:13px}
.phone .pbody{padding:14px 12px;display:grid;gap:8px;min-height:120px;align-content:start}
.tgb{background:var(--surface);border:1px solid var(--line);padding:8px 11px;border-radius:14px;border-top-left-radius:4px;max-width:92%;font-size:13px;line-height:1.45;box-shadow:var(--sh1);white-space:pre-wrap;overflow-wrap:anywhere}
.varchip{display:inline-flex;align-items:center;font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;padding:2px 8px;border-radius:7px;border:1px solid var(--brand-line);background:var(--brand-soft);color:var(--brand);margin:0 4px 4px 0;cursor:pointer}
.varchip:hover{background:var(--brand);color:var(--on-brand)}
.varchip[disabled]{opacity:.5;cursor:not-allowed}
@media (max-width:1000px){.setgrid{grid-template-columns:minmax(0,1fr)}.setnav{display:none}}
@media (max-width:640px){.srow{grid-template-columns:minmax(0,1fr);gap:8px}.sctl{justify-content:flex-start}.sctl .dflt{text-align:left}}
.need-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:12px;margin-bottom:16px}
.need{--tc:var(--info);display:flex;gap:12px;padding:14px 14px 14px 18px;border-radius:var(--r);background:var(--surface);border:1px solid var(--line);box-shadow:var(--sh1);position:relative;text-align:left;width:100%}
.need::before{content:"";position:absolute;left:0;top:12px;bottom:12px;width:4px;border-radius:0 4px 4px 0;background:var(--tc)}
.need .ni{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:color-mix(in srgb,var(--tc) 13%,var(--surface));color:var(--tc);flex:none}
.need b{display:block;line-height:1.3}
.need.warn{--tc:var(--warn)}.need.bad{--tc:var(--bad)}.need.info{--tc:var(--info)}.need.ok{--tc:var(--ok)}
.progress{height:8px;border-radius:999px;background:var(--sunken);overflow:hidden}
.progress i{display:block;height:100%;background:var(--ok);border-radius:999px}
.check{display:flex;gap:11px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--line)}
.check:last-child{border-bottom:0}
.check .cb{width:20px;height:20px;border-radius:50%;border:2px solid var(--line-2);display:grid;place-items:center;flex:none;margin-top:1px}
.check.done .cb{background:var(--ok);border-color:var(--ok);color:var(--on-ok)}
.check.done b{color:var(--muted);text-decoration:line-through;font-weight:550}
.notice.teal{--tc:var(--k-block)}
.need .cta{font-weight:650;font-size:13px;display:inline-flex;gap:4px;align-items:center;margin-top:7px;color:var(--brand)}
.hl{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}
.pdot{width:9px;height:9px;border-radius:50%;background:var(--muted);flex:none;display:inline-block}
.pdot.ok{background:var(--ok)}.pdot.warn{background:var(--warn)}.pdot.bad{background:var(--bad)}
.hl:last-child{border-bottom:0}
.feed .fi{display:flex;gap:10px;padding:11px 16px;border-bottom:1px solid var(--line);align-items:flex-start}
.feed .fi:last-child{border-bottom:0}
.act{display:flex;gap:12px;padding:13px 16px;border-bottom:1px solid var(--line);align-items:flex-start}
.act:last-child{border-bottom:0}

/* Flows: cards and map */
.fcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}
.fcard{display:grid;grid-template-columns:minmax(0,1fr);gap:11px;padding:14px 15px;cursor:pointer;text-align:left;transition:.15s;align-content:start}
.fcard:hover{border-color:var(--brand-line);box-shadow:var(--sh2)}
.fcard.off{opacity:.7}
.thumb{display:flex;align-items:center;padding:11px 12px;background:var(--surface-2);border:1px solid var(--line);border-radius:10px;overflow:hidden;min-height:42px}
.thumb .tn{width:15px;height:15px;border-radius:5px;background:var(--kc,var(--k-other));flex:none}
.thumb .tn.blk{box-shadow:2px 2px 0 -1px var(--surface),2px 2px 0 0 var(--k-block)}
.thumb .tn.trg{width:18px;height:18px;border-radius:50%;background:var(--k-trigger);display:grid;place-items:center;color:#fff}
.thumb .tn.cond{outline:2px dashed var(--line-2);outline-offset:2px}
.thumb .tl2{width:9px;height:2px;background:var(--line-2);flex:none}
.mapwrap{position:relative;display:grid;grid-template-columns:1fr 1.3fr 1fr;gap:90px;padding:26px;background-color:var(--surface);border:1px solid var(--line);border-radius:var(--r);background-image:radial-gradient(circle,var(--line) 1px,transparent 1.2px);background-size:22px 22px}
.mcol{display:grid;gap:12px;align-content:start;position:relative;z-index:2}
.mcol h4{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-bottom:2px}
.mnode{--kc:var(--k-trigger);padding:10px 12px 10px 16px;border-radius:11px;border:1px solid var(--line-2);background:var(--surface);box-shadow:var(--sh1);text-align:left;position:relative;transition:opacity .15s;display:block;width:100%}
.mnode::before{content:"";position:absolute;left:-1px;top:9px;bottom:9px;width:4px;border-radius:0 4px 4px 0;background:var(--kc)}
.mnode.blk{--kc:var(--k-block)}
.mnode.unused{border-style:dashed}
.mnode.dim{opacity:.28}
.mnode:hover{box-shadow:var(--sh2)}
.medges{position:absolute;inset:0;pointer-events:none;width:100%;height:100%;z-index:1}
.medges path{fill:none;stroke:var(--k-block);stroke-width:2;opacity:.45;transition:opacity .15s}
.medges path.trg{stroke:var(--k-trigger)}
.medges path.hl{opacity:1;stroke-width:3}
.medges path.dim{opacity:.07}
@media (max-width:900px){.mapwrap{grid-template-columns:1fr;gap:20px}.medges{display:none}}
"""

_CANVAS = r"""
/* the flow editor: step drawers on the left, the canvas, the panel on the right */
.wsp{display:flex;flex-direction:column;height:calc(100vh - var(--top-h));height:calc(100dvh - var(--top-h));overflow:hidden;background:var(--bg)}
.wsprow{flex:1;min-height:0;display:grid;grid-template-columns:auto minmax(0,1fr) auto;position:relative}
.pal{width:272px;border-right:1px solid var(--line);background:var(--surface);display:flex;flex-direction:column;min-height:0}
.pal.closed{display:none}
.pal .pp{padding:12px;border-bottom:1px solid var(--line);display:grid;gap:8px}
.pal .pl{overflow:auto;padding:6px 8px 24px}
.ps{border-radius:10px}
.ps>summary{list-style:none;display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:9px;cursor:pointer;font-weight:650;user-select:none}
.ps>summary::-webkit-details-marker{display:none}
.ps>summary:hover{background:var(--sunken)}
.ps .chev{display:grid;color:var(--faint);transition:transform .15s}
.ps[open]>summary .chev{transform:rotate(90deg)}
.ps .pg{--gc:var(--k-other);width:22px;height:22px;border-radius:7px;display:grid;place-items:center;background:color-mix(in srgb,var(--gc) 14%,var(--surface));color:var(--gc);flex:none}
.ps .pg .ico{width:14px;height:14px}
.ps .n{margin-left:auto;font-size:12px;color:var(--muted);font-weight:600}
.ps>.pb{padding:2px 0 6px 10px;margin-left:19px;border-left:2px solid var(--line)}
.ps.sub>summary{font-weight:600;font-size:13px;padding:5px 8px}
.ps.sub .pg{width:18px;height:18px;border-radius:6px}
.ps.sub .pg i{width:8px;height:8px;border-radius:3px;background:var(--gc)}
.pi{--gc:var(--k-other);display:flex;align-items:center;gap:9px;width:100%;padding:5px 7px;border:1px solid transparent;border-radius:10px;background:none;text-align:left;color:var(--ink-2);font-weight:550;font-size:13.5px;cursor:grab}
.pi:hover{background:var(--sunken);border-color:var(--line)}
.pi:active{cursor:grabbing}
.pi .gi{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;background:color-mix(in srgb,var(--gc) 13%,var(--surface));color:var(--gc);flex:none}
.pi .gi .ico{width:15px;height:15px}
.pi .hq{margin-left:auto;width:19px;height:19px;border-radius:50%;display:grid;place-items:center;color:var(--muted);border:1px solid var(--line);font-size:11px;font-weight:700;flex:none}
.pi .hq:hover{color:var(--brand);border-color:var(--brand)}
.pi.later{opacity:.55;cursor:not-allowed}
.pi.later:hover{background:none;border-color:transparent}
.pi .soonp{margin-left:auto;font-size:10px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);border:1px solid var(--line-2);border-radius:5px;padding:0 5px;flex:none}
.pi.later .hq{margin-left:6px}
.pmine{display:block;padding:4px 6px 6px;color:var(--muted);font-size:12.5px}
.mnew{display:flex;align-items:center;gap:8px;width:100%;padding:6px 8px;margin-top:2px;border:1px dashed var(--line-2);border-radius:10px;background:none;color:var(--brand);font-weight:650;font-size:13px}
.mnew:hover{background:var(--brand-soft)}

.cvwrap{position:relative;min-width:0;display:flex;flex-direction:column;min-height:0}
.cv{position:relative;flex:1;overflow:auto;min-height:0;background:var(--bg);cursor:grab}
.cv.panning{cursor:grabbing}
.cv.droptarget{outline:3px dashed var(--brand);outline-offset:-6px}
.sizer{position:relative;background-image:radial-gradient(circle,var(--line-2) 1px,transparent 1.3px);background-size:22px 22px}
.stage{position:absolute;left:0;top:0;transform-origin:0 0}
.wires{position:absolute;left:0;top:0;width:100%;height:100%;overflow:visible;pointer-events:none}
.wire{fill:none;stroke:var(--line-2);stroke-width:2.4;transition:stroke .2s}
.wire.done{stroke:var(--k-save)}
.wire.skipw{stroke-dasharray:7 7;stroke-width:2}
.wire.tmpw{stroke:var(--brand);stroke-dasharray:5 5}
.wire.ghostw{stroke:var(--k-save);stroke-dasharray:6 6}
.arrow{fill:var(--line-2)}.arrow.ok{fill:var(--k-save)}
.nodes,.wlabels{position:absolute;left:0;top:0;width:0;height:0}
.plus{position:absolute;width:22px;height:22px;border-radius:50%;border:1px solid var(--line-2);background:var(--surface);color:var(--muted);display:grid;place-items:center;opacity:.55;transition:.12s;z-index:5;padding:0}
.plus:hover,.plus:focus-visible{opacity:1;background:var(--brand);color:#fff;border-color:var(--brand)}
.skiptxt{position:absolute;transform:translate(-100%,-50%);font-size:11px;font-weight:700;color:var(--muted);background:var(--bg);padding:1px 6px;border-radius:6px;white-space:nowrap;pointer-events:none}

.cvbar{display:flex;gap:10px 14px;align-items:center;flex-wrap:wrap;padding:8px 14px;background:var(--surface);border-bottom:1px solid var(--line);z-index:30}

.titlechip{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0;flex:1 1 320px}
.titlechip input.nm{border:1px solid transparent;background:none;font-weight:700;font-size:15px;flex:1 1 150px;min-width:110px;max-width:340px;padding:4px 8px;border-radius:8px}
.titlechip input.nm:hover,.titlechip input.nm:focus{border-color:var(--line-2);background:var(--surface-2);outline:none}
.actbar{margin-left:auto;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.vdiv{width:1px;height:22px;background:var(--line);margin:0 2px;flex:none}
.cvprob{padding:8px 14px 0;max-height:150px;overflow:auto;z-index:19}
.cvprob .notice{margin:0;padding:8px 12px;font-size:13px}
.cvprob:empty{display:none}

.zoomb{position:absolute;left:14px;bottom:14px;z-index:20;display:flex;gap:2px;padding:4px;background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--sh2);align-items:center;flex-wrap:wrap;max-width:calc(100% - 28px)}
.zoomb .zv{min-width:48px;text-align:center;font-weight:650;font-size:13px;color:var(--ink-2)}
.zoomb .btn.tidy{color:var(--brand);font-weight:700}
/* boxes side by side: the wire leaves and enters at the sides, level with the box's title */
.nd[data-pin="left"] .nd-port.in{left:-7px;top:21px;margin:0}
.nd[data-pout="right"] .nd-port.out{left:auto;right:-7px;bottom:auto;top:21px;margin:0}
.cv.rowmode .nd-exit{top:56px;transform:none}
.skiptxt.c{transform:translate(-50%,-50%)}
.stglbl{position:absolute;width:150px;text-align:right;font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--kc,var(--muted));line-height:1.25;pointer-events:none}
.tthumb{flex:none;color:var(--muted)}.tthumb rect{fill:currentColor;opacity:.6}
.pop .mi.on{background:var(--brand-soft)}.pop .mi .grow{min-width:0}

.nd{--kc:var(--k-look);position:absolute;width:var(--nw);background:var(--surface);border:1px solid var(--line-2);border-radius:14px;box-shadow:var(--sh1);text-align:left;cursor:grab;user-select:none;touch-action:none;transition:box-shadow .15s,border-color .15s,opacity .2s}
.nd::before{content:"";position:absolute;left:-1px;top:12px;bottom:12px;width:4px;border-radius:0 4px 4px 0;background:var(--kc)}
.nd:hover{box-shadow:var(--sh2)}
.nd.sel{border-color:var(--brand);outline:3px solid var(--brand-line)}
.nd.dragging{box-shadow:0 18px 40px -12px rgba(15,19,32,.35);z-index:30;cursor:grabbing}
.nd.drop{outline:3px dashed var(--brand);outline-offset:3px}
.nd.blk{box-shadow:0 4px 0 -1px var(--surface),0 5px 0 -1px var(--line-2),0 9px 0 -3px var(--surface),0 10px 0 -3px var(--line-2),var(--sh1)}
.nd.trig{border-color:color-mix(in srgb,var(--k-trigger) 45%,var(--line-2));background:linear-gradient(180deg,color-mix(in srgb,var(--k-trigger) 8%,var(--surface)),var(--surface) 70%)}
.nd-ord{position:absolute;top:-11px;left:-11px;min-width:22px;height:22px;padding:0 5px;border-radius:999px;background:var(--ink-2);color:var(--surface);font-size:11px;font-weight:800;display:grid;place-items:center;z-index:4;box-shadow:0 0 0 3px var(--bg)}
.nd-ord.trg{background:var(--k-trigger);color:#fff}
.nd-port{position:absolute;left:50%;width:14px;height:14px;margin-left:-7px;border-radius:50%;background:var(--surface);border:2px solid var(--line-2);z-index:4}
.nd-port.in{top:-8px}
.nd-port.out{bottom:-8px;cursor:crosshair}
.nd-port.out:hover{border-color:var(--brand);background:var(--brand-soft);transform:scale(1.25)}
.nd-h{display:flex;gap:11px;padding:13px 14px 12px 18px;align-items:flex-start}
.nd-gi{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;background:color-mix(in srgb,var(--kc) 13%,var(--surface));color:var(--kc);flex:none}
.nd-kind{font-size:10.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--kc);margin-bottom:1px}
.nd-t{font-weight:650;line-height:1.3;overflow-wrap:anywhere}
.nd-s{font-size:12.5px;color:var(--muted);margin-top:2px}
.nd-tags{margin-left:auto;display:flex;gap:6px;align-items:center;flex:none;padding-left:6px}
.tag{font-size:10.5px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;padding:1px 6px;border-radius:5px;border:1px solid var(--line-2);color:var(--muted);line-height:1.5}
.tag.tcode{color:var(--k-save);border-color:color-mix(in srgb,var(--k-save) 40%,var(--line))}
.tag.ai{color:#fff;background:var(--k-ai);border-color:var(--k-ai)}
.tag.blk{color:var(--k-block);border-color:color-mix(in srgb,var(--k-block) 45%,var(--line))}
.nd-cond{display:flex;gap:6px;align-items:center;padding:0 14px 11px 61px;font-size:12.5px;color:var(--info);font-weight:650}
.nd-wait{margin:0 14px 12px 61px;padding:6px 9px;border-radius:9px;background:color-mix(in srgb,var(--k-approve) 9%,var(--surface));color:var(--k-approve);font-size:12.5px;font-weight:650;display:flex;gap:6px;align-items:center}
.nd-foot{display:flex;gap:8px;align-items:center;padding:0 14px 12px 61px;font-size:12.5px;color:var(--muted);flex-wrap:wrap}
.nd-exp{border:0;background:none;padding:2px 0;color:var(--kc);font-weight:700;display:inline-flex;gap:4px;align-items:center;cursor:pointer}
.nd-tech{margin:0 14px 12px 18px;padding:8px 10px;background:var(--sunken);border-radius:9px;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;color:var(--ink-2);overflow:hidden;overflow-wrap:anywhere}
.nd-inside{margin:0 12px 12px 18px;padding:2px 0 2px 12px;border-left:2px solid color-mix(in srgb,var(--kc) 40%,var(--line));display:grid;gap:6px}
.nd-irow{--kc:var(--k-look);display:flex;gap:9px;align-items:center;font-size:13px;padding:6px 9px;border-radius:9px;background:var(--surface-2);border:1px solid var(--line)}
.nd-irow i{width:9px;height:9px;border-radius:3px;background:var(--kc);flex:none}
.nd-irow em{margin-left:auto;font-style:normal;font-size:11px;color:var(--k-stop);font-weight:700;white-space:nowrap}
.nd-irow em.when{color:var(--info);margin-left:6px}
.nd-exit{position:absolute;left:100%;top:50%;transform:translateY(-50%);display:flex;align-items:center;width:250px;cursor:default}
.nd-exit::before{content:"";width:34px;border-top:2px dashed var(--k-stop);flex:none}
.nd-xp{border:1px solid color-mix(in srgb,var(--k-stop) 40%,var(--line));background:color-mix(in srgb,var(--k-stop) 7%,var(--surface));color:var(--ink-2);border-radius:11px;padding:7px 10px;font-size:12.5px;line-height:1.35}
.nd-xp b{color:var(--k-stop);display:flex;align-items:center;gap:5px;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;margin-bottom:2px}
.nd-exit.lit::before{border-top-style:solid}
.nd-exit.lit .nd-xp{background:color-mix(in srgb,var(--k-stop) 15%,var(--surface));border-color:var(--k-stop)}
.nd-bad{position:absolute;top:-9px;right:-9px;width:22px;height:22px;border-radius:50%;background:var(--bad);color:var(--on-bad);font-weight:800;display:grid;place-items:center;box-shadow:0 0 0 3px var(--bg);z-index:4}
.nd-stb{position:absolute;top:-9px;right:-9px;width:24px;height:24px;border-radius:50%;display:none;place-items:center;color:#fff;background:var(--sc);z-index:4;box-shadow:0 0 0 3px var(--bg);font-weight:800;font-size:12px}
.nd[data-st] .nd-stb{display:grid}
.nd[data-st="ran"]{--sc:var(--k-save);border-color:color-mix(in srgb,var(--k-save) 55%,var(--line-2))}
.nd[data-st="would"]{--sc:var(--k-look);border-color:color-mix(in srgb,var(--k-look) 55%,var(--line-2))}
.nd[data-st="skipped"]{--sc:var(--faint);opacity:.55}
.nd[data-st="failed"]{--sc:var(--k-stop);border-color:var(--k-stop)}
.nd[data-st="nr"]{opacity:.35}
.nd-tsec{padding:0 14px 12px 61px;display:grid;gap:6px}
.nd-tl{font-size:10.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.nd.end{width:auto;padding:7px 16px;border-radius:999px;display:flex;gap:7px;align-items:center;color:var(--muted);font-weight:650;font-size:12.5px;cursor:default;white-space:nowrap}
.nd.end::before{display:none}
.nd.ghost{border:2px dashed var(--k-save);background:color-mix(in srgb,var(--k-save) 7%,var(--surface));cursor:default}
.nd-ghostbar{display:flex;gap:8px;padding:0 14px 13px 61px}

/* little tiles: a coloured square with the step's picture, and its name under it */
.nd.nc{width:116px;background:none;border:0;box-shadow:none;border-radius:0;padding:0;cursor:grab;text-align:center;font:inherit;color:inherit}
.nd.nc::before{display:none}
.nd.nc:hover{box-shadow:none}
.nd.nc.sel{border-color:transparent;outline:0}
.nd.nc.trig{background:none;border-color:transparent}
.nc-sq{position:relative;width:68px;height:68px;margin:0 auto;border-radius:18px;background:color-mix(in srgb,var(--kc) 11%,var(--surface));border:1.5px solid color-mix(in srgb,var(--kc) 40%,var(--line-2));box-shadow:var(--sh1);display:grid;place-items:center;color:var(--kc);transition:box-shadow .15s,border-color .15s}
.nc-sq .ico{width:30px;height:30px;stroke-width:1.7}
.nd.nc:hover .nc-sq{box-shadow:var(--sh2)}
.nd.nc.sel .nc-sq{border-color:var(--brand);outline:3px solid var(--brand-line)}
.nd.nc.drop{outline:0}
.nd.nc.drop .nc-sq{outline:3px dashed var(--brand);outline-offset:3px}
.nd.nc.dragging .nc-sq{box-shadow:0 18px 40px -12px rgba(15,19,32,.35)}
.nd.nc.blk .nc-sq{box-shadow:0 4px 0 -1px var(--surface),0 5px 0 -1px var(--line-2),var(--sh1)}
.nd.nc.trig .nc-sq{border-color:color-mix(in srgb,var(--k-trigger) 55%,var(--line-2));background:linear-gradient(180deg,color-mix(in srgb,var(--k-trigger) 14%,var(--surface)),var(--surface))}
.nc-nm{margin-top:7px;padding:0 3px;font-size:12.5px;font-weight:650;line-height:1.25;color:var(--ink);overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.nc-sub{margin-top:1px;padding:0 3px;font-size:11px;line-height:1.3;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nd.nc .nd-ord{top:-9px;left:14px}
.nd.nc .nd-stb,.nd.nc .nd-bad{top:-9px;right:13px}
.nd.nc .nd-port.out{bottom:-17px}
.nd.nc[data-pin="left"] .nd-port.in{left:17px;top:27px;margin:0}
.nd.nc[data-pout="right"] .nd-port.out{left:auto;right:17px;bottom:auto;top:27px;margin:0}
.nd.nc[data-st="ran"] .nc-sq{border-color:color-mix(in srgb,var(--k-save) 70%,var(--line-2))}
.nd.nc[data-st="would"] .nc-sq{border-color:color-mix(in srgb,var(--k-look) 70%,var(--line-2))}
.nd.nc[data-st="failed"] .nc-sq{border-color:var(--k-stop)}
.nc-bdg{position:absolute;right:-8px;bottom:-8px;display:flex;gap:3px}
.nc-b{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;background:var(--surface);border:1.5px solid var(--line-2);color:var(--muted);box-shadow:0 0 0 2px var(--bg)}
.nc-b .ico{width:11px;height:11px;stroke-width:2.2}
.nc-b-stop{color:var(--k-stop);border-color:var(--k-stop)}
.nc-b-if{color:var(--info);border-color:var(--info)}
.nc-b-wait{color:var(--k-approve);border-color:var(--k-approve)}
.nc-b-ai{color:#fff;background:var(--k-ai);border-color:var(--k-ai)}
/* the dashed square at the end of the flow: click it to add a step */
.nd.nc-end{cursor:pointer}
.nd.nc-end .nc-sq{background:none;border:1.5px dashed var(--line-2);box-shadow:none;color:var(--muted)}
.nd.nc-end:hover .nc-sq,.nd.nc-end:focus-visible .nc-sq{border-color:var(--brand);color:var(--brand);background:var(--brand-soft)}
.nd.nc-end .nc-nm{color:var(--muted)}
.nd.nc-end .nc-sub{white-space:normal}
/* parked: taken out of the flow, kept on the canvas */
.nd.parked{opacity:.82}
.nd.parked:not(.nc){border-style:dashed}
.nd.nc.parked .nc-sq{border-style:dashed;background:var(--surface);box-shadow:none}
.nd.nc.parked .nc-nm{color:var(--muted)}
.nd-parkn{display:flex;gap:6px;align-items:center;padding:0 14px 12px 61px;font-size:12.5px;color:var(--muted);font-weight:650}
/* the bar above a box, the bar on a wire, and the step picker's title */
.nd-bar{position:absolute;left:50%;top:-42px;display:none;gap:2px;padding:3px;background:var(--surface);border:1px solid var(--line-2);border-radius:10px;box-shadow:var(--sh2);z-index:8;cursor:default;white-space:nowrap;transform:translateX(-50%) scale(var(--zi,1));transform-origin:50% 100%}
.nd-bar::after{content:"";position:absolute;left:-6px;right:-6px;top:100%;height:14px}
.nd:hover>.nd-bar,.nd:focus-visible>.nd-bar{display:flex}
.nd-bb{width:28px;height:28px;border:0;background:none;border-radius:7px;color:var(--ink-2);display:grid;place-items:center;padding:0;cursor:pointer}
.nd-bb:hover,.nd-bb:focus-visible{background:var(--sunken);color:var(--brand)}
.nd-bb.del:hover{color:var(--bad)}
.wbar{position:absolute;display:none;gap:2px;padding:3px;background:var(--surface);border:1px solid var(--line-2);border-radius:10px;box-shadow:var(--sh2);z-index:9;transform:translate(-50%,-50%) scale(var(--zi,1))}
.cv.gest .nd-bar,.cv.gest .wbar{display:none!important}
.wirehit{fill:none;stroke:transparent;stroke-width:22;pointer-events:stroke;cursor:pointer}
.pk-h{padding:8px 10px 2px;font-weight:700;font-size:13.5px}
/* the bar at the bottom of the canvas and the chat pill share the space: when the canvas is narrow the words on the bar go and the pill moves above it */
.cvwrap{container-type:inline-size}
@container (max-width:1120px){.zoomb .tx{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}}
@container (max-width:860px){.dock.min{right:auto;left:14px;bottom:66px}}
@media (max-width:760px){.topbar .btn.primary .tx{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}}
.toast .tact{margin-left:14px;border:0;background:color-mix(in srgb,currentColor 20%,transparent);color:inherit;font-weight:700;padding:3px 11px;border-radius:7px;cursor:pointer}
.toast .tact:hover{background:color-mix(in srgb,currentColor 34%,transparent)}

.insp{width:420px;border-left:1px solid var(--line);background:var(--surface);display:flex;flex-direction:column;min-height:0}
.insp.closed{display:none}
.insp .ih{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;gap:11px;align-items:flex-start}
.insp .itabs{display:flex;gap:2px;padding:0 10px;border-bottom:1px solid var(--line);overflow-x:auto}
.insp .itabs .tab{padding:10px 12px;font-size:13px;margin:0}
.insp .ib{padding:16px;overflow:auto;display:grid;grid-template-columns:minmax(0,1fr);gap:15px;align-content:start;flex:1;min-height:0}
.insp .ib .two{grid-template-columns:1fr}
.insp .ib .field{margin-bottom:0}
.insp .if{padding:10px 14px;border-top:1px solid var(--line);display:flex;gap:6px;flex-wrap:wrap;background:var(--surface-2)}
.insp .gi{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;background:color-mix(in srgb,var(--kc,var(--brand)) 13%,var(--surface));color:var(--kc,var(--brand));flex:none}
.insp .kicker{font-size:10.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--kc,var(--brand))}

.dock{position:absolute;right:14px;bottom:14px;z-index:22;width:min(380px,calc(100% - 28px));background:var(--surface);border:1px solid var(--line-2);border-radius:16px;box-shadow:var(--sh2);display:flex;flex-direction:column;overflow:hidden}
.dock.min{width:auto;border-radius:999px}
.dock.min .chatdock{display:none}
.dock .dhd{display:flex;align-items:center;gap:8px;padding:10px 14px;font-weight:650;border:0;background:none;width:100%;text-align:left}




.bub{max-width:92%;padding:8px 12px;border-radius:14px;font-size:13.5px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere}
.bub.user{justify-self:end;background:var(--brand);color:var(--on-brand);border-bottom-right-radius:5px}
.bub.assistant{justify-self:start;background:var(--sunken);border-bottom-left-radius:5px}
.bub.error{background:color-mix(in srgb,var(--bad) 12%,var(--surface));color:var(--bad)}
.lgrow{display:flex;align-items:center;gap:10px;padding:5px 8px;font-size:13px}
.lgrow i{width:12px;height:12px;border-radius:4px;background:var(--kc)}
.pal{grid-column:1;grid-row:1}.cvwrap{grid-column:2;grid-row:1}.insp{grid-column:3;grid-row:1}
.cv{scrollbar-width:thin}
@media (max-width:1400px){:root{--nw:360px}.nd-exit{width:210px}.pal{width:248px}.insp{width:380px}}
@media (max-width:1180px){
  .pal,.insp{grid-column:auto;grid-row:auto}
  .pal{position:absolute;left:0;top:0;bottom:0;z-index:26;box-shadow:var(--sh2);width:min(300px,88vw)}
  .insp{position:absolute;right:0;top:0;bottom:0;z-index:25;box-shadow:var(--sh2);width:min(400px,92vw)}
}
@media (max-width:700px){
  .cvbar{padding:8px 10px;gap:8px}
  .cvbar .tx,.zoomb .tx{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
  .titlechip{flex-basis:100%}
  .titlechip input.nm{max-width:none}
  .actbar{margin-left:0;width:100%;justify-content:flex-end}
  .insp{left:0;right:0;top:auto;width:auto;height:66%;border-left:0;border-top:1px solid var(--line);border-radius:18px 18px 0 0}
  .zoomb{left:10px;bottom:10px;padding:3px}
  .zoomb .vdiv.opt,.zoomb .seg{display:none}
  .dock{right:10px;bottom:62px;width:min(380px,calc(100% - 20px))}
  .dock.min{width:46px;height:46px;border-radius:50%}
  .dock.min .dhd{padding:0;height:46px;justify-content:center}
  .dock.min .dhd span{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
  .dock.min .dhd .ico:last-child{display:none}
}
"""

_KINDS = r"""
/* the colour of what a step does: set on a box, a drawer item, a panel header... they all read --kc / --gc */
.k-trigger{--kc:var(--k-trigger);--gc:var(--k-trigger)}.k-look{--kc:var(--k-look);--gc:var(--k-look)}
.k-save{--kc:var(--k-save);--gc:var(--k-save)}.k-tell{--kc:var(--k-tell);--gc:var(--k-tell)}
.k-approve{--kc:var(--k-approve);--gc:var(--k-approve)}.k-other{--kc:var(--k-other);--gc:var(--k-other)}
.k-block{--kc:var(--k-block);--gc:var(--k-block)}.k-ai{--kc:var(--k-ai);--gc:var(--k-ai)}
.srch{position:relative}
.srch .ico{position:absolute;left:10px;top:50%;margin-top:-7.5px;color:var(--faint);pointer-events:none}
.srch .input{padding-left:32px}
/* the assistant box on the canvas reuses the chat from the editor */
.chatdock{display:flex;flex-direction:column}
.dock .chatdock>.card-h{display:none}
.chatlog{padding:10px 12px;overflow:auto;display:grid;gap:8px;align-content:start;min-height:100px;max-height:290px}
.bubble{padding:8px 12px;border-radius:14px;max-width:95%;font-size:13.5px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere}
.bubble.user{justify-self:end;background:var(--brand);color:var(--on-brand);border-bottom-right-radius:5px}
.bubble.assistant{justify-self:start;background:var(--sunken);border-bottom-left-radius:5px}
.bubble.error{background:color-mix(in srgb,var(--bad) 12%,var(--surface));color:var(--bad)}
.chatin{padding:10px;border-top:1px solid var(--line);display:grid;gap:8px}
.chatin textarea{min-height:48px}
"""

_STEPWIN = r"""
/* the step window: what comes in, the settings, what goes out */
.sw{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);width:min(1160px,calc(100% - 28px));height:min(780px,calc(100% - 28px));background:var(--surface);border:1px solid var(--line);border-radius:16px;z-index:61;display:flex;flex-direction:column;box-shadow:var(--sh2);overflow:hidden}
.sw-h{display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--line)}
.sw-h .gi{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:color-mix(in srgb,var(--kc,var(--brand)) 13%,var(--surface));color:var(--kc,var(--brand));flex:none}
.sw-h .kicker{font-size:10.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--kc,var(--brand))}
.sw-h .grow{min-width:0}
.sw-t{display:inline-flex;align-items:center;gap:7px;border:0;background:none;padding:1px 0;font-size:16px;font-weight:700;color:var(--ink);text-align:left;max-width:100%}
.sw-t span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sw-t .ico{color:var(--faint);flex:none}
.sw-t:hover .ico{color:var(--brand)}
.sw-nm{font-size:16px;font-weight:700;width:100%;max-width:520px}
.sw-sub{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sw-b{display:grid;grid-template-columns:268px minmax(0,1fr) 340px;flex:1;min-height:0}
.sw-p{overflow:auto;padding:14px 16px;min-width:0}
.sw-pl,.sw-pr{background:var(--surface-2)}
.sw-pm{border-left:1px solid var(--line);border-right:1px solid var(--line)}
.sw-ph{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:11px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin:0 0 10px}
.sw-tabs{display:flex;gap:2px;margin:-4px -6px 14px;border-bottom:1px solid var(--line);overflow-x:auto}
.sw-tabs .tab{padding:9px 12px;font-size:13px;margin:0}
.sw-tw{margin:0 0 6px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
.sw-tw summary{cursor:pointer;font-weight:650;font-size:13px}
.sw-tw[open] summary{margin-bottom:10px}
.sw-gt{font-size:11px;font-weight:700;color:var(--muted);margin:14px 0 5px;text-transform:uppercase;letter-spacing:.05em}
.sw-dp{display:block;width:100%;text-align:left;padding:6px 10px;margin:0 0 5px;border:1px dashed var(--line-2);border-radius:9px;background:var(--surface);color:var(--ink);font-size:13px;cursor:pointer}
.sw-dp:hover{border-color:var(--brand);background:var(--brand-soft)}
.sw-dp small{display:block;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.sw-kv{width:100%;border-collapse:collapse;font-size:13px;background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.sw-kv td{padding:6px 9px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
.sw-kv tr:last-child td{border-bottom:0}
.sw-kv td:first-child{width:42%;font-weight:650;color:var(--ink-2)}
.sw-json{margin:0;padding:10px;background:var(--surface);border:1px solid var(--line);border-radius:10px;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.sw-err{color:var(--bad);font-weight:700}
.sw-f{display:flex;align-items:center;gap:6px;padding:9px 16px;border-top:1px solid var(--line);background:var(--surface-2);flex-wrap:wrap}
.sw-f .grow{flex:1}
.dotn{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--brand);margin-left:6px}
.seg.sm button{padding:3px 10px;font-size:12px}
.cdd{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;border:1px solid var(--line-2);background:var(--surface);border-radius:9px;padding:7px 10px;text-align:left;color:var(--ink)}
.cdd:hover{border-color:var(--brand)}
.pop .cdd-o b{font-weight:650;display:block}
.pop .mi .kbd{margin-left:auto;padding-left:14px;font-size:11px;color:var(--muted)}
.pop .msep{height:1px;background:var(--line);margin:4px 6px}
.pop .mi.danger{color:var(--bad)}
.nc-b-note{color:var(--muted)}
.nd-note{display:flex;gap:6px;align-items:flex-start;padding:0 14px 12px 61px;font-size:12.5px;color:var(--muted);font-style:italic}
.cvprob li.jump{cursor:pointer;text-decoration:underline dotted}
.cvprob li.jump:hover{text-decoration:underline}
@media (max-width:1000px){.sw{width:calc(100% - 12px);height:calc(100% - 12px)}.sw-b{display:flex;flex-direction:column;overflow:auto}.sw-p{overflow:visible;flex:none}.sw-pm{order:1;border:0}.sw-pr{order:2;border-top:1px solid var(--line)}.sw-pl{order:3;border-top:1px solid var(--line)}}
"""

from app.admin_panel.ui.css_login import CSS as _LOGIN
from app.admin_panel.ui.css_redesign import CSS as _REDESIGN

CSS = (
    _TOKENS
    + _BASE
    + _SHELL
    + _COMPONENTS
    + _FORMS
    + _SCREENS
    + _CANVAS
    + _KINDS
    + _STEPWIN
    + _REDESIGN
    + _LOGIN
)
