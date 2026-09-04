import streamlit as st
import pandas as pd
import sqlite3
import datetime
import re

st.set_page_config(page_title="Painel de Controle de Retrabalho Comercial", layout="wide")

DB_FILE = "retrabalho_historico.db"

# --- PERSISTÊNCIA DAS COBRANÇAS REALIZADAS ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS controle_envios (
            lead_key TEXT PRIMARY KEY,
            nome TEXT,
            celular TEXT,
            corretor_cobrado TEXT,
            tipo_lead TEXT,
            data_envio TEXT,
            total_cobrancas INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def registrar_lote_enviado(leads_para_gravar, corretor, tipo_lead):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    for l in leads_para_gravar:
        c.execute('''
            INSERT INTO controle_envios (lead_key, nome, celular, corretor_cobrado, tipo_lead, data_envio, total_cobrancas)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(lead_key) DO UPDATE SET
                corretor_cobrado = ?,
                data_envio = ?,
                tipo_lead = ?,
                total_cobrancas = total_cobrancas + 1
        ''', (l['lead_key'], l['nome'], l['celular'], corretor, tipo_lead, agora, corretor, agora, tipo_lead))
    conn.commit()
    conn.close()

def get_historico():
    conn = sqlite3.connect(DB_FILE)
    df_hist = pd.read_sql_query("SELECT lead_key, corretor_cobrado, data_envio as data_ultima_cobranca, total_cobrancas FROM controle_envios", conn)
    conn.close()
    return df_hist

# --- PROCESSAMENTO DO EXCEL DO CRM ---
def limpar_celular(val):
    if pd.isna(val):
        return ""
    digits = re.sub(r'\D', '', str(val))
    return digits[:-2] if digits.endswith('.0') else digits

def classificar_tipo(etapa):
    etapa_str = str(etapa).strip()
    if etapa_str in ['Em Tentativa', 'Lead na Base']:
        return "1. Aguardando 1ª Interação"
    elif etapa_str in ['Em Atendimento - Primeiras Informações', 'Em Atendimento - Aguardando Disponibilidade', 'Visita Agendada', 'Visita Realizada', 'Negócio Fechado.']:
        return "2. Em Atendimento"
    elif etapa_str in ['Perdido', 'Visita Cancelada', 'Visita - Cliente Não Compareceu']:
        return "3. Perdidos para Recuperação"
    return "Outros"

st.title("Gestão de Prazos & Cobrança de Corretores")

arquivo = st.sidebar.file_uploader("Subir relatório diário (.xlsx)", type=["xlsx"])

if arquivo:
    df_crm = pd.read_excel(arquivo, sheet_name=0)
    
    # Tratamento de dados
    df_crm['Celular_Limpo'] = df_crm['Celular Cliente'].apply(limpar_celular)
    df_crm['Recebido_Str'] = df_crm['Recebido em'].astype(str)
    df_crm['lead_key'] = df_crm['Celular_Limpo'] + "_" + df_crm['Recebido_Str']
    df_crm['Tipo_Lead'] = df_crm['Etapa do Funil'].apply(classificar_tipo)
    df_crm['Descrição Último Contato'] = df_crm['Descrição Último Contato'].fillna("Sem descrição registrada")

    # Cálculo dos dias sem interação
    hoje = datetime.datetime.now()
    def calcular_dias(row):
        data_ref = row.get('Último Contato em')
        if pd.isna(data_ref) or str(data_ref).strip() == "":
            data_ref = row.get('Recebido em')
        try:
            d = pd.to_datetime(data_ref, format="%d/%m/%Y %H:%M")
            return max(0, (hoje - d).days)
        except:
            return 0
            
    df_crm['Dias_Sem_Interacao'] = df_crm.apply(calcular_dias, axis=1)

    def faixa_dias(dias):
        if dias <= 3:
            return "0 a 3 dias"
        elif dias <= 10:
            return "3 a 10 dias"
        else:
            return "Mais de 10 dias"

    df_crm['Faixa_Atraso'] = df_crm['Dias_Sem_Interacao'].apply(faixa_dias)

    # Cruzamento com histórico de envios locais
    df_hist = get_historico()
    if not df_hist.empty:
        df = df_crm.merge(df_hist, on='lead_key', how='left')
    else:
        df = df_crm.copy()
        df['data_ultima_cobranca'] = None
        df['total_cobrancas'] = 0

    df['Status_Cobranca'] = df['data_ultima_cobranca'].apply(lambda x: "Já Cobrado/Passado" if pd.notna(x) else "Nunca Cobrado")

    # --- BARRA LATERAL: FILTRO GERAL POR CORRETOR ---
    st.sidebar.markdown("### Seleção Operacional")
    corretores_disponiveis = sorted([c for c in df['Corretor'].dropna().unique() if str(c).strip() != ""])
    corretor_selecionado = st.sidebar.selectbox("Escolha o Corretor:", corretores_disponiveis)

    # Abas operacionais por tipo de lead
    aba1, aba2, aba3 = st.tabs([
        "1. Aguardando 1ª Interação", 
        "2. Em Atendimento", 
        "3. Perdidos para Redistribuição"
    ])

    def renderizar_painel_operacional(df_tipo, nome_tipo, permitir_troca_corretor=False):
        # Filtra pelo corretor selecionado
        if not permitir_troca_corretor:
            dados = df_tipo[df_tipo['Corretor'] == corretor_selecionado].copy()
            st.markdown(f"### Leads de **{corretor_selecionado}** — {nome_tipo}")
        else:
            dados = df_tipo.copy()
            st.markdown(f"### Carteira de **Perdidos** (Para você repassar para o WhatsApp de qualquer corretor)")

        # Métricas de topo por faixa de dias
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("0 a 3 dias", len(dados[dados['Faixa_Atraso'] == "0 a 3 dias"]))
        c2.metric("3 a 10 dias", len(dados[dados['Faixa_Atraso'] == "3 a 10 dias"]))
        c3.metric("Mais de 10 dias", len(dados[dados['Faixa_Atraso'] == "Mais de 10 dias"]))
        c4.metric("Já Cobrados pelo App", len(dados[dados['Status_Cobranca'] == "Já Cobrado/Passado"]))

        # Filtros de trabalho
        col_filtro1, col_filtro2 = st.columns(2)
        with col_filtro1:
            filtro_faixa = st.multiselect(
                "Filtrar Faixa de Dias:", 
                ["0 a 3 dias", "3 a 10 dias", "Mais de 10 dias"],
                default=["3 a 10 dias", "Mais de 10 dias"],
                key=f"faixa_{nome_tipo}"
            )
        with col_filtro2:
            filtro_cobranca = st.selectbox(
                "Filtrar por Histórico de Envio:", 
                ["Todos", "Apenas Nunca Cobrados", "Apenas Já Cobrados"],
                key=f"cob_{nome_tipo}"
            )

        dados_filtrados = dados[dados['Faixa_Atraso'].isin(filtro_faixa)]
        if filtro_cobranca == "Apenas Nunca Cobrados":
            dados_filtrados = dados_filtrados[dados_filtrados['Status_Cobranca'] == "Nunca Cobrado"]
        elif filtro_cobranca == "Apenas Já Cobrados":
            dados_filtrados = dados_filtrados[dados_filtrados['Status_Cobranca'] == "Já Cobrado/Passado"]

        st.markdown("---")

        if dados_filtrados.empty:
            st.info("Nenhum lead encontrado para os filtros selecionados.")
            return

        # Destinatário real da mensagem no WhatsApp
        corretor_destino = corretor_selecionado
        if permitir_troca_corretor:
            corretor_destino = st.selectbox("Para qual corretor você vai mandar esses contatos no WhatsApp?", corretores_disponiveis, key=f"dest_{nome_tipo}")

        # Geração do texto formatado para copiar direto para o WhatsApp do corretor
        st.markdown(f"#### Lista Formatada para Copiar (WhatsApp de {corretor_destino})")
        
        texto_whatsapp = f"*LISTA DE LEADS - {nome_tipo.upper()}*\n"
        texto_whatsapp += f"*Destinatário:* {corretor_destino}\n"
        texto_whatsapp += f"*Data:* {hoje.strftime('%d/%m/%Y')}\n\n"
        
        leads_para_gravar = []
        for _, r in dados_filtrados.iterrows():
            linha = f"• *{r['Nome Cliente']}* - Tel: {r['Celular_Limpo']} ({r['Faixa_Atraso']})\n  _Último contato:_ {r['Descrição Último Contato']}\n"
            texto_whatsapp += linha
            leads_para_gravar.append({
                'lead_key': r['lead_key'],
                'nome': r['Nome Cliente'],
                'celular': r['Celular_Limpo']
            })

        st.text_area("Copie o texto abaixo e cole no WhatsApp do corretor:", value=texto_whatsapp, height=200, key=f"txt_{nome_tipo}")

        # Botão que efetiva o registro no banco
        if st.button(f"Registrar Envio / Marcar como Passado para {corretor_destino}", key=f"btn_{nome_tipo}"):
            registrar_lote_enviado(leads_para_gravar, corretor_destino, nome_tipo)
            st.success(f"Sucesso! {len(leads_para_gravar)} leads registrados como enviados para {corretor_destino}. O app já atualizou o status.")
            st.rerun()

        # Tabela detalhada de conferência com a Descrição do Último Contato
        st.markdown("#### Detalhamento dos Leads")
        colunas_tabela = [
            'Nome Cliente', 'Celular_Limpo', 'Faixa_Atraso', 'Dias_Sem_Interacao', 
            'Descrição Último Contato', 'Último Contato em', 'Status_Cobranca', 'data_ultima_cobranca'
        ]
        st.dataframe(dados_filtrados[colunas_tabela], use_container_width=True)

    # --- EXECUÇÃO DAS TELAS ---
    with aba1:
        df_1 = df[df['Tipo_Lead'] == "1. Aguardando 1ª Interação"]
        renderizar_painel_operacional(df_1, "Aguardando 1ª Interação", permitir_troca_corretor=False)

    with aba2:
        df_2 = df[df['Tipo_Lead'] == "2. Em Atendimento"]
        renderizar_painel_operacional(df_2, "Em Atendimento", permitir_troca_corretor=False)

    with aba3:
        df_3 = df[df['Tipo_Lead'] == "3. Perdidos para Recuperação"]
        renderizar_painel_operacional(df_3, "Perdidos para Redistribuição", permitir_troca_corretor=True)

else:
    st.info("Faça o upload do relatório do CRM no menu à esquerda para iniciar.")
