"""Styles for signing in (the sign-in, sign-up and forgot-password pages), the account menu, the
super admin page and the admin's help card. New class names only (lgn-*, acct, sa-*, pr-help)."""

CSS = r"""
/* ───── the sign-in pages ───── */
.lgn{min-height:100vh;display:grid;grid-template-columns:minmax(0,1.12fr) minmax(0,1fr);background:var(--bg)}
.lgn-hero{position:relative;overflow:hidden;color:#fff;padding:38px 56px 34px;display:flex;flex-direction:column;gap:24px;
  background:radial-gradient(640px 460px at 12% 8%,rgba(139,92,246,.55),transparent 62%),radial-gradient(560px 520px at 92% 88%,rgba(20,184,166,.32),transparent 62%),radial-gradient(520px 420px at 78% 0%,rgba(99,102,241,.45),transparent 60%),linear-gradient(160deg,#0e0b2b 0%,#1a1450 52%,#241d78 100%)}
.lgn-hero::before{content:"";position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.055) 1px,transparent 1px);background-size:46px 46px;-webkit-mask-image:radial-gradient(ellipse 80% 70% at 30% 25%,#000 25%,transparent 75%);mask-image:radial-gradient(ellipse 80% 70% at 30% 25%,#000 25%,transparent 75%)}
.lgn-hero>*{position:relative}
.lgn-orb{position:absolute!important;border-radius:50%;filter:blur(64px);opacity:.5;pointer-events:none;animation:lgnFloat 14s ease-in-out infinite}
.lgn-orb.a{width:280px;height:280px;background:#7c3aed;top:-90px;right:10%}
.lgn-orb.b{width:240px;height:240px;background:#06b6d4;bottom:-70px;left:6%;animation-delay:-6s;opacity:.32}
@keyframes lgnFloat{0%,100%{transform:translate(0,0)}50%{transform:translate(26px,-20px)}}
.lgn-brand{display:flex;align-items:center;gap:11px;font-weight:750;font-size:19px;letter-spacing:-.01em}
.lgn-mark{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;display:grid;place-items:center;box-shadow:0 10px 26px -8px rgba(99,102,241,.85);flex:none}
.lgn-hero h1{font-size:clamp(30px,3.1vw,45px);line-height:1.08;letter-spacing:-.03em;max-width:20ch;font-weight:800;color:#fff}
.lgn-hero h1 em{font-style:normal;background:linear-gradient(90deg,#a5b4fc,#67e8f9);-webkit-background-clip:text;background-clip:text;color:transparent}
.lgn-lead{color:rgba(255,255,255,.78);font-size:16.5px;max-width:46ch;margin-top:12px}
.lgn-stage{position:relative;height:320px;max-width:560px;margin-top:4px}
.lgn-phone{position:absolute;left:0;top:0;width:300px;border-radius:22px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.18);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);box-shadow:0 30px 60px -20px rgba(0,0,0,.6);overflow:hidden;transform:rotate(-2deg)}
.lgn-phone .hd{display:flex;align-items:center;gap:10px;padding:12px 14px;background:rgba(255,255,255,.08);border-bottom:1px solid rgba(255,255,255,.12)}
.lgn-phone .av{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#06b6d4);display:grid;place-items:center;font-weight:800;flex:none}
.lgn-phone .hd b{display:block;font-size:13.5px;line-height:1.2}
.lgn-phone .hd small{color:rgba(255,255,255,.65);font-size:11.5px}
.lgn-phone .hd small::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:#34d399;margin-right:5px}
.lgn-phone .bd{height:232px;padding:12px;display:flex;flex-direction:column;gap:8px;overflow:hidden}
.lgn-phone .b{max-width:88%;padding:8px 11px;border-radius:14px;font-size:13px;line-height:1.38;animation:lgnPop .3s ease both}
.lgn-phone .b.in{align-self:flex-start;background:rgba(255,255,255,.14);border-bottom-left-radius:4px}
.lgn-phone .b.out{align-self:flex-end;background:linear-gradient(135deg,#5b5bf0,#7c5cf5);border-bottom-right-radius:4px}
.lgn-phone .b.typing{display:flex;gap:4px;padding:11px 13px}
.lgn-phone .b.typing i{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,.85);animation:lgnDot 1s infinite}
.lgn-phone .b.typing i:nth-child(2){animation-delay:.15s}.lgn-phone .b.typing i:nth-child(3){animation-delay:.3s}
@keyframes lgnDot{0%,60%,100%{opacity:.3;transform:translateY(0)}30%{opacity:1;transform:translateY(-3px)}}
@keyframes lgnPop{from{opacity:0;transform:translateY(8px) scale(.97)}to{opacity:1;transform:none}}
.lgn-glass{position:absolute;display:flex;align-items:center;gap:12px;padding:13px 15px;border-radius:16px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);box-shadow:0 24px 50px -20px rgba(0,0,0,.6)}
.lgn-needs{right:0;bottom:4px;width:318px;animation:lgnBob 7s ease-in-out infinite}
.lgn-needs .ic{width:38px;height:38px;border-radius:11px;background:rgba(251,191,36,.2);color:#fbbf24;display:grid;place-items:center;flex:none}
.lgn-needs b{display:block;font-size:13.5px;line-height:1.25}
.lgn-needs small{color:rgba(255,255,255,.66);font-size:12px}
.lgn-needs .n{display:inline-block;min-width:1ch}
.lgn-needs .n.tick{animation:lgnTick .7s ease}
@keyframes lgnTick{0%{transform:scale(1);color:#fbbf24}40%{transform:scale(1.6);color:#34d399}100%{transform:scale(1)}}
.lgn-chip{right:14px;top:16px;padding:9px 13px;font-size:12.5px;opacity:0;transform:translateY(10px);transition:opacity .4s,transform .4s}
.lgn-chip.on{opacity:1;transform:none}
.lgn-chip .ico{color:#34d399}
@keyframes lgnBob{0%,100%{translate:0 0}50%{translate:0 -7px}}
.lgn-points{display:flex;gap:10px 24px;flex-wrap:wrap;margin-top:auto;padding-top:4px}
.lgn-points div{display:flex;align-items:center;gap:9px;color:rgba(255,255,255,.88);font-size:13.5px}
.lgn-points .ico{color:#a5b4fc}
.lgn-orgs{display:flex;align-items:center;gap:8px;color:rgba(255,255,255,.62);font-size:12.5px}
.lgn-orgs .logo{width:26px;height:26px;border-radius:8px;font-size:12px;display:grid;place-items:center;background:rgba(255,255,255,.16);color:#fff;font-weight:700}
.lgn-main{position:relative;display:grid;align-content:center;justify-items:center;gap:18px;padding:44px 24px;background:radial-gradient(700px 420px at 100% 0%,color-mix(in srgb,var(--brand) 11%,transparent),transparent),var(--bg)}
.lgn-theme{position:absolute;top:16px;right:16px}
.lgn-mini{display:none;align-items:center;gap:12px;width:100%;max-width:450px;padding:14px 16px;border-radius:16px;color:#fff;background:linear-gradient(135deg,#1a1450,#3b2fb0 70%,#5b3fd6)}
.lgn-mini b{display:block}
.lgn-mini small{color:rgba(255,255,255,.75)}
.lgn-card{width:100%;max-width:450px;background:var(--surface);border:1px solid var(--line);border-radius:22px;box-shadow:var(--sh2);padding:30px 30px 24px;animation:lgnIn .5s cubic-bezier(.2,.8,.2,1) both}
@keyframes lgnIn{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.lgn-card h2{font-size:25px;letter-spacing:-.02em}
.lgn-card .sub{color:var(--muted);margin:4px 0 20px}
.lgn-card .field{margin-bottom:14px}
.lgn-card .notice{margin-bottom:14px;display:flex;gap:8px;align-items:flex-start}
.lgn-in{position:relative}
.lgn-in>.ico{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--faint);pointer-events:none}
.lgn-in input{width:100%;padding:11px 42px 11px 40px;border-radius:12px}
.lgn-in input:focus{border-color:var(--brand);box-shadow:0 0 0 4px color-mix(in srgb,var(--brand) 18%,transparent);outline:0}
.lgn-eye{position:absolute;right:5px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--muted);width:34px;height:34px;border-radius:9px;display:grid;place-items:center}
.lgn-eye:hover{background:var(--sunken);color:var(--ink)}
.lgn-row{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:2px 0 16px;font-size:13px}
.lgn-card .btn.primary.lgn-go{width:100%;justify-content:center;gap:8px;padding:12px 16px;font-size:15px;font-weight:650;border:0;border-radius:12px;background:linear-gradient(135deg,var(--brand),color-mix(in srgb,var(--brand) 55%,#7c3aed));color:var(--on-brand);box-shadow:0 12px 26px -12px color-mix(in srgb,var(--brand) 80%,transparent);transition:transform .15s,box-shadow .15s}
.lgn-card .btn.primary.lgn-go:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 16px 30px -12px color-mix(in srgb,var(--brand) 85%,transparent)}
.lgn-go .ico{transition:transform .15s}
.lgn-go:hover:not(:disabled) .ico{transform:translateX(3px)}
.lgn-go.busy .ico{display:none}
.lgn-go.busy::before{content:"";width:16px;height:16px;border-radius:50%;border:2px solid currentColor;border-right-color:transparent;animation:lgnSpin .7s linear infinite}
@keyframes lgnSpin{to{transform:rotate(360deg)}}
.lgn-secure{display:flex;align-items:center;gap:7px;justify-content:center;margin-top:14px;color:var(--muted);font-size:12.5px;text-align:center}
.lgn-hd{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;background:var(--brand-soft);color:var(--brand);margin-bottom:14px}
.lgn-steps{display:flex;gap:6px;margin-bottom:16px}
.lgn-steps i{height:4px;flex:1;border-radius:4px;background:var(--line-2)}
.lgn-steps i.on{background:var(--brand)}
.lgn-code{font:700 28px/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.5em;text-align:center;padding:14px 10px 14px 22px!important}
.lgn-back{margin-top:14px;text-align:center}
.lgn-swap{margin-top:16px;text-align:center;color:var(--muted);font-size:13.5px}
.lgn-rules{display:grid;gap:5px;margin:2px 0 16px;font-size:13px;color:var(--muted)}
.lgn-rules .ok{color:var(--ok)}
.lgn-rules div{display:flex;gap:7px;align-items:center}
@media (max-width:920px){.lgn{grid-template-columns:minmax(0,1fr)}.lgn-hero{display:none}.lgn-mini{display:flex}.lgn-main{padding-top:56px}}
@media (prefers-reduced-motion:reduce){.lgn *,.lgn *::before{animation:none!important;transition:none!important}}

/* ───── who is signed in: the account button in the menu ───── */
.acct{display:flex!important;align-items:center;gap:10px;padding:7px 8px!important;border-radius:12px!important}
.acct .who{min-width:0;display:grid;line-height:1.2;text-align:left}
.acct .who b{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.acct .who small{color:var(--muted);font-size:11.5px}
body.rail .acct .who{display:none}
.acctpop{padding:6px;display:grid;gap:2px;min-width:230px}
.acctpop .me{padding:8px 10px 10px;border-bottom:1px solid var(--line);margin-bottom:4px}
.acctpop .me b{display:block}
.acctpop .me small{color:var(--muted)}
.acctpop .mi{display:flex;align-items:center;gap:9px;width:100%;padding:8px 10px;border:0;background:none;border-radius:9px;text-align:left;color:var(--ink);text-decoration:none}
.acctpop .mi:hover{background:var(--sunken);text-decoration:none}
.pr-help{margin:10px 0;padding:12px 13px;border:1px dashed var(--line-2);border-radius:12px;background:var(--surface-2);display:grid;gap:7px;font-size:12.5px;color:var(--muted)}
.pr-help b{color:var(--ink);font-size:13px}
body.rail .pr-help{display:none}
.sa-back{white-space:nowrap}
.sa-view{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:650;background:var(--brand-soft);color:var(--brand);white-space:nowrap}

/* ───── the super admin page ───── */
.sa-orgs{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}
.sa-org .card-b{display:grid;gap:12px}
.sa-org .top{display:flex;align-items:center;gap:12px}
.sa-org .logo{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;font-weight:800;font-size:18px;background:var(--brand-soft);color:var(--brand);flex:none}
.sa-org .top b{display:block;font-size:16px}
.sa-who{display:flex;flex-wrap:wrap;gap:6px}
.sa-line{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 16px;border-bottom:1px solid var(--line)}
.sa-line:last-child{border-bottom:0}
.sa-line .t{min-width:0}
.sa-two{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:16px;align-items:start}
@media (max-width:900px){.sa-two{grid-template-columns:minmax(0,1fr)}}
.sa-pick{display:grid;gap:6px}
.sa-pick .opt{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:var(--surface);cursor:pointer;text-align:left;width:100%}
.sa-pick .opt:hover,.sa-pick .opt.on{border-color:var(--brand);background:var(--brand-soft)}
"""
