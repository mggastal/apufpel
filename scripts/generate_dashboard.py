#!/usr/bin/env python3
"""
Gera o dashboard HTML da Pesquisa de Satisfação - APUFPEL / Projeto Culinária Criativa.

Busca as respostas diretamente do Google Sheets (exportação CSV pública) e
renderiza um HTML autocontido. Layout: uma linha por pergunta do formulário,
com a pergunta condicional (se houver) ao lado da pergunta principal.
Pensado para rodar via GitHub Actions em um schedule, commitando o
docs/index.html atualizado.
"""

import base64
import html
import io
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SHEET_ID = os.environ.get("SHEET_ID") or "1CKoap-5nDXimxHe3qIAgX9NHiW9qEgtaAl9QdjFMFBI"
GID = os.environ.get("SHEET_GID") or "0"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&gid={GID}"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_PATH = os.path.join(REPO_ROOT, "docs", "index.html")
LOGO_PATH = os.path.join(REPO_ROOT, "assets", "logo.png")

# Colunas do formulário, na ordem em que aparecem no Google Forms.
COLS = [
    "timestamp",
    "avaliacao_geral",
    "motivo_avaliacao_baixa",
    "formato_adequado",
    "sugestao_formato",
    "receitas_uteis",
    "instrutor_dominio",
    "instrutor_melhorar",
    "organizacao",
    "organizacao_melhorar",
    "orientacoes_claras",
    "orientacoes_melhorar",
    "participaria_outros",
    "participaria_motivo",
    "nps_raw",
    "nps_motivo_baixo",
    "temas_desejados",
    "comentario_final",
]

PALETTE = {
    "navy": "#1E2470",
    "navy_dark": "#141A55",
    "gold": "#D9A441",
    "blue": "#3B4FD9",
    "light_blue": "#7B8AF0",
    "grey": "#9AA0C7",
    "red": "#D9534F",
    "green": "#4CAF6D",
}

AVALIACAO_ORDER = ["Excelente", "Bom", "Regular", "Ruim"]
AVALIACAO_COLORS = [PALETTE["green"], PALETTE["blue"], PALETTE["gold"], PALETTE["red"]]

FORMATO_ORDER = [
    "Sim, o tempo foi ideal.",
    "Foi suficiente, mas um pouco corrido.",
    "Não, precisaria de mais encontros.",
]
INSTRUTOR_ORDER = ["Sim, de forma clara e didática.", "Em partes.", "Não muito."]
ORIENTACOES_ORDER = ["Sim, totalmente claras.", "Parcialmente claras.", "Não foram claras."]
PARTICIPARIA_ORDER = ["Com certeza", "Talvez", "Não"]
TRI_COLORS = [PALETTE["green"], PALETTE["gold"], PALETTE["red"]]

# Estrutura do formulário: uma entrada por linha, na ordem exata das perguntas.
# type: "categorical" (distribuição em barras), "scale" (nota 0-10),
#       "tags" (nuvem de termos) ou "quotes" (respostas de texto livre, uma por linha).
QUESTIONS = [
    {
        "a_field": "avaliacao_geral", "a_type": "categorical", "a_order": AVALIACAO_ORDER, "a_colors": AVALIACAO_COLORS,
        "a_label": 'De forma geral, como você avalia o Workshop Especial Mão na Massa?',
        "b_field": "motivo_avaliacao_baixa", "b_type": "quotes",
        "b_label": 'Você respondeu "Regular" ou "Ruim": motivo da avaliação',
    },
    {
        "a_field": "formato_adequado", "a_type": "categorical", "a_order": FORMATO_ORDER, "a_colors": TRI_COLORS,
        "a_label": 'O formato de 4 encontros foi adequado para o aprendizado das receitas?',
        "b_field": "sugestao_formato", "b_type": "quotes",
        "b_label": 'Respondeu "corrido" ou "Não": sugestão sobre o formato',
    },
    {
        "a_field": "receitas_uteis", "a_type": "tags", "a_tag_class": "",
        "a_label": 'Quais receitas você considerou mais úteis ou gostou mais de aprender?',
        "b_field": None,
    },
    {
        "a_field": "instrutor_dominio", "a_type": "categorical", "a_order": INSTRUTOR_ORDER, "a_colors": TRI_COLORS,
        "a_label": 'O instrutor demonstrou domínio do conteúdo e explicou as técnicas de forma clara?',
        "b_field": "instrutor_melhorar", "b_type": "quotes",
        "b_label": 'Aspectos que poderiam ser melhorados no instrutor',
    },
    {
        "a_field": "organizacao", "a_type": "categorical", "a_order": AVALIACAO_ORDER, "a_colors": AVALIACAO_COLORS,
        "a_label": 'Como você avalia a organização do evento (horários, comunicação e espaço)?',
        "b_field": "organizacao_melhorar", "b_type": "quotes",
        "b_label": 'Respondeu "Regular" ou "Ruim": o que poderia ser melhorado',
    },
    {
        "a_field": "orientacoes_claras", "a_type": "categorical", "a_order": ORIENTACOES_ORDER, "a_colors": TRI_COLORS,
        "a_label": 'As orientações sobre materiais e ingredientes necessários foram claras?',
        "b_field": "orientacoes_melhorar", "b_type": "quotes",
        "b_label": 'O que poderia ser mais bem explicado',
    },
    {
        "a_field": "participaria_outros", "a_type": "categorical", "a_order": PARTICIPARIA_ORDER, "a_colors": TRI_COLORS,
        "a_label": 'Você participaria de outros workshops práticos organizados pela APUFPEL?',
        "b_field": "participaria_motivo", "b_type": "quotes",
        "b_label": 'Respondeu "Talvez" ou "Não": motivo',
    },
    {
        "a_field": "nps_raw", "a_type": "scale",
        "a_label": 'Em uma escala de 0 a 10, qual a probabilidade de recomendar este workshop?',
        "b_field": "nps_motivo_baixo", "b_type": "quotes",
        "b_label": 'Nota de 0 a 5: motivo',
    },
    {
        "a_field": "temas_desejados", "a_type": "tags", "a_tag_class": "tag-gold",
        "a_label": 'Quais temas você gostaria de ver nos próximos workshops?',
        "b_field": None,
    },
    {
        "a_field": "comentario_final", "a_type": "quotes",
        "a_label": 'Comentário, elogio ou sugestão para os próximos encontros',
        "b_field": None,
    },
]


def fetch_csv() -> pd.DataFrame:
    resp = requests.get(CSV_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    # Garante o número certo de colunas mesmo que o form ganhe/perca campos opcionais
    n = min(len(COLS), len(df.columns))
    df = df.iloc[:, :n]
    df.columns = COLS[:n]
    return df


def counter_ordered(series, order):
    c = Counter(series.dropna().astype(str).str.strip())
    return {label: c.get(label, 0) for label in order}


def top_terms(series, max_items=12):
    """Extrai temas/respostas curtas de um campo de texto livre e conta ocorrências."""
    c = Counter()
    for val in series.dropna():
        parts = re.split(r"[,;/\n]|(?:\se\s)", str(val))
        for p in parts:
            p = p.strip(" .")
            if p and len(p) > 1:
                c[p] += 1
    return c.most_common(max_items)


def extract_leading_int(value):
    if pd.isna(value):
        return None
    m = re.match(r"\s*(\d+)", str(value))
    return int(m.group(1)) if m else None


def quote_items(df, field):
    """Lista de respostas de texto livre (mais recentes primeiro), já em HTML escapado."""
    items = []
    for _, row in df.sort_values("timestamp", ascending=False).iterrows():
        texto = str(row.get(field, "")).strip()
        if texto and texto.lower() != "nan":
            data_fmt = ""
            try:
                data_fmt = pd.to_datetime(row["timestamp"]).strftime("%d/%m/%Y")
            except Exception:
                pass
            items.append({"texto": html.escape(texto), "data": data_fmt})
    return items


def pct(part, total):
    return round((part / total) * 100) if total else 0


def bar_group_html(dist, colors, total):
    rows = []
    for (label, count), color in zip(dist.items(), colors):
        rows.append(
            f'<div class="bar-row"><span class="bar-label">{html.escape(label)}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct(count,total)}%;background:{color}"></div></div>'
            f'<span class="bar-value">{count} ({pct(count,total)}%)</span></div>'
        )
    return "\n".join(rows) or '<div class="empty">Sem respostas ainda.</div>'


def scale_group_html(series, total):
    scores = [extract_leading_int(v) for v in series]
    scores = [s for s in scores if s is not None]
    dist = Counter(scores)
    rows = []
    for score in range(10, -1, -1):
        count = dist.get(score, 0)
        if count == 0:
            continue
        color = PALETTE["green"] if score >= 9 else (PALETTE["gold"] if score >= 7 else PALETTE["red"])
        rows.append(
            f'<div class="bar-row"><span class="bar-label">Nota {score}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct(count,total)}%;background:{color}"></div></div>'
            f'<span class="bar-value">{count} ({pct(count,total)}%)</span></div>'
        )
    return "\n".join(rows) or '<div class="empty">Sem respostas ainda.</div>'


def tags_html(series, css_class=""):
    terms = top_terms(series)
    cls = f"tag {css_class}".strip()
    return "".join(
        f'<span class="{cls}">{html.escape(t)} <b>{c}</b></span>' for t, c in terms
    ) or '<div class="empty">Sem respostas ainda.</div>'


def quotes_html(items):
    return "".join(
        f'<div class="quote"><p>&ldquo;{i["texto"]}&rdquo;</p><span class="quote-date">{i["data"]}</span></div>'
        for i in items
    ) or '<div class="empty">Sem respostas ainda.</div>'


def build_context(df: pd.DataFrame) -> dict:
    total = len(df)

    linhas = []
    for q in QUESTIONS:
        # Coluna A
        if q["a_type"] == "categorical":
            dist = counter_ordered(df[q["a_field"]], q["a_order"])
            a_html = bar_group_html(dist, q["a_colors"], total)
        elif q["a_type"] == "scale":
            a_html = scale_group_html(df[q["a_field"]], total)
        elif q["a_type"] == "tags":
            a_html = tags_html(df[q["a_field"]], q.get("a_tag_class", ""))
        elif q["a_type"] == "quotes":
            a_html = quotes_html(quote_items(df, q["a_field"]))
        else:
            a_html = ""

        # Coluna B (condicional, se existir)
        b_html = None
        if q.get("b_field"):
            b_html = quotes_html(quote_items(df, q["b_field"]))

        linhas.append({
            "a_label": q["a_label"],
            "a_html": a_html,
            "b_label": q.get("b_label"),
            "b_html": b_html,
        })

    ultima_resposta = ""
    try:
        ultima_resposta = pd.to_datetime(df["timestamp"]).max().strftime("%d/%m/%Y às %H:%M")
    except Exception:
        pass

    return {
        "total": total,
        "ultima_resposta": ultima_resposta,
        "linhas": linhas,
        "avaliacao_excelente_pct": pct(
            counter_ordered(df["avaliacao_geral"], AVALIACAO_ORDER).get("Excelente", 0), total
        ),
        "participaria_certeza_pct": pct(
            counter_ordered(df["participaria_outros"], PARTICIPARIA_ORDER).get("Com certeza", 0), total
        ),
        "gerado_em": (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%d/%m/%Y às %H:%M") + " (horário de Brasília)",
    }


def logo_data_uri() -> str:
    if not os.path.exists(LOGO_PATH):
        return ""
    with open(LOGO_PATH, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def render_html(ctx: dict) -> str:
    logo = logo_data_uri()
    total = ctx["total"]

    linhas_html = []
    for linha in ctx["linhas"]:
        if linha["b_label"]:
            linhas_html.append(f"""
  <div class="qrow">
    <div class="qcol">
      <h3>{html.escape(linha['a_label'])}</h3>
      {linha['a_html']}
    </div>
    <div class="qcol qcol-b">
      <h3>{html.escape(linha['b_label'])}</h3>
      {linha['b_html']}
    </div>
  </div>""")
        else:
            linhas_html.append(f"""
  <div class="qrow qrow-full">
    <div class="qcol qcol-full">
      <h3>{html.escape(linha['a_label'])}</h3>
      {linha['a_html']}
    </div>
  </div>""")
    linhas_html = "".join(linhas_html)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APUFPEL &middot; Pesquisa de Satisfação — Culinária Criativa</title>
<style>
:root {{
  --navy: {PALETTE['navy']};
  --navy-dark: {PALETTE['navy_dark']};
  --gold: {PALETTE['gold']};
  --blue: {PALETTE['blue']};
  --light-blue: {PALETTE['light_blue']};
  --grey: {PALETTE['grey']};
  --red: {PALETTE['red']};
  --green: {PALETTE['green']};
  --bg: #F4F5FB;
  --card: #FFFFFF;
  --text: #1B1E3D;
  --muted: #6A6F9A;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
}}
header {{
  background: linear-gradient(135deg, var(--navy) 0%, var(--navy-dark) 100%);
  color: #fff;
  padding: 0 32px 0 0;
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}}
header img {{ height: 76px; background: #fff; padding: 8px 14px; }}
header .title {{ padding: 28px 0; }}
header .title h1 {{ margin: 0; font-size: 22px; font-weight: 700; }}
header .title p {{ margin: 4px 0 0; color: #C7CBF5; font-size: 14px; }}
header .meta {{ margin-left: auto; text-align: right; font-size: 13px; color: #C7CBF5; padding: 28px 0; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 60px; }}
.grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px; }}
.stat-card {{
  background: var(--card); border-radius: 14px; padding: 18px 20px;
  box-shadow: 0 2px 10px rgba(30,36,112,0.06);
}}
.stat-card .label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
.stat-card .value {{ font-size: 30px; font-weight: 800; color: var(--navy); margin-top: 4px; }}
.stat-card .sub {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}

.qrow {{
  display: grid; grid-template-columns: 1fr 1fr; gap: 0;
  background: var(--card); border-radius: 16px; margin-bottom: 14px;
  box-shadow: 0 2px 10px rgba(30,36,112,0.06); overflow: hidden;
}}
.qcol {{ padding: 20px 24px; }}
.qcol-b {{ background: #F9FAFF; border-left: 1px solid #ECEEFA; }}
.qcol-full {{ }}
.qrow-full .qcol-full {{ }}
.qrow h3 {{ margin: 0 0 14px; font-size: 14px; color: var(--navy); font-weight: 700; line-height: 1.4; }}
.qcol-b h3 {{ color: var(--blue); }}

.bar-row {{ display: grid; grid-template-columns: 1fr 2fr 90px; align-items: center; gap: 10px; margin-bottom: 10px; }}
.bar-label {{ font-size: 13px; color: var(--text); }}
.bar-track {{ background: #EEF0FA; border-radius: 8px; height: 12px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 8px; }}
.bar-value {{ font-size: 12px; color: var(--muted); text-align: right; }}

.tag {{ display: inline-block; background: #EEF0FA; color: var(--navy); padding: 6px 12px; border-radius: 999px; font-size: 13px; margin: 0 8px 8px 0; }}
.tag b {{ color: var(--blue); margin-left: 4px; }}
.tag-gold {{ background: #FBF1DD; color: #7A5A12; }}
.tag-gold b {{ color: var(--gold); }}

.quote {{ border-left: 3px solid var(--light-blue); padding: 8px 12px; margin-bottom: 8px; background: #fff; border-radius: 0 8px 8px 0; }}
.qcol-b .quote {{ border-left-color: var(--gold); background: #FFFDF7; }}
.quote p {{ margin: 0 0 4px; font-size: 13px; line-height: 1.5; }}
.quote-date {{ font-size: 11px; color: var(--muted); }}

.empty {{ color: var(--muted); font-size: 13px; font-style: italic; }}
footer {{ text-align: center; padding: 20px; color: var(--muted); font-size: 12px; }}
@media (max-width: 800px) {{
  .grid {{ grid-template-columns: repeat(2, 1fr); }}
  .qrow {{ grid-template-columns: 1fr; }}
  .qcol-b {{ border-left: none; border-top: 1px solid #ECEEFA; }}
  header .meta {{ margin-left: 0; text-align: left; }}
}}
</style>
</head>
<body>
<header>
  {'<img src="' + logo + '" alt="APUFPEL">' if logo else ''}
  <div class="title">
    <h1>Pesquisa de Satisfação — Projeto Culinária Criativa</h1>
    <p>Workshop Especial Mão na Massa &middot; APUFPEL — A Associação das Gerações</p>
  </div>
  <div class="meta">
    Última resposta: {ctx['ultima_resposta'] or '—'}<br>
    Atualizado em {ctx['gerado_em']}
  </div>
</header>

<main>
  <div class="grid">
    <div class="stat-card">
      <div class="label">Respostas recebidas</div>
      <div class="value">{total}</div>
      <div class="sub">total de participantes</div>
    </div>
    <div class="stat-card">
      <div class="label">Avaliação geral excelente</div>
      <div class="value">{ctx['avaliacao_excelente_pct']}%</div>
      <div class="sub">responderam "Excelente"</div>
    </div>
    <div class="stat-card">
      <div class="label">Participariam de novo</div>
      <div class="value">{ctx['participaria_certeza_pct']}%</div>
      <div class="sub">responderam "Com certeza"</div>
    </div>
  </div>

  {linhas_html}
</main>

<footer>
  Dashboard gerado automaticamente a partir das respostas do Google Forms &middot; APUFPEL &middot; Projeto Culinária Criativa
</footer>
</body>
</html>
"""


def main():
    try:
        df = fetch_csv()
    except Exception as e:
        print(f"Erro ao buscar a planilha: {e}", file=sys.stderr)
        sys.exit(1)

    if df.empty:
        print("Planilha sem respostas ainda — gerando dashboard vazio.")

    ctx = build_context(df)
    html_out = render_html(ctx)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html_out)

    print(f"Dashboard gerado em {OUTPUT_PATH} com {ctx['total']} respostas.")


if __name__ == "__main__":
    main()
