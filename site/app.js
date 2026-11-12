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

// ------------------------------------------------------------------ acesso com senha
// Os dados são publicados criptografados (AES-256-GCM). A chave vem da senha (PBKDF2-SHA256).
let CHAVE = null, CFG = null;
const SAL = "portal-balancos/thalesfmarin-art/v1";
const LS = "portal-chave";
const b64e = (u8) => btoa(String.fromCharCode(...u8));
const b64d = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const guardar = { get: (k) => { try { return sessionStorage.getItem(k) || localStorage.getItem(k); } catch { return null; } },
  set: (k, v, lembrar) => { try { (lembrar ? localStorage : sessionStorage).setItem(k, v); } catch {} },
  limpar: (k) => { try { sessionStorage.removeItem(k); localStorage.removeItem(k); } catch {} } };

async function derivar(senha) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(senha), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt: new TextEncoder().encode(SAL), iterations: CFG.iter, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, true, ["decrypt"]);
}
async function lerDados(caminho, chave = CHAVE) {
  const r = await fetch(`data/${caminho}.bin?v=${Date.now()}`, { cache: "no-store" });
  if (!r.ok) throw new Error(caminho === "index" ? "Dados ainda não gerados" : "Empresa não encontrada");
  const buf = new Uint8Array(await r.arrayBuffer());
  const txt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: buf.slice(0, 12) }, chave, buf.slice(12));
  return JSON.parse(new TextDecoder().decode(txt));
}
async function garantirAcesso() {
  if (CHAVE) return true;
  if (!CFG) CFG = await fetch(`data/chave.json?v=${Date.now()}`, { cache: "no-store" }).then((r) => r.json()).catch(() => null);
  if (!CFG || !CFG.configurado) {
    $app.innerHTML = `<div class="vazio">Portal protegido. A senha de acesso ainda não foi configurada.</div>`;
    return false;
  }
  const salva = guardar.get(LS);
  if (salva) {
    try {
      const k = await crypto.subtle.importKey("raw", b64d(salva), "AES-GCM", true, ["decrypt"]);
      INDICE = await lerDados("index", k); CHAVE = k; posLogin(); return true;
    } catch { guardar.limpar(LS); }
  }
  telaLogin();
  return false;
}
function telaLogin(erro) {
  document.querySelector(".abas").style.visibility = "hidden";
  $app.innerHTML = `<form class="login" id="login">
      <h1>Acesso restrito</h1>
      <p class="sub">Digite a senha para ver o portal.</p>
      <input type="password" id="senha" placeholder="Senha" autocomplete="current-password" autofocus required>
      <label class="lembrar"><input type="checkbox" id="lembrar" checked> Lembrar neste dispositivo</label>
      ${erro ? `<p class="neg">${esc(erro)}</p>` : ""}
      <button type="submit" id="entrar">Entrar</button>
    </form>`;
  document.getElementById("login").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = document.getElementById("entrar"); btn.disabled = true; btn.textContent = "Verificando…";
    try {
      const k = await derivar(document.getElementById("senha").value);
      INDICE = await lerDados("index", k); CHAVE = k;
      guardar.set(LS, b64e(new Uint8Array(await crypto.subtle.exportKey("raw", k))), document.getElementById("lembrar").checked);
      posLogin(); rota();
    } catch { telaLogin("Senha incorreta."); }
  });
}
function posLogin() {
  document.querySelector(".abas").style.visibility = "";
  document.getElementById("atualizado").innerHTML = `Atualizado em ${fmtData(INDICE.atualizado_em.slice(0, 10))} às ${INDICE.atualizado_em.slice(11)} · <a href="#" id="sair">Sair</a>`;
  document.getElementById("sair").addEventListener("click", (e) => { e.preventDefault(); guardar.limpar(LS); location.hash = ""; location.reload(); });
}

async function carregarIndice() {
  if (INDICE) return INDICE;
  INDICE = await lerDados("index");
  return INDICE;
}
async function carregarEmpresa(id) {
  if (cacheEmp[id]) return cacheEmp[id];
  return (cacheEmp[id] = await lerDados(`empresas/${encodeURIComponent(id)}`));
}

function marcarAba(aba) {
  document.querySelectorAll(".abas a").forEach((a) => a.classList.toggle("ativa", a.dataset.aba === aba));
}

async function rota() {
  graficos.forEach((g) => g.destroy()); graficos = [];
  const h = location.hash.replace(/^#\/?/, "");
  try {
    if (!(await garantirAcesso())) return;
    await carregarIndice();
    if (h.startsWith("empresa/")) { marcarAba(""); await telaEmpresa(decodeURIComponent(h.slice(8))); }
    else if (h === "calendario") { marcarAba("calendario"); telaCalendario(); }
    else if (h === "analise") { marcarAba("analise"); telaAnalise(); }
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
      <div><small>Lucro líquido contábil</small><span class="num">${dinheiro(e.lucro, e.moeda)}</span> <span class="num ${cls(e.lucro_yoy ?? (e.lucro >= 0 ? 1 : -1))}">${lucroTexto(e)}</span></div>
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
    kpi("Lucro líquido contábil", dinheiro(g(e.base.lucro, i), e.moeda), vv(g(e.base.lucro, i), g(e.base.lucro, a)), `${pct(vv(g(e.base.lucro, i), g(e.base.lucro, a)))} no ano`),
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
    ${painelFundamentos(e)}
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
    <div class="unid">Valores em ${moedaSimb(e.moeda)} milhões. Fonte: ${esc(e.fonte)}. ${e.mercado === "B3" ? "Demonstrações consolidadas quando disponíveis. O lucro mostrado é o contábil atribuído aos controladores; os números recorrentes ou ajustados que a imprensa destaca podem ser diferentes; trimestres calculados a partir dos acumulados do ano quando necessário." : "4º trimestre calculado como ano fiscal menos os três primeiros trimestres. Trimestres rotulados pelo calendário."}</div>`;

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

// ------------------------------------------------------------------ análise fundamentalista
// Cada indicador vira um percentil dentro do grupo (B3 não financeiras, B3 financeiras, BDRs).
// O percentil é "melhor que X% do grupo"; pilar = média dos percentis; nota = média ponderada dos pilares.
const PILARES = {
  valuation: { nome: "Valuation", m: [["pl", -1, "P/L"], ["ev_ebitda", -1, "EV/EBITDA"], ["pvp", -1, "P/VP"], ["fcf_yield", 1, "FCF yield"]] },
  qualidade: { nome: "Qualidade", m: [["roe", 1, "ROE"], ["margem_liquida", 1, "Margem líquida"], ["volatilidade_margem", -1, "Estabilidade da margem"]] },
  crescimento: { nome: "Crescimento", m: [["cresc_receita_1a", 1, "Receita em 12 meses"], ["cresc_lucro_1a", 1, "Lucro em 12 meses"], ["cresc_receita_2a", 1, "Receita em 2 anos (ao ano)"]] },
  saude: { nome: "Saúde financeira", m: [["div_ebitda", -1, "Dívida líquida/EBITDA"]] },
  dividendos: { nome: "Dividendos", m: [["dy", 1, "Dividend yield"]] },
};
const PESOS_PADRAO = { valuation: 30, qualidade: 25, crescimento: 20, saude: 15, dividendos: 10 };
const MULT = new Set(["pl", "ev_ebitda", "pvp", "div_ebitda"]);
let PESOS = (() => { try { return { ...PESOS_PADRAO, ...JSON.parse(localStorage.getItem("portal-pesos") || "{}") }; } catch { return { ...PESOS_PADRAO }; } })();
let NOTAS = null;
const fmtMetr = (k, v) => v == null ? "—" : k === "volatilidade_margem" ? `${(v * 100).toFixed(1).replace(".", ",")} p.p.` : MULT.has(k) ? `${v.toFixed(1).replace(".", ",")}x` : pctSimples(v);
const grupoDe = (e) => e.mercado === "BDR" ? "BDRs" : e.financeira ? "B3 – financeiras" : "B3 – demais setores";
const CLASSES = { "Atrativa": "Bom", "Neutra": "Misto", "Pouco atrativa": "Ruim" };
const badgeClasse = (c) => `<span class="badge v-${CLASSES[c] || "outro"}">${esc(c || "Sem dados")}</span>`;

function calcularNotas() {
  const L = INDICE.empresas.filter((e) => e.fund);
  const grupos = {};
  L.forEach((e) => (grupos[grupoDe(e)] ||= []).push(e));
  const out = {};
  for (const [g, lista] of Object.entries(grupos)) {
    const perc = {};
    lista.forEach((e) => (perc[e.id] = {}));
    for (const p of Object.values(PILARES)) for (const [k, dir] of p.m) {
      // P/L com prejuízo conta como o pior valuation do grupo
      const ajust = lista.map((e) => [e, k === "pl" && e.fund.lucro_negativo ? Infinity : e.fund[k]]).filter(([, v]) => v != null);
      if (ajust.length < 3) continue;
      for (const [e, v] of ajust) {
        let pior = 0, igual = 0;
        for (const [, w] of ajust) { if (dir > 0 ? w < v : w > v) pior++; else if (w === v) igual++; }
        perc[e.id][k] = Math.round(100 * (pior + (igual - 1) / 2) / (ajust.length - 1));
      }
    }
    for (const e of lista) {
      const pil = {};
      for (const [pk, p] of Object.entries(PILARES)) {
        const xs = p.m.map(([k]) => perc[e.id][k]).filter((x) => x != null);
        pil[pk] = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
      }
      let soma = 0, peso = 0;
      for (const [pk, v] of Object.entries(pil)) if (v != null && PESOS[pk] > 0) { soma += v * PESOS[pk]; peso += PESOS[pk]; }
      const usados = Object.values(pil).filter((v) => v != null).length;
      const nota = peso && usados >= 2 ? soma / peso : null;
      let classe = nota == null ? null : nota >= 60 ? "Atrativa" : nota >= 40 ? "Neutra" : "Pouco atrativa";
      const travas = [];
      if (e.fund.lucro_negativo) travas.push("prejuízo nos últimos 12 meses");
      if (e.fund.div_ebitda != null && e.fund.div_ebitda > 4) travas.push("dívida líquida acima de 4x o EBITDA");
      if (classe === "Atrativa" && travas.length) classe = "Neutra";
      const mot = [];
      for (const p of Object.values(PILARES)) for (const [k, , nome] of p.m) {
        const pc = perc[e.id][k];
        if (pc == null) continue;
        const v = k === "pl" && e.fund.lucro_negativo ? null : e.fund[k];
        const txt = k === "pl" && e.fund.lucro_negativo ? "P/L negativo (prejuízo)" : `${nome} de ${fmtMetr(k, v)}`;
        if (pc >= 75) mot.push({ pos: true, pc, t: `${txt}: melhor que ${pc}% do grupo` });
        if (pc <= 25) mot.push({ pos: false, pc, t: `${txt}: pior que ${100 - pc}% do grupo` });
      }
      out[e.id] = { nota, classe, pilares: pil, perc: perc[e.id], grupo: g, n: lista.length, travas,
        fortes: mot.filter((m) => m.pos).sort((a, b) => b.pc - a.pc).slice(0, 4).map((m) => m.t),
        fracos: mot.filter((m) => !m.pos).sort((a, b) => a.pc - b.pc).slice(0, 4).map((m) => m.t) };
    }
  }
  return out;
}
function notas() { return NOTAS || (NOTAS = calcularNotas()); }

const estAn = { mercado: "todos", classe: "todas", busca: "", ordem: "nota" };
function telaAnalise() {
  const N = notas();
  const L = INDICE.empresas.filter((e) => e.fund && (estAn.mercado === "todos" || e.mercado === estAn.mercado));
  const cont = (c) => L.filter((e) => N[e.id]?.classe === c).length;
  $app.innerHTML = `
    <h1>Análise fundamentalista</h1>
    <p class="sub">Cada empresa recebe uma nota de 0 a 100 comparando seus indicadores com os do próprio grupo (B3 – demais setores, B3 – financeiras e BDRs). <b>Classificação automática pelos critérios do modelo; não é recomendação de compra ou venda.</b></p>
    <div class="placar">
      <div><b class="pos">${cont("Atrativa")}</b><span>atrativas pelos critérios</span></div>
      <div><b style="color:var(--misto)">${cont("Neutra")}</b><span>neutras</span></div>
      <div><b class="neg">${cont("Pouco atrativa")}</b><span>pouco atrativas</span></div>
      <div><b>${L.length}</b><span>empresas analisadas</span></div>
    </div>
    <details class="painel pesos" ${localStorage.getItem("portal-pesos") ? "open" : ""}>
      <summary><b>Pesos dos critérios</b> <span class="meta">(ajuste ao seu estilo: valor, qualidade, crescimento, dividendos…)</span></summary>
      <div class="pesos-grade">${Object.entries(PILARES).map(([k, p]) => `
        <label>${p.nome} <b id="pv-${k}">${PESOS[k]}</b><input type="range" min="0" max="50" step="5" value="${PESOS[k]}" data-k="${k}"></label>`).join("")}
      </div>
      <button class="link" id="pesos-reset">Restaurar pesos padrão</button>
    </details>
    <div class="filtros">
      <input id="busca-an" type="search" placeholder="Buscar ticker ou empresa…" value="${esc(estAn.busca)}">
      <div class="chips" id="fa-mercado">${[["todos", "Todos"], ["B3", "B3"], ["BDR", "BDRs IA"]].map(([k, t]) => `<button data-v="${k}" class="${estAn.mercado === k ? "on" : ""}">${t}</button>`).join("")}</div>
      <div class="chips" id="fa-classe">${[["todas", "Todas"], ["Atrativa", "Atrativas"], ["Neutra", "Neutras"], ["Pouco atrativa", "Pouco atrativas"]].map(([k, t]) => `<button data-v="${k}" class="${estAn.classe === k ? "on" : ""}">${t}</button>`).join("")}</div>
    </div>
    <div id="tab-an"></div>
    <details class="painel metodo"><summary><b>Como a nota é calculada</b></summary>
      <ul>
        <li><b>Valuation:</b> P/L, EV/EBITDA, P/VP e FCF yield (geração de caixa livre ÷ valor de mercado). Quanto mais barata em relação ao grupo, maior a nota. Empresa com prejuízo fica com o pior P/L. O lucro usado é o contábil: baixas contábeis pontuais (impairments) podem distorcer o P/L.</li>
        <li><b>Qualidade:</b> ROE, margem líquida dos últimos 12 meses e estabilidade da margem nos últimos 8 trimestres.</li>
        <li><b>Crescimento:</b> receita e lucro dos últimos 12 meses contra os 12 meses anteriores, e crescimento anual da receita em 2 anos.</li>
        <li><b>Saúde financeira:</b> dívida líquida/EBITDA (não se aplica a bancos e seguradoras).</li>
        <li><b>Dividendos:</b> proventos efetivamente pagos em caixa nos últimos 12 meses (dividendos + JCP, pelo fluxo de caixa) ÷ valor de mercado. Inclui pagamentos extraordinários, então pode ficar acima do yield recorrente.</li>
        <li>Cada indicador vira um percentil dentro do grupo ("melhor que X% do grupo"). A nota é a média ponderada dos pilares. <b>Atrativa</b> ≥ 60, <b>Neutra</b> de 40 a 60, <b>Pouco atrativa</b> &lt; 40. Empresas com prejuízo em 12 meses ou dívida acima de 4x o EBITDA não passam de Neutra.</li>
        <li>Preços: fechamento oficial da B3 (BDRs: cotação da ação nos EUA). Balanços: CVM e SEC. Valor de mercado = ações em circulação × preço de cada classe.</li>
      </ul>
    </details>`;
  const pct0 = (v) => v == null ? `<span class="meta">—</span>` : `<span class="nota-mini" style="--p:${Math.round(v)}">${Math.round(v)}</span>`;
  const desenhar = () => {
    const b = estAn.busca.trim().toLowerCase();
    const l = L.filter((e) => (estAn.classe === "todas" || N[e.id]?.classe === estAn.classe) && (!b || e.ticker.toLowerCase().includes(b) || (e.nome || "").toLowerCase().includes(b)))
      .sort((a, c) => (N[c.id]?.nota ?? -1) - (N[a.id]?.nota ?? -1));
    document.getElementById("tab-an").innerHTML = l.length ? `<div class="tabela-wrap"><table class="tab-an">
      <thead><tr><th>Empresa</th><th>Classificação</th><th>Nota</th>${Object.values(PILARES).map((p) => `<th>${p.nome}</th>`).join("")}
        <th>P/L</th><th>EV/EBITDA</th><th>P/VP</th><th>DY</th><th>ROE</th><th>Dív./EBITDA</th><th>Receita 12m</th></tr></thead>
      <tbody>${l.map((e) => { const n = N[e.id] || {}, f = e.fund; return `<tr data-id="${esc(e.id)}">
        <td><b>${esc(e.ticker)}</b> <span class="meta">${esc(e.nome)}</span></td>
        <td>${badgeClasse(n.classe)}</td><td class="num"><b>${n.nota == null ? "—" : Math.round(n.nota)}</b></td>
        ${Object.keys(PILARES).map((k) => `<td>${pct0(n.pilares?.[k])}</td>`).join("")}
        <td class="num">${f.lucro_negativo ? `<span class="neg">neg.</span>` : fmtMetr("pl", f.pl)}</td><td class="num">${fmtMetr("ev_ebitda", f.ev_ebitda)}</td>
        <td class="num">${fmtMetr("pvp", f.pvp)}</td><td class="num">${fmtMetr("dy", f.dy)}</td><td class="num">${fmtMetr("roe", f.roe)}</td>
        <td class="num">${fmtMetr("div_ebitda", f.div_ebitda)}</td><td class="num ${cls(f.cresc_receita_1a)}">${pct(f.cresc_receita_1a)}</td></tr>`; }).join("")}</tbody>
    </table></div>` : `<div class="vazio">Nenhuma empresa com esses filtros.</div>`;
    document.querySelectorAll(".tab-an tbody tr").forEach((tr) => tr.addEventListener("click", () => { location.hash = `#/empresa/${encodeURIComponent(tr.dataset.id)}`; }));
  };
  desenhar();
  document.getElementById("busca-an").addEventListener("input", (e) => { estAn.busca = e.target.value; desenhar(); });
  document.getElementById("fa-mercado").addEventListener("click", (e) => { const v = e.target.dataset.v; if (v) { estAn.mercado = v; telaAnalise(); } });
  document.getElementById("fa-classe").addEventListener("click", (e) => { const v = e.target.dataset.v; if (v) { estAn.classe = v; telaAnalise(); } });
  document.querySelectorAll(".pesos input").forEach((inp) => {
    inp.addEventListener("input", () => { document.getElementById(`pv-${inp.dataset.k}`).textContent = inp.value; });
    inp.addEventListener("change", () => { PESOS[inp.dataset.k] = +inp.value; try { localStorage.setItem("portal-pesos", JSON.stringify(PESOS)); } catch {} NOTAS = null; telaAnalise(); });
  });
  document.getElementById("pesos-reset").addEventListener("click", (ev) => { ev.preventDefault(); PESOS = { ...PESOS_PADRAO }; try { localStorage.removeItem("portal-pesos"); } catch {} NOTAS = null; telaAnalise(); });
}

function painelFundamentos(e) {
  const item = INDICE.empresas.find((x) => x.id === e.id);
  const f = item?.fund, n = notas()[e.id];
  if (!f) return "";
  const barra = (k) => { const v = n?.pilares?.[k]; return `<div class="pilar"><span>${PILARES[k].nome}</span><div class="barra"><i style="width:${v == null ? 0 : Math.round(v)}%"></i></div><b class="num">${v == null ? "—" : Math.round(v)}</b></div>`; };
  const linha = (k, nome) => `<tr><td>${nome}</td><td class="num">${k === "pl" && f.lucro_negativo ? "negativo" : fmtMetr(k, f[k])}</td><td class="num meta">${n?.perc?.[k] == null ? "" : `melhor que ${n.perc[k]}%`}</td></tr>`;
  return `<h2>Análise fundamentalista</h2>
    <div class="duas">
      <div class="painel">
        <h3>${badgeClasse(n?.classe)} <span class="num" style="margin-left:6px">Nota ${n?.nota == null ? "—" : Math.round(n.nota)}/100</span></h3>
        <p class="meta" style="margin:0 0 10px">Comparada com ${n?.n || 0} empresas do grupo <b>${esc(n?.grupo || "")}</b>. Pesos ajustáveis na aba Análise. Não é recomendação de investimento.</p>
        ${Object.keys(PILARES).map(barra).join("")}
        ${n?.travas?.length ? `<p class="neg" style="margin:10px 0 0">Limitada a Neutra por: ${esc(n.travas.join(" e "))}.</p>` : ""}
        ${n?.fortes?.length ? `<div class="rotulo">Pontos fortes</div><ul>${n.fortes.map((t) => `<li class="pos">${esc(t)}</li>`).join("")}</ul>` : ""}
        ${n?.fracos?.length ? `<div class="rotulo">Pontos fracos</div><ul>${n.fracos.map((t) => `<li class="neg">${esc(t)}</li>`).join("")}</ul>` : ""}
      </div>
      <div class="painel">
        <h3>Indicadores (últimos 12 meses até ${esc(f.periodo)})</h3>
        <table class="ind-tab"><tbody>
          <tr><td>Preço (${esc(f.preco_ticker || "")}${f.preco_data ? `, ${fmtData(f.preco_data)}` : ""})</td><td class="num">${f.preco == null ? "—" : `${e.moeda === "USD" ? "US$" : "R$"} ${f.preco.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}</td><td></td></tr>
          <tr><td>Valor de mercado</td><td class="num">${dinheiro(f.valor_mercado, e.moeda)}</td><td></td></tr>
          ${linha("pl", "P/L")}${e.financeira ? "" : linha("ev_ebitda", "EV/EBITDA")}${linha("pvp", "P/VP")}${e.financeira ? "" : linha("fcf_yield", "FCF yield")}
          ${linha("dy", "Dividend yield")}${linha("roe", "ROE")}${linha("margem_liquida", "Margem líquida")}${linha("volatilidade_margem", "Oscilação da margem")}
          ${e.financeira ? "" : linha("div_ebitda", "Dívida líquida/EBITDA")}${linha("cresc_receita_1a", "Crescimento da receita (12m)")}${linha("cresc_lucro_1a", "Crescimento do lucro (12m)")}${linha("cresc_receita_2a", "Crescimento da receita (2 anos, ao ano)")}
        </tbody></table>
      </div>
    </div>`;
}
