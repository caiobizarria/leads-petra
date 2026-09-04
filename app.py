import streamlit as st
import pandas as pd
import sqlite3
import datetime
import re

st.set_page_config(page_title="Gestão de Retrabalho & Recuperação", layout="wide")

# --- BANCO DE DADOS LOCAL (PERSISTÊNCIA) ---
DB_FILE = "retrabalho_historico.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS retrabalhos (
            lead_key TEXT PRIMARY KEY,
            nome TEXT,
            celular TEXT,
            corretor_original TEXT,
            corretor_atual TEXT,
            ultima_data_envio TEXT,
            etapa_no_envio TEXT,
            total_envios INTEGER DEFAULT 0,
            status_reTrabalho TEXT,
            redistribuido_em TEXT,
            historico_notas TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def registrar_disparo(lead_key, nome, celular, corretor, etapa):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO retrabalhos (lead_key, nome, celular, corretor_original, corretor_atual, ultima_data_envio, etapa_no_envio, total_envios, status_reTrabalho)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'Enviado')
        ON CONFLICT(lead_key) DO UPDATE SET
            ultima_data_envio = ?,
            etapa_no_envio = ?,
            total_envios = total_envios + 1,
            corretor_atual = ?,
            status_reTrabalho = 'Enviado'
    ''', (lead_key, nome, celular, corretor, corretor, agora, etapa, agora, etapa, corretor))
    conn.commit()
    conn.close()

def registrar_redistribuicao(lead_key, nome, celular, corretor_orig, novo_corretor):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO retrabalhos (lead_key, nome, celular, corretor_original, corretor_atual, redistribuido_em, status_reTrabalho, total_envios)
        VALUES (?, ?, ?, ?, ?, ?, 'Redistribuído', 0)
        ON CONFLICT(lead_key) DO UPDATE SET
            corretor_atual = ?,
            redistribuido_em = ?,
            status_reTrabalho = 'Redistribuído'
    ''', (lead_key, nome, celular, corretor_orig, novo_corretor, agora, novo_corretor, agora))
    conn.commit()
    conn.close()

def get_historico():
    conn = sqlite3.connect(DB_FILE)
    df_hist = pd.read_sql_query("SELECT * FROM retrabalhos", conn)
    conn.close()
    return df_hist

# --- PROCESSAMENTO DO EXCEL ---
def limpar_celular(val):
    if pd.isna(val):
        return ""
    digits = re.sub(r'\D', '', str(val))
    return digits[:-2] if digits.endswith('.0') else digits

def categorizar_lead(etapa):
    etapa_str = str(etapa).strip()
    if etapa_str in ['Em Tentativa', 'Lead na Base']:
        return "1. Aguardando 1ª Interação"
    elif etapa_str in ['Em Atendimento - Primeiras Informações', 'Em Atendimento - Aguardando Disponibilidade', 'Visita Agendada', 'Visita Realizada', 'Negócio Fechado.']:
        return "2. Em Atendimento"
    elif etapa_str in ['Perdido', 'Visita Cancelada', 'Visita - Cliente Não Compareceu']:
        return "3. Perdido"
    return "Outros"

st.title("Sistema de Gestão de Retrabalho Comercial")

# Upload de arquivo
arquivo = st.sidebar.file_uploader("Subir relatório diário do CRM (.xlsx)", type=["xlsx"])

if arquivo:
    df_crm = pd.read_excel(arquivo, sheet_name=0)
    
    df_crm['Celular_Limpo'] = df_crm['Celular Cliente'].apply(limpar_celular)
    df_crm['Recebido_Str'] = df_crm['Recebido em'].astype(str)
    df_crm['Lead_Key'] = df_crm['Celular_Limpo'] + "_" + df_crm['Recebido_Str']
    df_crm['Categoria_Sistema'] = df_crm['Etapa do Funil'].apply(categorizar_lead)
    
    df_hist = get_historico()
    if not df_hist.empty:
        df = df_crm.merge(df_hist, left_on='Lead_Key', right_on='lead_key', how='left')
    else:
        df = df_crm.copy()
        df['ultima_data_envio'] = None
        df['total_envios'] = 0
        df['corretor_atual'] = None
        df['status_reTrabalho'] = "Nunca retrabalhado"

    df['total_envios'] = df['total_envios'].fillna(0).astype(int)
    df['Corretor_Efetivo'] = df['corretor_atual'].fillna(df['Corretor'])
    
    hoje = datetime.datetime.now()
    def calcular_dias(row):
        data_ref = row.get('Último Contato em')
        if pd.isna(data_ref) or str(data_ref).strip() == "":
            data_ref = row.get('Recebido em')
        try:
            d = pd.to_datetime(data_ref, format="%d/%m/%Y %H:%M")
            return (hoje - d).days
        except:
            return 0
    df['Dias_Sem_Interacao'] = df.apply(calcular_dias, axis=1)

    aba1, aba2, aba3 = st.tabs(["Aguardando 1ª Interação", "Em Atendimento", "Fila de Recuperação (Perdidos)"])

    # --- ABA 1: AGUARDANDO 1ª INTERAÇÃO ---
    with aba1:
        st.subheader("Leads Aguardando 1ª Interação (Cobrar Corretor)")
        df_aba1 = df[df['Categoria_Sistema'] == "1. Aguardando 1ª Interação"]
        
        corretores_aba1 = sorted(df_aba1['Corretor_Efetivo'].dropna().unique())
        corretor_sel1 = st.selectbox("Selecione o Corretor:", ["Todos"] + list(corretores_aba1), key="corretor_aba1")
        
        if corretor_sel1 != "Todos":
            df_aba1 = df_aba1[df_aba1['Corretor_Efetivo'] == corretor_sel1]
            
        col1, col2, col3 = st.columns(3)
        col1.metric("0 a 3 dias", len(df_aba1[df_aba1['Dias_Sem_Interacao'] <= 3]))
        col2.metric("3 a 10 dias", len(df_aba1[(df_aba1['Dias_Sem_Interacao'] > 3) & (df_aba1['Dias_Sem_Interacao'] <= 10)]))
        col3.metric("> 10 dias", len(df_aba1[df_aba1['Dias_Sem_Interacao'] > 10]))

        for idx, row in df_aba1.head(20).iterrows():
            with st.expander(f"{row['Nome Cliente']} | Tel: {row['Celular_Limpo']} | {row['Dias_Sem_Interacao']} dias sem retorno"):
                st.write(f"**Etapa:** {row['Etapa do Funil']} | **Último Envio:** {row['ultima_data_envio'] or 'Nunca'}")
                msg = f"Olá {row['Nome Cliente']}, tudo bem? Vi seu contato sobre o empreendimento e gostaria de saber se conseguiu analisar as informações."
                st.text_area("Texto WhatsApp:", value=msg, height=70, key=f"txt_1_{row['Lead_Key']}")
                if st.button("Registrar como Enviado", key=f"btn_1_{row['Lead_Key']}"):
                    registrar_disparo(row['Lead_Key'], row['Nome Cliente'], row['Celular_Limpo'], row['Corretor_Efetivo'], row['Etapa do Funil'])
                    st.success("Disparo registrado! Recarregue a página.")

    # --- ABA 2: EM ATENDIMENTO ---
    with aba2:
        st.subheader("Leads Em Atendimento (Acompanhar Evolução)")
        df_aba2 = df[df['Categoria_Sistema'] == "2. Em Atendimento"]
        
        corretores_aba2 = sorted(df_aba2['Corretor_Efetivo'].dropna().unique())
        corretor_sel2 = st.selectbox("Selecione o Corretor:", ["Todos"] + list(corretores_aba2), key="corretor_aba2")
        
        if corretor_sel2 != "Todos":
            df_aba2 = df_aba2[df_aba2['Corretor_Efetivo'] == corretor_sel2]

        st.dataframe(df_aba2[['Nome Cliente', 'Celular_Limpo', 'Etapa do Funil', 'Dias_Sem_Interacao', 'Último Contato em', 'ultima_data_envio']], use_container_width=True)

    # --- ABA 3: PERDIDOS & REDISTRIBUIÇÃO ---
    with aba3:
        st.subheader("Fila de Leads Perdidos para Recuperação")
        df_perdidos = df[df['Categoria_Sistema'] == "3. Perdido"].copy()
        st.write(f"Total de leads perdidos na base: **{len(df_perdidos)}**")
        
        selecionados = st.multiselect(
            "Selecione leads para redistribuir:",
            options=df_perdidos['Lead_Key'].tolist(),
            format_func=lambda x: f"{df_perdidos.loc[df_perdidos['Lead_Key'] == x, 'Nome Cliente'].values[0]} ({df_perdidos.loc[df_perdidos['Lead_Key'] == x, 'Motivo Perda'].values[0] or 'Sem motivo'})"
        )
        
        if selecionados:
            st.write(f"Leads selecionados: **{len(selecionados)}**")
            todos_corretores = sorted(df['Corretor'].dropna().unique())
            novos_corretores = st.multiselect("Corretores de destino (para rodízio):", options=todos_corretores)
            
            if novos_corretores and st.button("Confirmar e Redistribuir"):
                for i, l_key in enumerate(selecionados):
                    dest_corretor = novos_corretores[i % len(novos_corretores)]
                    lead_dados = df_perdidos[df_perdidos['Lead_Key'] == l_key].iloc[0]
                    registrar_redistribuicao(
                        lead_key=l_key,
                        nome=lead_dados['Nome Cliente'],
                        celular=lead_dados['Celular_Limpo'],
                        corretor_orig=lead_dados['Corretor'],
                        novo_corretor=dest_corretor
                    )
                st.success(f"{len(selecionados)} leads redistribuídos com sucesso entre {len(novos_corretores)} corretores!")
else:
    st.info("Aguardando upload da planilha na barra lateral para iniciar a análise.")
