"use strict";
const $app = document.getElementById("app");
let INDICE = null;
const cacheEmp = {};
const estado = { mercado: "todos", veredito: "todos", busca: "", ordem: "recentes", setor: "" };
let graficos = [];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtData = (iso) => { if (!iso) return "—"; const [y, m, d] = iso.split("-"); return `${d}/${m}/${y}`; };
const pct = (x, casas = 1) => (x == null || !isFinite(x)) ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(casas).replace(".", ",")}%`;
const pctSimples = (x) => (x == null || !isFinite(x)) ? "—" : `${(x * 100).toFixed(1).replace(".", ",")}%`;
const cls = (x) => x == null ? "" : (x > 0 ? "pos" : x < 0 ? "neg" : "");
const moedaSimb = (m) => (m === "USD" ? "US$" : "R$");

// valores vêm em milhares (R$ mil / US$ mil)
function dinheiro(v, moeda) {
  if (v == null || !isFinite(v)) return "—";
  const s = moedaSimb(moeda), a = Math.abs(v);
  const f = (n, d) => n.toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  if (a >= 1e6) return `${s} ${f(v / 1e6, 1)} bi`;
  if (a >= 1e3) return `${s} ${f(v / 1e3, 0)} mi`;
  return `${s} ${f(v, 0)} mil`;
}
const milhoes = (v) => (v == null || !isFinite(v)) ? "" : (v / 1000).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function badge(v) {
  const k = ["Bom", "Ruim", "Misto"].includes(v) ? v : "outro";
  return `<span class="badge v-${k}">${esc(v || "—")}</span>`;
}

async function carregarIndice() {
  if (INDICE) return INDICE;
  const r = await fetch("data/index.json", { cache: "no-store" });
  if (!r.ok) throw new Error("Dados ainda não gerados");
  INDICE = await r.json();
  document.getElementById("atualizado").textContent = `Atualizado em ${fmtData(INDICE.atualizado_em.slice(0, 10))} às ${INDICE.atualizado_em.slice(11)}`;
  return INDICE;
}
async function carregarEmpresa(id) {
  if (cacheEmp[id]) return cacheEmp[id];
  const r = await fetch(`data/empresas/${encodeURIComponent(id)}.json`, { cache: "no-store" });
  if (!r.ok) throw new Error("Empresa não encontrada");
  return (cacheEmp[id] = await r.json());
}

function marcarAba(aba) {
  document.querySelectorAll(".abas a").forEach((a) => a.classList.toggle("ativa", a.dataset.aba === aba));
}

async function rota() {
  graficos.forEach((g) => g.destroy()); graficos = [];
  const h = location.hash.replace(/^#\/?/, "");
  try {
    await carregarIndice();
    if (h.startsWith("empresa/")) { marcarAba(""); await telaEmpresa(decodeURIComponent(h.slice(8))); }
    else if (h === "calendario") { marcarAba("calendario"); telaCalendario(); }
    else { marcarAba("inicio"); telaInicio(); }
  } catch (e) {
    $app.innerHTML = `<div class="vazio">${esc(e.message)}. Se o portal acabou de ser criado, aguarde a primeira atualização terminar.</div>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", rota);
document.addEventListener("DOMContentLoaded", rota);

// ------------------------------------------------------------------ início
function filtrar(lista) {
  const b = estado.busca.trim().toLowerCase();
  let l = lista.filter((e) =>
    (estado.mercado === "todos" || e.mercado === estado.mercado) &&
    (estado.veredito === "todos" || e.veredito === estado.veredito) &&
    (!estado.setor || e.setor === estado.setor) &&
    (!b || e.ticker.toLowerCase().includes(b) || (e.nome || "").toLowerCase().includes(b)));
  const by = {
    recentes: (a, c) => (c.divulgado_em || "").localeCompare(a.divulgado_em || ""),
    az: (a, c) => a.ticker.localeCompare(c.ticker),
    receita: (a, c) => (c.receita_yoy ?? -1e9) - (a.receita_yoy ?? -1e9),
    lucro: (a, c) => (c.lucro_yoy ?? -1e9) - (a.lucro_yoy ?? -1e9),
  }[estado.ordem];
  return l.sort(by);
}

function telaInicio() {
  const L = INDICE.empresas;
  const setores = [...new Set(L.filter((e) => estado.mercado === "todos" || e.mercado === estado.mercado).map((e) => e.setor).filter(Boolean))].sort();
  const cont = (v) => L.filter((e) => e.veredito === v).length;
  $app.innerHTML = `
    <h1>Resultados das empresas</h1>
    <p class="sub">${L.filter((e) => e.mercado === "B3").length} empresas mais negociadas da B3 e ${L.filter((e) => e.mercado === "BDR").length} BDRs ligadas a inteligência artificial. Último trimestre de cada uma disponível nas bases oficiais (a da CVM é atualizada semanalmente).</p>
    <div class="placar">
      <div><b class="pos">${cont("Bom")}</b><span>resultados bons</span></div>
      <div><b style="color:var(--misto)">${cont("Misto")}</b><span>resultados mistos</span></div>
      <div><b class="neg">${cont("Ruim")}</b><span>resultados ruins</span></div>
      <div><b>${L.filter((e) => e.divulgado_em && (Date.now() - new Date(e.divulgado_em)) / 864e5 <= 14).length}</b><span>divulgados nos últimos 14 dias</span></div>
    </div>
    <div class="filtros">
      <input id="busca" type="search" placeholder="Buscar ticker ou empresa…" value="${esc(estado.busca)}">
      <div class="chips" id="f-mercado">
        ${[["todos", "Todos"], ["B3", "B3"], ["BDR", "BDRs IA"]].map(([k, t]) => `<button data-v="${k}" class="${estado.mercado === k ? "on" : ""}">${t}</button>`).join("")}
      </div>
      <div class="chips" id="f-veredito">
        ${[["todos", "Todos"], ["Bom", "Bons"], ["Misto", "Mistos"], ["Ruim", "Ruins"]].map(([k, t]) => `<button data-v="${k}" class="${estado.veredito === k ? "on" : ""}">${t}</button>`).join("")}
      </div>
      <select id="f-setor"><option value="">Todos os setores</option>${setores.map((s) => `<option ${s === estado.setor ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
      <select id="f-ordem">
        ${[["recentes", "Mais recentes"], ["receita", "Maior alta da receita"], ["lucro", "Maior alta do lucro"], ["az", "Ticker A–Z"]].map(([k, t]) => `<option value="${k}" ${estado.ordem === k ? "selected" : ""}>${t}</option>`).join("")}
      </select>
    </div>
    <div id="grade" class="grade"></div>`;
  const desenhar = () => {
    const l = filtrar(L);
    document.getElementById("grade").innerHTML = l.length ? l.map(cartao).join("") : `<div class="vazio">Nenhuma empresa com esses filtros.</div>`;
  };
  desenhar();
  document.getElementById("busca").addEventListener("input", (e) => { estado.busca = e.target.value; desenhar(); });
  document.getElementById("f-setor").addEventListener("change", (e) => { estado.setor = e.target.value; desenhar(); });
  document.getElementById("f-ordem").addEventListener("change", (e) => { estado.ordem = e.target.value; desenhar(); });
  for (const [id, campo] of [["f-mercado", "mercado"], ["f-veredito", "veredito"]]) {
    document.getElementById(id).addEventListener("click", (e) => {
      const v = e.target.dataset.v; if (!v) return;
      estado[campo] = v; if (campo === "mercado") estado.setor = ""; telaInicio();
    });
  }
}

function lucroTexto(e) {
  if (e.lucro != null && e.lucro_ant != null && (e.lucro < 0) !== (e.lucro_ant < 0)) return e.lucro >= 0 ? "virou lucro" : "virou prejuízo";
  return pct(e.lucro_yoy);
}
function cartao(e) {
  const motivos = [...(e.positivos || []).map((t) => `<li class="pos">${esc(t)}</li>`), ...(e.negativos || []).map((t) => `<li class="neg">${esc(t)}</li>`)].slice(0, 3).join("");
  return `<a class="card" href="#/empresa/${encodeURIComponent(e.id)}">
    <div class="card-top">
      <div><div class="tk">${esc(e.ticker)}<span class="tag">${e.mercado === "BDR" ? "BDR" : "B3"}</span></div><div class="nm">${esc(e.nome)}</div></div>
      ${badge(e.veredito)}
    </div>
    <div class="card-nums">
      <div><small>${e.financeira ? "Receitas" : "Receita"} ${esc(e.periodo || "")}</small><span class="num">${dinheiro(e.receita, e.moeda)}</span> <span class="num ${cls(e.receita_yoy)}">${pct(e.receita_yoy)}</span></div>
      <div><small>Lucro líquido</small><span class="num">${dinheiro(e.lucro, e.moeda)}</span> <span class="num ${cls(e.lucro_yoy ?? (e.lucro >= 0 ? 1 : -1))}">${lucroTexto(e)}</span></div>
    </div>
    ${motivos ? `<ul class="card-why">${motivos}</ul>` : ""}
    <div class="card-foot"><span>Divulgado ${fmtData(e.divulgado_em)}</span><span>Próximo: ${e.proximo ? fmtData(e.proximo.data) : "—"}</span></div>
  </a>`;
}

// ------------------------------------------------------------------ calendário
function telaCalendario() {
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
  const isoHoje = hoje.toISOString().slice(0, 10);
  const L = INDICE.empresas.filter((e) => estado.mercado === "todos" || e.mercado === estado.mercado);
  const futuros = L.filter((e) => e.proximo && e.proximo.data >= isoHoje).sort((a, b) => a.proximo.data.localeCompare(b.proximo.data));
  const atrasados = L.filter((e) => e.proximo && e.proximo.data < isoHoje);
  const recentes = L.filter((e) => e.divulgado_em && (hoje - new Date(e.divulgado_em)) / 864e5 <= 21).sort((a, b) => b.divulgado_em.localeCompare(a.divulgado_em));
  const porDia = {};
  futuros.forEach((e) => (porDia[e.proximo.data] ||= []).push(e));
  const nomeDia = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
  const item = (e, extra) => `<a class="cal-item" href="#/empresa/${encodeURIComponent(e.id)}">
      <span class="tk">${esc(e.ticker)}</span>
      <span>${esc(e.nome)} <small>· ${esc(e.proximo?.periodo || "")}</small></span>
      <small>${extra}</small></a>`;
  $app.innerHTML = `
    <h1>Calendário de resultados</h1>
    <p class="sub">O que ainda vai sair. As datas são estimadas a partir de quando cada empresa divulgou o mesmo trimestre no ano passado (ou pelo prazo legal) e mudam quando a empresa confirma.</p>
    <div class="filtros"><div class="chips" id="f-mercado">
      ${[["todos", "Todos"], ["B3", "B3"], ["BDR", "BDRs IA"]].map(([k, t]) => `<button data-v="${k}" class="${estado.mercado === k ? "on" : ""}">${t}</button>`).join("")}
    </div></div>
    ${atrasados.length ? `<h2>Pode sair a qualquer momento (${atrasados.length})</h2>
      <p class="legenda">A data estimada já passou e o resultado ainda não está nos dados oficiais. Na B3, muitas vezes ele já saiu: a CVM publica a base de dados aberta uma vez por semana, então os números podem levar alguns dias para aparecer aqui.</p>
      <div class="cal-dia">${atrasados.map((e) => item(e, e.pendente ? `anunciado em ${fmtData(e.pendente)}, aguardando 10-Q` : `previsto ${fmtData(e.proximo.data)}`)).join("")}</div>` : ""}
    <h2>Próximas divulgações</h2>
    ${Object.keys(porDia).length ? Object.entries(porDia).map(([d, l]) => `<div class="cal-dia"><h3>${nomeDia(d)} <span>${l.length} empresa${l.length > 1 ? "s" : ""}</span></h3>${l.map((e) => item(e, `${esc(e.proximo.tipo)} · estimado (${esc(e.proximo.base)})`)).join("")}</div>`).join("") : `<div class="vazio">Nenhuma divulgação prevista.</div>`}
    <h2>Divulgados nas últimas 3 semanas</h2>
    ${recentes.length ? `<div class="cal-dia">${recentes.map((e) => `<a class="cal-item" href="#/empresa/${encodeURIComponent(e.id)}"><span class="tk">${esc(e.ticker)}</span><span>${esc(e.nome)} <small>· ${esc(e.periodo || "")}</small></span><small>${fmtData(e.divulgado_em)} ${badge(e.veredito)}</small></a>`).join("")}</div>` : `<div class="vazio">Nenhum resultado nas últimas 3 semanas.</div>`}`;
  document.getElementById("f-mercado").addEventListener("click", (e) => { const v = e.target.dataset.v; if (v) { estado.mercado = v; telaCalendario(); } });
}

// ------------------------------------------------------------------ empresa
const NOMES_DEM = { DRE: "Resultado (DRE)", BPA: "Balanço – Ativo", BPP: "Balanço – Passivo e PL", DFC: "Fluxo de caixa" };
const estEmp = { dem: "DRE", periodo: "trimestral" };

async function telaEmpresa(id) {
  $app.innerHTML = `<p class="carregando">Carregando ${esc(id)}…</p>`;
  const e = await carregarEmpresa(id);
  const n = e.trimestres.length;
  let i = n - 1;
  while (i > 0 && e.base.receita[i] == null && e.base.lucro[i] == null) i--;
  const a = i - 4;
  const g = (s, j) => (s && j >= 0 ? s[j] : null);
  const vv = (x, y) => (x == null || y == null || y === 0 ? null : (x - y) / Math.abs(y));
  const r = e.resumo || {}, ia = e.resumo_ia;
  const veredito = ia?.veredito || r.veredito;
  const kpi = (t, v, d, dTxt) => `<div class="kpi"><small>${t}</small><b class="num">${v}</b>${dTxt !== undefined ? `<em class="num ${cls(d)}">${dTxt}</em>` : ""}</div>`;
  const per = e.trimestres[i]?.l || "";

  const kpis = [
    kpi(e.financeira ? "Receitas" : "Receita", dinheiro(g(e.base.receita, i), e.moeda), vv(g(e.base.receita, i), g(e.base.receita, a)), `${pct(vv(g(e.base.receita, i), g(e.base.receita, a)))} no ano`),
    e.financeira ? "" : kpi("EBITDA", dinheiro(g(e.ind.ebitda, i), e.moeda), vv(g(e.ind.ebitda, i), g(e.ind.ebitda, a)), `${pct(vv(g(e.ind.ebitda, i), g(e.ind.ebitda, a)))} no ano`),
    kpi("Lucro líquido", dinheiro(g(e.base.lucro, i), e.moeda), vv(g(e.base.lucro, i), g(e.base.lucro, a)), `${pct(vv(g(e.base.lucro, i), g(e.base.lucro, a)))} no ano`),
    e.financeira ? "" : kpi("Margem EBITDA", pctSimples(g(e.ind.margem_ebitda, i))),
    kpi("Margem líquida", pctSimples(g(e.ind.margem_liquida, i))),
    kpi("ROE (12 meses)", pctSimples(g(e.ind.roe, i))),
    e.financeira ? "" : kpi("Dívida líq./EBITDA", g(e.ind.alavancagem, i) == null ? "—" : `${g(e.ind.alavancagem, i).toFixed(1).replace(".", ",")}x`),
    e.financeira ? "" : kpi("Fluxo de caixa livre", dinheiro(g(e.ind.fcl, i), e.moeda)),
  ].join("");

  const lista = (arr, c) => (arr || []).map((t) => `<li class="${c}">${esc(t)}</li>`).join("");
  $app.innerHTML = `
    <a class="voltar" href="#/">← Todos os resultados</a>
    <div class="emp-top">
      <div>
        <h1>${esc(e.ticker)} <span style="font-weight:500;color:var(--ink2)">${esc(e.nome)}</span> ${badge(veredito)}</h1>
        <div class="meta"><span>${esc(e.setor || "")}</span><span>${e.mercado === "BDR" ? `BDR de ${esc(e.ticker_eua)} (valores em US$)` : `B3 · ${esc(e.tickers.join(", "))}`}</span>
          <span>${esc(per)} divulgado em ${fmtData(e.divulgado_em)}</span>${e.link ? `<span><a href="${esc(e.link)}" target="_blank" rel="noopener">Documento oficial ↗</a></span>` : ""}</div>
      </div>
    </div>
    ${e.pendente ? `<div class="aviso">A empresa já anunciou um resultado novo em ${fmtData(e.pendente)}. Os números detalhados entram aqui assim que o relatório oficial (10-Q/10-K) for arquivado na SEC, normalmente em poucos dias.</div>` : ""}
    <div class="duas">
      <div class="painel">
        <h3>Resumo do ${esc(r.periodo || per)}: ${badge(veredito)}</h3>
        ${ia?.texto ? `<p class="ia">${esc(ia.texto)}</p>` : ""}
        ${r.positivos?.length ? `<div class="rotulo">O que foi bem</div><ul>${lista(r.positivos, "pos")}</ul>` : ""}
        ${r.negativos?.length ? `<div class="rotulo">O que foi mal</div><ul>${lista(r.negativos, "neg")}</ul>` : ""}
        ${r.neutros?.length ? `<div class="rotulo">Estável</div><ul>${lista(r.neutros, "")}</ul>` : ""}
      </div>
      <div class="painel">
        <h3>O que esperar</h3>
        ${ia?.esperar ? `<p class="ia">${esc(ia.esperar)}</p>` : `<ul>${lista(r.esperar, "")}</ul>`}
        <div class="rotulo">Próxima divulgação</div>
        <p style="margin:4px 0">${e.proximo ? `<b>${fmtData(e.proximo.data)}</b> · ${esc(e.proximo.periodo)} · ${esc(e.proximo.tipo)}<br><small style="color:var(--ink3)">Data estimada (${esc(e.proximo.base)})</small>` : "—"}</p>
      </div>
    </div>
    <div class="kpis">${kpis}</div>
    <div class="graficos">
      <div class="painel"><h3>${e.financeira ? "Receitas" : "Receita"} e lucro por trimestre (${moedaSimb(e.moeda)} milhões)</h3><canvas id="g1"></canvas></div>
      <div class="painel"><h3>${e.financeira ? "Margem líquida e ROE" : "Margens"}</h3><canvas id="g2"></canvas></div>
    </div>
    <h2>Demonstrações completas</h2>
    <div class="dem-ctrl">
      <div class="chips" id="f-dem">${Object.entries(NOMES_DEM).filter(([k]) => e.demonstracoes[k]?.trimestral?.length).map(([k, t]) => `<button data-v="${k}" class="${estEmp.dem === k ? "on" : ""}">${t}</button>`).join("")}</div>
      <div class="chips" id="f-per">${[["trimestral", "Trimestral"], ["anual", "Anual"]].map(([k, t]) => `<button data-v="${k}" class="${estEmp.periodo === k ? "on" : ""}">${t}</button>`).join("")}</div>
    </div>
    <div id="tabela"></div>
    <div class="unid">Valores em ${moedaSimb(e.moeda)} milhões. Fonte: ${esc(e.fonte)}. ${e.mercado === "B3" ? "Demonstrações consolidadas quando disponíveis; trimestres calculados a partir dos acumulados do ano quando necessário." : "4º trimestre calculado como ano fiscal menos os três primeiros trimestres. Trimestres rotulados pelo calendário."}</div>`;

  const desenharTabela = () => {
    if (!e.demonstracoes[estEmp.dem]?.trimestral?.length) estEmp.dem = "DRE";
    const d = e.demonstracoes[estEmp.dem]?.[estEmp.periodo] || [];
    const cols = estEmp.periodo === "anual" ? e.anos.map((x) => x.l) : e.trimestres.map((x) => x.l);
    const mostrar = estEmp.periodo === "anual" ? cols.map((_, j) => j) : cols.map((_, j) => j).slice(-8);
    document.getElementById("tabela").innerHTML = d.length && cols.length ? `<div class="tabela-wrap"><table>
      <thead><tr><th>${NOMES_DEM[estEmp.dem]}</th>${mostrar.map((j) => `<th>${esc(cols[j])}</th>`).join("")}</tr></thead>
      <tbody>${d.map((l) => `<tr class="nv${Math.min(l.nv, 2)}"><td style="padding-left:${10 + Math.max(0, l.nv - 1) * 14}px">${e.mercado === "B3" ? `<span class="cod">${esc(l.c)}</span>` : ""}${esc(l.n)}</td>${mostrar.map((j) => `<td class="num ${l.v[j] < 0 ? "neg" : ""}">${l.u === "USD/shares" ? (l.v[j] == null ? "" : l.v[j].toFixed(2).replace(".", ",")) : milhoes(l.v[j])}</td>`).join("")}</tr>`).join("")}</tbody>
    </table></div>` : `<div class="vazio">Sem dados para este período.</div>`;
  };
  desenharTabela();
  document.getElementById("f-dem").addEventListener("click", (ev) => { const v = ev.target.dataset.v; if (!v) return; estEmp.dem = v; document.querySelectorAll("#f-dem button").forEach((b) => b.classList.toggle("on", b.dataset.v === v)); desenharTabela(); });
  document.getElementById("f-per").addEventListener("click", (ev) => { const v = ev.target.dataset.v; if (!v) return; estEmp.periodo = v; document.querySelectorAll("#f-per button").forEach((b) => b.classList.toggle("on", b.dataset.v === v)); desenharTabela(); });

  desenharGraficos(e);
}

function desenharGraficos(e) {
  if (!window.Chart) { setTimeout(() => desenharGraficos(e), 200); return; }
  const css = getComputedStyle(document.documentElement);
  const cor = (v) => css.getPropertyValue(v).trim();
  Chart.defaults.color = cor("--ink2"); Chart.defaults.borderColor = cor("--line"); Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  const labels = e.trimestres.map((t) => t.l);
  const mi = (s) => (s || []).map((v) => (v == null ? null : v / 1000));
  const opt = (fmt) => ({ responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
    plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)}` } } },
    scales: { y: { ticks: { callback: fmt } }, x: { grid: { display: false } } } });
  const fmtMi = (v) => v == null ? "—" : v.toLocaleString("pt-BR", { maximumFractionDigits: 0 });
  const fmtPct = (v) => v == null ? "—" : `${(v * 100).toFixed(0)}%`;
  graficos.push(new Chart(document.getElementById("g1"), { type: "bar", data: { labels, datasets: [
    { label: e.financeira ? "Receitas" : "Receita", data: mi(e.base.receita), backgroundColor: cor("--accent"), borderRadius: 3 },
    { label: "Lucro líquido", data: mi(e.base.lucro), backgroundColor: cor("--bom"), borderRadius: 3 },
  ] }, options: opt(fmtMi) }));
  const ds = e.financeira
    ? [{ label: "Margem líquida", data: e.ind.margem_liquida, borderColor: cor("--accent") }, { label: "ROE 12m", data: e.ind.roe, borderColor: cor("--bom") }]
    : [{ label: "Margem bruta", data: e.ind.margem_bruta, borderColor: cor("--ink3") }, { label: "Margem EBITDA", data: e.ind.margem_ebitda, borderColor: cor("--accent") }, { label: "Margem líquida", data: e.ind.margem_liquida, borderColor: cor("--bom") }];
  ds.forEach((d) => { d.tension = 0.25; d.spanGaps = true; d.pointRadius = 2; d.backgroundColor = d.borderColor; });
  graficos.push(new Chart(document.getElementById("g2"), { type: "line", data: { labels, datasets: ds.filter((d) => d.data?.some((v) => v != null)) }, options: opt(fmtPct) }));
}
