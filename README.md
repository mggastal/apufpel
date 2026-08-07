# Dashboard — Pesquisa de Satisfação APUFPEL (Projeto Culinária Criativa)

Dashboard HTML autoatualizável, gerado a partir das respostas do Google Forms
(planilha do Google Sheets), publicado via GitHub Pages.

## Como funciona

1. Um GitHub Action roda `scripts/generate_dashboard.py` a cada 15 minutos
   (e também sempre que você fizer push na branch `main`).
2. O script baixa as respostas da planilha em formato CSV, agrega os dados
   e gera `docs/index.html` (HTML autocontido, com Chart.js e a logo
   embutidos — não depende de nenhum outro arquivo).
3. Se algo mudou, o Action commita o novo `docs/index.html` automaticamente.
4. O GitHub Pages serve a pasta `docs/` como o site do dashboard.

## Passo a passo para publicar

### 1. Criar o repositório
Suba esta pasta inteira (`apufpel-culinaria/`) para um repositório novo no
GitHub (público ou privado, tanto faz).

### 2. IMPORTANTE — liberar a leitura da planilha
O script busca os dados sem autenticação, via link público de exportação CSV.
Para isso funcionar, a planilha precisa estar com o compartilhamento em:

> **Compartilhar → Acesso geral → "Qualquer pessoa com o link" → Leitor**

Hoje ela está compartilhada só como "editor" para você — isso não é
suficiente para o GitHub Actions conseguir ler os dados. Ajuste essa
permissão antes de ativar o workflow (o conteúdo continua só leitura para
quem não tem o link, e ninguém consegue editar sem ser convidado).

### 3. Ativar o GitHub Pages
Nas configurações do repositório: **Settings → Pages → Build and
deployment → Source: Deploy from a branch → Branch: `main` / pasta `/docs`**.

### 4. (Opcional) Configurar o ID da planilha via variável
O script já vem com o ID da planilha (`1CKoap-5nDXimxHe3qIAgX9NHiW9qEgtaAl9QdjFMFBI`)
como padrão. Se um dia trocar de planilha, não precisa mexer no código:
em **Settings → Secrets and variables → Actions → Variables**, crie:
- `SHEET_ID`: o ID da nova planilha (o trecho entre `/d/` e `/edit` na URL)
- `SHEET_GID`: o gid da aba (0 = primeira aba, padrão)

### 5. Rodar pela primeira vez
Vá em **Actions → Atualizar dashboard APUFPEL → Run workflow** para gerar o
`docs/index.html` manualmente na primeira vez (não precisa esperar os 15 min).

## Estrutura

```
apufpel-culinaria/
├── .github/workflows/update-dashboard.yml   # roda o script periodicamente
├── assets/logo.png                          # logo da APUFPEL (embutida no HTML)
├── docs/index.html                          # dashboard gerado (não editar à mão)
└── scripts/
    ├── generate_dashboard.py
    └── requirements.txt
```

## Ajustar a frequência de atualização
No arquivo `.github/workflows/update-dashboard.yml`, altere o `cron`.
Exemplos: `*/30 * * * *` (a cada 30 min), `0 * * * *` (a cada hora).
GitHub Actions em repositórios gratuitos tem um limite prático — não vale a
pena rodar mais rápido que a cada 5 minutos.
