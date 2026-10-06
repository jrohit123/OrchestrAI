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
