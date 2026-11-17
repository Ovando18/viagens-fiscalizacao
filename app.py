"""Controle de Viagens – Agentes de Fiscalização do CREA-MS.

- Qualquer pessoa com o link visualiza e pesquisa.
- Para editar, é preciso a senha (guardada em st.secrets, nunca no código).
- Ao salvar, o app grava o CSV direto no GitHub (commit), então o dado
  fica versionado e todo mundo vê a atualização na hora.
"""
import base64
import hmac
import io

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Controle de Viagens – Fiscais CREA-MS", page_icon="🚗", layout="wide")

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
MAX_TENTATIVAS = 5

REPO = st.secrets["GITHUB_REPO"]
BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
PATH = st.secrets.get("DATA_PATH", "data/viagens_2026.csv")
API = f"https://api.github.com/repos/{REPO}/contents/{PATH}"
HEADERS = {
    "Authorization": f"Bearer {st.secrets['GITHUB_TOKEN']}",
    "Accept": "application/vnd.github+json",
}


# ---------- GitHub ----------
@st.cache_data(ttl=60, show_spinner="Carregando dados...")
def carregar():
    """Lê o CSV do GitHub. Retorna (DataFrame, sha do arquivo)."""
    r = requests.get(API, headers=HEADERS, params={"ref": BRANCH}, timeout=20)
    r.raise_for_status()
    j = r.json()
    texto = base64.b64decode(j["content"]).decode("utf-8")
    df = pd.read_csv(io.StringIO(texto), sep=";", dtype={m: "Int64" for m in MESES})
    return df, j["sha"]


def salvar(df, sha):
    """Faz commit do CSV no GitHub. Retorna (ok, mensagem)."""
    csv = df.to_csv(sep=";", index=False)
    corpo = {
        "message": "Atualiza controle de viagens (via app)",
        "content": base64.b64encode(csv.encode("utf-8")).decode(),
        "sha": sha,
        "branch": BRANCH,
    }
    r = requests.put(API, headers=HEADERS, json=corpo, timeout=20)
    if r.status_code in (200, 201):
        carregar.clear()
        return True, "Dados salvos no GitHub ✔"
    if r.status_code in (409, 422):
        return False, "Alguém salvou antes de você. Recarregue a página e refaça a alteração."
    return False, f"Erro do GitHub ({r.status_code}): {r.text[:200]}"


# ---------- Cálculo / exibição ----------
def com_totais(df):
    out = df.copy()
    out["TOTAL"] = out[MESES].sum(axis=1, skipna=True).astype("Int64")
    linha = {"FISCAL": "TOTAL GERAL", **{m: out[m].sum() for m in MESES}, "TOTAL": out["TOTAL"].sum()}
    return pd.concat([out, pd.DataFrame([linha]).astype({c: "Int64" for c in MESES + ["TOTAL"]})], ignore_index=True)


def mostrar(df):
    st.dataframe(
        df.style.format(na_rep="X", precision=0),
        hide_index=True, use_container_width=True, height=min(740, 38 * (len(df) + 1)),
    )


# ---------- Login ----------
def tela_login():
    st.session_state.setdefault("auth", False)
    st.session_state.setdefault("tentativas", 0)
    with st.sidebar:
        st.header("🔒 Edição")
        if st.session_state.auth:
            st.success("Modo de edição ativo")
            if st.button("Sair da edição"):
                st.session_state.auth = False
                st.rerun()
        elif st.session_state.tentativas >= MAX_TENTATIVAS:
            st.error("Muitas tentativas. Recarregue a página para tentar de novo.")
        else:
            with st.form("login"):
                senha = st.text_input("Senha de edição", type="password")
                if st.form_submit_button("Entrar"):
                    if hmac.compare_digest(senha, str(st.secrets["EDIT_PASSWORD"])):
                        st.session_state.auth = True
                        st.session_state.tentativas = 0
                        st.rerun()
                    st.session_state.tentativas += 1
                    st.error("Senha incorreta.")
    return st.session_state.auth


# ---------- Página ----------
st.title("🚗 Controle de Viagens – Agentes de Fiscalização")
st.caption("CREA-MS · Exercício 2026 · quantidade de viagens por mês. “X” = ainda não atuava (não entra na soma).")

try:
    df, sha = carregar()
except Exception as e:
    st.error(f"Não consegui ler os dados do GitHub: {e}")
    st.stop()

editando = tela_login()

if not editando:
    busca = st.text_input("🔎 Pesquisar agente", placeholder="Digite parte do nome...")
    base = df[df["FISCAL"].str.contains(busca.strip(), case=False, na=False)] if busca.strip() else df
    tabela = com_totais(base) if len(base) else None
    if tabela is None:
        st.info("Nenhum agente encontrado.")
    else:
        mostrar(tabela)
        st.download_button("⬇ Baixar CSV", com_totais(df).to_csv(sep=";", index=False).encode("utf-8-sig"),
                           "viagens_fiscais_2026.csv", "text/csv")
else:
    st.subheader("Editar lançamentos")
    st.caption("Deixe a célula vazia para “X”. Dá para adicionar agentes na última linha e remover selecionando a linha e apertando Delete.")
    editado = st.data_editor(
        df, num_rows="dynamic", hide_index=True, use_container_width=True, key="editor",
        column_config={
            "FISCAL": st.column_config.TextColumn("FISCAL", required=True),
            **{m: st.column_config.NumberColumn(m, min_value=0, step=1, format="%d") for m in MESES},
        },
    )
    if st.button("💾 Salvar no GitHub", type="primary"):
        editado = editado.copy()
        editado["FISCAL"] = editado["FISCAL"].astype(str).str.strip().str.upper()
        if (editado["FISCAL"] == "").any() or editado["FISCAL"].duplicated().any():
            st.error("Há nomes vazios ou repetidos. Corrija antes de salvar.")
        else:
            for m in MESES:
                editado[m] = pd.to_numeric(editado[m], errors="coerce").astype("Int64")
            ok, msg = salvar(editado, sha)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()
    st.markdown("**Prévia dos totais**")
    mostrar(com_totais(editado))
