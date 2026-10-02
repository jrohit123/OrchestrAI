CSS = r"""
:root{
  --bg:#f0f4f8; --panel:#ffffff; --ink:#1a1a2e; --muted:#64748b; --line:#e2e8f0; --line2:#cbd5e1;
  --brand:#185FA5; --brand-ink:#ffffff; --brand-soft:#e7f0fa; --side:#0f2744; --side-ink:#cfe0f3;
  --ok:#15803d; --ok-soft:#dcfce7; --warn:#b45309; --warn-soft:#fef3c7; --bad:#b91c1c; --bad-soft:#fee2e2;
  --info:#1d4ed8; --info-soft:#dbeafe; --violet:#6d28d9; --violet-soft:#ede9fe; --mute-soft:#eef2f6;
  --radius:10px; --shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.08);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0b1220; --panel:#131c2e; --ink:#e6edf7; --muted:#94a3b8; --line:#22304a; --line2:#2e405f;
    --brand:#4f9be0; --brand-ink:#06121f; --brand-soft:#16273f; --side:#08101d; --side-ink:#a9bdd6;
    --ok:#4ade80; --ok-soft:#10301d; --warn:#fbbf24; --warn-soft:#3a2d0c; --bad:#f87171; --bad-soft:#3b1414;
    --info:#7ab2ff; --info-soft:#14284a; --violet:#b69cff; --violet-soft:#241a45; --mute-soft:#1b263b;
    --shadow:0 1px 2px rgba(0,0,0,.4);
  }
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
a{color:var(--brand)}
button,input,select,textarea{font:inherit;color:inherit}
.boot{padding:40px;color:var(--muted)}
.shell{display:grid;grid-template-columns:244px minmax(0,1fr);min-height:100vh}
.side{background:var(--side);color:var(--side-ink);padding:16px 12px;position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:6px;overflow:auto}
.brand{display:flex;gap:10px;align-items:center;padding:6px 8px 14px;color:#fff;font-weight:700;font-size:15px;line-height:1.2}
.brand .logo{width:34px;height:34px;border-radius:9px;background:var(--brand);color:#fff;display:grid;place-items:center;font-weight:800;overflow:hidden;flex:none}
.brand .logo img{width:100%;height:100%;object-fit:cover}
.brand small{display:block;font-weight:500;color:var(--side-ink);opacity:.8;font-size:12px}
.nav{display:flex;flex-direction:column;gap:2px}
.nav a{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;color:var(--side-ink);text-decoration:none;font-weight:500}
.nav a:hover{background:rgba(255,255,255,.07)}
.nav a.active{background:rgba(255,255,255,.14);color:#fff}
.nav .ic{width:18px;text-align:center;opacity:.9}
.nav .count{margin-left:auto;font-size:11px;background:var(--bad);color:#fff;border-radius:999px;padding:1px 7px;font-weight:700}
.side .grow{flex:1}
.side .foot{border-top:1px solid rgba(255,255,255,.12);padding:10px 8px 2px;font-size:12px;display:grid;gap:8px}
.side .foot a{color:var(--side-ink)}
.side input{width:100%;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);color:#fff;border-radius:6px;padding:5px 8px;font-size:12px}
.main{padding:24px 28px 80px;min-width:0}
.page-head{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin-bottom:14px;flex-wrap:wrap}
.page-head h1{font-size:22px;margin:0;line-height:1.2}
.page-head .sub{color:var(--muted);margin-top:2px}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin:0 0 16px;overflow-x:auto}
.tab{padding:9px 14px;border:0;background:none;border-bottom:2px solid transparent;cursor:pointer;color:var(--muted);font-weight:600;white-space:nowrap;text-decoration:none}
.tab:hover{color:var(--ink)}
.tab.active{color:var(--brand);border-color:var(--brand)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);min-width:0}
.card-h{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line);font-weight:600}
.card-h .muted{font-weight:400}
.card-b{padding:16px}
.card-b.flush{padding:0}
.grid{display:grid;gap:14px}
.g2{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.kpis{grid-template-columns:repeat(auto-fit,minmax(165px,1fr));margin-bottom:14px}
.kpi{padding:14px 16px;cursor:pointer;border-left:4px solid var(--line2);transition:transform .08s}
.kpi:hover{transform:translateY(-1px)}
.kpi .n{font-size:28px;font-weight:700;line-height:1.1}
.kpi .l{color:var(--muted);margin-top:2px}
.kpi.warn{border-left-color:var(--warn)} .kpi.bad{border-left-color:var(--bad)} .kpi.ok{border-left-color:var(--ok)} .kpi.info{border-left-color:var(--info)}
.muted{color:var(--muted)}
.small{font-size:12px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.row.between{justify-content:space-between}
.stack{display:grid;gap:10px}
.sp{flex:1}
.btn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line2);background:var(--panel);color:var(--ink);border-radius:8px;padding:7px 12px;cursor:pointer;font-weight:600;text-decoration:none;white-space:nowrap}
.btn:hover{background:var(--mute-soft)}
.btn.primary{background:var(--brand);border-color:var(--brand);color:var(--brand-ink)}
.btn.primary:hover{filter:brightness(1.08)}
.btn.danger{color:var(--bad);border-color:var(--bad)}
.btn.danger.solid{background:var(--bad);color:#fff}
.btn.ghost{border-color:transparent;background:transparent}
.btn.sm{padding:4px 9px;font-size:13px}
.btn[disabled]{opacity:.55;cursor:not-allowed}
.badge{display:inline-flex;align-items:center;gap:4px;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap;background:var(--mute-soft);color:var(--muted)}
.badge.ok{background:var(--ok-soft);color:var(--ok)} .badge.warn{background:var(--warn-soft);color:var(--warn)}
.badge.bad{background:var(--bad-soft);color:var(--bad)} .badge.info{background:var(--info-soft);color:var(--info)}
.badge.violet{background:var(--violet-soft);color:var(--violet)} .badge.brand{background:var(--brand-soft);color:var(--brand)}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:2px 10px;font-size:12px}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.avatar{width:28px;height:28px;border-radius:50%;display:inline-grid;place-items:center;color:#fff;font-weight:700;font-size:12px;flex:none}
.person{display:inline-flex;align-items:center;gap:8px;min-width:0}
.person .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
table.t{width:100%;border-collapse:collapse}
.t th{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
.t td{padding:11px 12px;border-bottom:1px solid var(--line);vertical-align:top}
.t tr:last-child td{border-bottom:0}
.t tr.click{cursor:pointer}
.t tr.click:hover{background:var(--brand-soft)}
.t td.num,.t th.num{text-align:right}
.t td.wide,.t th.wide{min-width:250px}
.tablewrap{overflow-x:auto}
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.filters>*{min-width:0}
input[type=text],input[type=search],input[type=number],input[type=date],select,textarea{border:1px solid var(--line2);background:var(--panel);border-radius:8px;padding:7px 10px;min-width:0}
textarea{width:100%;resize:vertical;min-height:70px}
input:focus,select:focus,textarea:focus{outline:2px solid var(--brand-soft);border-color:var(--brand)}
.field{display:grid;gap:4px;margin-bottom:12px}
.field>label,.field>.lbl{font-weight:600;font-size:13px}
.field .hint{color:var(--muted);font-size:12px}
.field input[type=text],.field input[type=number],.field input[type=date],.field select{width:100%}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.switch{position:relative;width:38px;height:22px;flex:none;display:inline-block}
.switch input{opacity:0;width:0;height:0}
.switch span{position:absolute;inset:0;background:var(--line2);border-radius:999px;transition:.15s;cursor:pointer}
.switch span:before{content:"";position:absolute;left:3px;top:3px;width:16px;height:16px;border-radius:50%;background:#fff;transition:.15s}
.switch input:checked+span{background:var(--ok)}
.switch input:checked+span:before{transform:translateX(16px)}
.switch input:disabled+span{opacity:.5;cursor:not-allowed}
.empty{padding:34px 16px;text-align:center;color:var(--muted)}
.empty b{display:block;color:var(--ink);margin-bottom:4px}
.notice{padding:10px 14px;border-radius:8px;background:var(--info-soft);color:var(--info);margin-bottom:14px}
.notice.warn{background:var(--warn-soft);color:var(--warn)}
.notice.bad{background:var(--bad-soft);color:var(--bad)}
.bar{display:grid;grid-template-columns:minmax(80px,150px) 1fr 34px;gap:10px;align-items:center;margin:7px 0;font-size:13px}
.bar .track{background:var(--mute-soft);border-radius:999px;height:10px;overflow:hidden}
.bar .fill{height:100%;background:var(--brand);border-radius:999px}
.bar .lbl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar .v{text-align:right;color:var(--muted)}
.kv{display:grid;grid-template-columns:130px 1fr;gap:6px 12px;font-size:13.5px}
.kv dt{color:var(--muted)} .kv dd{margin:0;min-width:0}
.scrim{position:fixed;inset:0;background:rgba(15,23,42,.4);z-index:50}
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(640px,100%);background:var(--bg);z-index:51;box-shadow:-12px 0 32px rgba(0,0,0,.22);display:flex;flex-direction:column}
.drawer .dh{padding:14px 18px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:flex-start}
.drawer .dh h2{margin:0;font-size:17px;line-height:1.3}
.drawer .db{padding:16px 18px 40px;overflow:auto;display:grid;gap:14px;align-content:start}
.x{border:0;background:none;font-size:22px;line-height:1;cursor:pointer;color:var(--muted);padding:2px 6px}
.modal{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);width:min(560px,calc(100% - 24px));max-height:calc(100% - 24px);background:var(--panel);border-radius:12px;z-index:61;display:flex;flex-direction:column;box-shadow:0 20px 50px rgba(0,0,0,.3)}
.modal.wide{width:min(760px,calc(100% - 24px))}
.modal .mh{padding:14px 18px;border-bottom:1px solid var(--line);font-weight:700;font-size:16px;display:flex;align-items:center}
.modal .mb{padding:16px 18px;overflow:auto}
.modal .mf{padding:12px 18px;border-top:1px solid var(--line);display:flex;gap:8px;justify-content:flex-end;align-items:center;flex-wrap:wrap}
.modal .err{color:var(--bad);margin-right:auto;font-size:13px}
.scrim.top{z-index:60}
.toasts{position:fixed;right:16px;bottom:16px;z-index:80;display:grid;gap:8px}
.toast{background:#0f172a;color:#fff;padding:10px 14px;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.3);max-width:360px}
.toast.bad{background:var(--bad)} .toast.ok{background:var(--ok)}
.timeline{display:grid;gap:0}
.tl{display:grid;grid-template-columns:18px 1fr;gap:10px;padding-bottom:14px;position:relative}
.tl:before{content:"";position:absolute;left:8px;top:14px;bottom:-2px;width:2px;background:var(--line)}
.tl:last-child:before{display:none}
.tl .dot{width:10px;height:10px;border-radius:50%;background:var(--brand);margin:5px 0 0 4px}
.tl.comment .dot{background:var(--violet)} .tl.assignment .dot{background:var(--info)} .tl.status_change .dot,.tl.reopen .dot{background:var(--ok)}
.tl .when{color:var(--muted);font-size:12px}
.quote{white-space:pre-wrap;background:var(--mute-soft);border-radius:8px;padding:8px 10px;margin-top:4px}
.thread{display:grid;gap:12px;padding:4px 2px;max-height:68vh;overflow:auto;align-content:start}
.msg{display:grid;gap:3px;max-width:80%}
.msg.them{justify-self:end}
.msg.bot{justify-self:start}
.msg .who{font-size:11.5px;color:var(--muted);padding:0 6px}
.msg.them .who{text-align:right}
.msg .b{white-space:pre-wrap;overflow-wrap:anywhere;padding:9px 13px;border-radius:16px;font-size:14px;line-height:1.45}
.msg.them .b{background:var(--brand-soft);border-bottom-right-radius:4px}
.msg.bot .b{background:var(--mute-soft);border-bottom-left-radius:4px}
.tcell{display:grid;gap:3px}
.tcell input{width:100%;max-width:140px}
.picker{position:relative}
.picker .results{position:absolute;left:0;right:0;top:100%;margin-top:4px;background:var(--panel);border:1px solid var(--line2);border-radius:8px;box-shadow:0 10px 28px rgba(0,0,0,.18);z-index:70;max-height:260px;overflow:auto}
.picker .opt{padding:8px 10px;cursor:pointer;display:flex;gap:8px;align-items:center;justify-content:space-between}
.picker .opt:hover,.picker .opt.on{background:var(--brand-soft)}
.picked{display:flex;align-items:center;gap:8px;border:1px solid var(--line2);border-radius:8px;padding:5px 8px;background:var(--panel)}
.seatgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.rule{padding:14px 16px;display:grid;gap:8px}
.rule.off{opacity:.6}
.sentence{font-size:15px;line-height:1.7}
.sentence b{background:var(--brand-soft);padding:1px 7px;border-radius:6px;font-weight:600}
.matrix th,.matrix td{text-align:center}
.matrix th:first-child,.matrix td:first-child{text-align:left}
.cols{display:grid;grid-template-columns:1fr auto;gap:10px}
.spark{display:block;width:100%;height:110px}
.mobilebar{display:none}
@media (max-width:900px){
  .shell{grid-template-columns:1fr}
  .side{position:fixed;left:0;top:0;bottom:0;width:260px;z-index:55;transform:translateX(-100%);transition:transform .18s}
  .side.open{transform:none}
  .mobilebar{display:flex;gap:10px;align-items:center;padding:10px 14px;background:var(--side);color:#fff;position:sticky;top:0;z-index:40}
  .mobilebar button{background:none;border:0;color:#fff;font-size:22px;cursor:pointer}
  .main{padding:16px 14px 80px}
  .two{grid-template-columns:1fr}
  .kv{grid-template-columns:100px 1fr}
}

.studio-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 12px;position:sticky;top:0;z-index:20;background:var(--bg);padding:6px 0}
.namebox{font-size:18px;font-weight:600;border:1px solid transparent;background:transparent;min-width:200px;flex:1 1 220px;max-width:420px}
.namebox:hover,.namebox:focus{border-color:var(--line2);background:var(--panel)}
.studio-grid{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:14px;align-items:start}
.steps{display:grid;gap:0}
.addpt{display:flex;justify-content:center;height:22px;align-items:center;position:relative}
.addpt .btn.ghost{opacity:0;padding:0 10px;height:20px;font-size:13px;transition:opacity .1s}
.addpt:hover .btn.ghost,.addpt .btn.ghost:focus{opacity:1}
.addpt:last-child{height:auto;padding:10px 0 0}
.stcard{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.stcard.open{border-color:var(--brand)}
.stcard.flash{background:var(--ok-soft)}
.st-head{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;cursor:pointer}
.st-head .num{width:24px;height:24px;border-radius:50%;background:var(--mute-soft);color:var(--muted);font-size:12px;font-weight:600;display:grid;place-items:center;flex:none}
.st-head .glyph{width:22px;text-align:center;font-size:16px;color:var(--brand);flex:none;line-height:24px}
.st-title{font-weight:600;overflow-wrap:anywhere}
.ib{border:0;background:none;padding:2px 7px;min-width:26px;cursor:pointer;color:var(--muted);border-radius:6px}
.ib:hover{background:var(--mute-soft);color:var(--ink)}
.stepform{padding:4px 14px 14px 56px;display:grid;gap:2px;border-top:1px solid var(--line)}
.stepform .field{margin-bottom:8px}
.vp{display:grid;gap:6px}
.vp select,.vp input,.vp textarea{width:100%}
.maprow{display:grid;grid-template-columns:minmax(120px,.7fr) minmax(0,1.3fr) auto;gap:8px;align-items:start}
.cond{display:grid;grid-template-columns:minmax(0,1.2fr) 130px minmax(0,1fr) auto;gap:8px;align-items:start}
.tags{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.tags input{min-width:140px;flex:1}
.tags .chip .x{font-size:15px;padding:0 2px}
.checks{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:4px 12px}
.prob{font-size:12.5px;padding:4px 14px 8px 56px}
.prob.bad{color:var(--bad)}.prob.warn{color:var(--warn)}
.code{background:var(--mute-soft);border-radius:8px;padding:10px 12px;overflow:auto;font:12px/1.5 ui-monospace,monospace;margin:0;white-space:pre-wrap}
.addgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px}
.addtile{display:grid;gap:3px;text-align:left;border:1px solid var(--line2);background:var(--panel);border-radius:10px;padding:10px 12px;cursor:pointer}
.addtile:hover{border-color:var(--brand);background:var(--brand-soft)}
.chatdock{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);display:flex;flex-direction:column;position:sticky;top:64px;max-height:calc(100vh - 90px)}
.chatlog{padding:10px;overflow:auto;display:grid;gap:8px;align-content:start;min-height:160px;flex:1}
.bubble{padding:8px 11px;border-radius:12px;max-width:95%;font-size:13.5px;overflow-wrap:anywhere}
.bubble.user{background:var(--brand);color:var(--brand-ink);justify-self:end}
.bubble.assistant{background:var(--mute-soft)}
.bubble.error{background:var(--bad-soft);color:var(--bad)}
.chatin{padding:10px;border-top:1px solid var(--line);display:grid;gap:8px}
.chatin textarea{min-height:56px}
.proposal{margin-top:8px;display:grid;gap:6px}
.diff{border-radius:8px;overflow:hidden;border:1px solid var(--line);font-size:12.5px}
.dl{padding:5px 8px}
.dl.add{background:var(--ok-soft);color:var(--ok)}
.dl.del{background:var(--bad-soft);color:var(--bad);text-decoration:line-through}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:9px;overflow:hidden}
.seg button{border:0;background:var(--panel);padding:6px 14px;cursor:pointer;color:var(--muted);font-weight:600}
.seg button.on{background:var(--brand);color:var(--brand-ink)}
.tech{display:grid;gap:10px}
.techstep{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.techstep .th{display:flex;gap:10px;align-items:flex-start;padding:10px 12px}
.techstep .tb{padding:0 12px 12px 46px;display:grid;gap:10px}
.techlabel{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:12px;color:var(--muted);font-weight:600;margin-bottom:3px}
.vals{font-size:12px;color:var(--muted);margin:4px 0 0;padding-left:16px}
.trace{display:grid;gap:4px}
.tr{display:grid;grid-template-columns:22px 1fr;gap:8px;padding:6px 8px;border-radius:8px;background:var(--mute-soft)}
.tr .ic{font-weight:700;text-align:center}
.tr.ran .ic{color:var(--ok)}.tr.would .ic{color:var(--info)}.tr.skipped{opacity:.6}.tr.failed{background:var(--bad-soft)}.tr.failed .ic{color:var(--bad)}
.tr .dt{font-size:12.5px;color:var(--muted)}
.subcfg{display:grid;gap:8px;padding:10px;border:1px dashed var(--line2);border-radius:8px}
.tile-sep{grid-column:1/-1;font-size:12px;color:var(--muted);margin-top:4px}
@media (max-width:1100px){.studio-grid{grid-template-columns:1fr}.chatdock{position:static;max-height:none}}
@media (max-width:700px){.maprow,.cond{grid-template-columns:1fr}.stepform{padding-left:14px}.prob{padding-left:14px}}
"""
