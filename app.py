import streamlit as st
import pandas as pd
import sqlite3
import datetime
import re

st.set_page_config(page_title="Gestão de Retrabalho Comercial", layout="wide")

DB_FILE = "retrabalho_historico.db"

# --- BANCO DE DADOS LOCAL ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS controle_envios (
            lead_key TEXT PRIMARY KEY,
            nome TEXT,
            celular TEXT,
            corretor_cobrado TEXT,
            corretor_original TEXT,
            tipo_lead TEXT,
            data_envio TEXT,
            total_cobrancas INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def registrar_lote_enviado(leads_para_gravar, corretor_destino, tipo_lead):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    for l in leads_para_gravar:
        c.execute('''
            INSERT INTO controle_envios (lead_key, nome, celular, corretor_cobrado, corretor_original, tipo_lead, data_envio, total_cobrancas)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(lead_key) DO UPDATE SET
                corretor_cobrado = ?,
                data_envio = ?,
                tipo_lead = ?,
                total_cobrancas = total_cobrancas + 1
        ''', (l['lead_key'], l['nome'], l['celular'], corretor_destino, l.get('corretor_orig', ''), tipo_lead, agora, corretor_destino, agora, tipo_lead))
    conn.commit()
    conn.close()

def get_historico():
    conn = sqlite3.connect(DB_FILE)
    df_hist = pd.read_sql_query("SELECT lead_key, corretor_cobrado, data_envio as data_ultima_cobranca, total_cobrancas FROM controle_envios", conn)
    conn.close()
    return df_hist

# --- PROCESSAMENTO DO EXCEL ---
def limpar_celular(val):
    if pd.isna(val):
        return ""
    digits = re.sub(r'\D', '', str(val))
    return digits[:-2] if digits.endswith('.0') else digits

def classificar_tipo(row):
    etapa_str = str(row.get('Etapa do Funil', '')).strip()
    motivo_perda = str(row.get('Motivo Perda', '')).strip()
    
    if etapa_str in ['Em Tentativa', 'Lead na Base']:
        return "1. Aguardando 1ª Interação"
    elif etapa_str in ['Em Atendimento - Primeiras Informações', 'Em Atendimento - Aguardando Disponibilidade', 'Visita Agendada', 'Visita Realizada', 'Negócio Fechado.']:
        return "2. Em Atendimento"
    elif etapa_str in ['Perdido', 'Visita Cancelada', 'Visita - Cliente Não Compareceu']:
        # Filtra apenas quem foi perdido por falta de resposta / sem sucesso no contato
        if motivo_perda.lower() == "tentativas de contato sem sucesso":
            return "3. Perdidos para Recuperação"
        else:
            return "Perdido (Outros Motivos)"
    return "Outros"

st.title("Gestão de Prazos & Cobrança de Corretores")

arquivo = st.sidebar.file_uploader("Subir relatório diário (.xlsx)", type=["xlsx"])

if arquivo:
    df_crm = pd.read_excel(arquivo, sheet_name=0)
    
    df_crm['Celular_Limpo'] = df_crm['Celular Cliente'].apply(limpar_celular)
    df_crm['Recebido_Str'] = df_crm['Recebido em'].astype(str)
    df_crm['lead_key'] = df_crm['Celular_Limpo'] + "_" + df_crm['Recebido_Str']
    df_crm['Descrição Último Contato'] = df_crm['Descrição Último Contato'].fillna("Sem descrição registrada")
    df_crm['Motivo Perda'] = df_crm['Motivo Perda'].fillna("Não informado")
    
    # Classificação com base no motivo da perda
    df_crm['Tipo_Lead'] = df_crm.apply(classificar_tipo, axis=1)

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

    # Histórico de envios locais
    df_hist = get_historico()
    if not df_hist.empty:
        df = df_crm.merge(df_hist, on='lead_key', how='left')
    else:
        df = df_crm.copy()
        df['corretor_cobrado'] = None
        df['data_ultima_cobranca'] = None
        df['total_cobrancas'] = 0

    df['Status_Cobranca'] = df['data_ultima_cobranca'].apply(lambda x: "Já Cobrado/Passado" if pd.notna(x) else "Nunca Cobrado")

    # Lista de todos os corretores ativos
    corretores_disponiveis = sorted([c for c in df['Corretor'].dropna().unique() if str(c).strip() != ""])

    aba1, aba2, aba3 = st.tabs([
        "1. Aguardando 1ª Interação", 
        "2. Em Atendimento", 
        "3. Perdidos para Recuperação (Tentativas Sem Sucesso)"
    ])

    # --- FUNÇÃO PARA ABAS 1 E 2 ---
    def renderizar_painel_corretor_fixo(df_tipo, chave_aba, titulo_aba):
        st.subheader(f"{titulo_aba} (Cobrança do Corretor Responsável)")
        
        corretores_com_leads = sorted([c for c in df_tipo['Corretor'].dropna().unique() if str(c).strip() != ""])
        if not corretores_com_leads:
            st.info("Nenhum lead encontrado nesta categoria.")
            return

        corretor_alvo = st.selectbox(
            "Selecione o Corretor que será cobrado:", 
            corretores_com_leads, 
            key=f"sel_corretor_{chave_aba}"
        )

        dados = df_tipo[df_tipo['Corretor'] == corretor_alvo].copy()

        # Métricas
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("0 a 3 dias", len(dados[dados['Faixa_Atraso'] == "0 a 3 dias"]))
        c2.metric("3 a 10 dias", len(dados[dados['Faixa_Atraso'] == "3 a 10 dias"]))
        c3.metric("Mais de 10 dias", len(dados[dados['Faixa_Atraso'] == "Mais de 10 dias"]))
        c4.metric("Já Cobrados", len(dados[dados['Status_Cobranca'] == "Já Cobrado/Passado"]))

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filtro_faixa = st.multiselect(
                "Filtrar Faixa de Dias:", 
                ["0 a 3 dias", "3 a 10 dias", "Mais de 10 dias"],
                default=["3 a 10 dias", "Mais de 10 dias"],
                key=f"faixa_{chave_aba}"
            )
        with col_f2:
            filtro_cobranca = st.selectbox(
                "Filtrar por Status de Envio:", 
                ["Apenas Nunca Cobrados", "Todos", "Apenas Já Cobrados"],
                key=f"cob_{chave_aba}"
            )

        dados_filtrados = dados[dados['Faixa_Atraso'].isin(filtro_faixa)]
        if filtro_cobranca == "Apenas Nunca Cobrados":
            dados_filtrados = dados_filtrados[dados_filtrados['Status_Cobranca'] == "Nunca Cobrado"]
        elif filtro_cobranca == "Apenas Já Cobrados":
            dados_filtrados = dados_filtrados[dados_filtrados['Status_Cobranca'] == "Já Cobrado/Passado"]

        st.markdown("---")

        total_disponivel = len(dados_filtrados)
        if total_disponivel == 0:
            st.info(f"Nenhum lead pendente para **{corretor_alvo}** nos filtros selecionados.")
            return

        tamanho_malote = st.number_input(
            f"Quantidade de leads para este malote (Disponíveis: {total_disponivel}):",
            min_value=1,
            max_value=total_disponivel,
            value=min(10, total_disponivel),
            step=1,
            key=f"num_{chave_aba}_{corretor_alvo}"
        )

        malote_atual = dados_filtrados.head(int(tamanho_malote))

        # Montagem do texto
        texto_whatsapp = f"*LISTA DE LEADS - {titulo_aba.upper()}*\n"
        texto_whatsapp += f"*Destinatário:* {corretor_alvo}\n"
        texto_whatsapp += f"*Data:* {hoje.strftime('%d/%m/%Y')}\n\n"

        leads_para_gravar = []
        for _, r in malote_atual.iterrows():
            texto_whatsapp += f"• *{r['Nome Cliente']}* - {r['Celular_Limpo']}\n"
            leads_para_gravar.append({
                'lead_key': r['lead_key'],
                'nome': r['Nome Cliente'],
                'celular': r['Celular_Limpo'],
                'corretor_orig': r['Corretor']
            })

        st.markdown(f"#### Copie a lista abaixo para enviar para **{corretor_alvo}**:")
        key_dinamica = f"txt_{chave_aba}_{corretor_alvo}_{len(malote_atual)}"
        st.text_area("Texto formatado:", value=texto_whatsapp, height=180, key=key_dinamica)

        if st.button(f"Registrar Envio do Malote para {corretor_alvo}", key=f"btn_{chave_aba}_{corretor_alvo}"):
            registrar_lote_enviado(leads_para_gravar, corretor_alvo, titulo_aba)
            st.success(f"Malote de {len(leads_para_gravar)} leads registrado como enviado para {corretor_alvo}!")
            st.rerun()

        st.markdown("#### Detalhamento dos Leads Deste Malote")
        colunas_tabela = [
            'Nome Cliente', 'Celular_Limpo', 'Faixa_Atraso', 'Dias_Sem_Interacao', 
            'Descrição Último Contato', 'Último Contato em', 'Status_Cobranca'
        ]
        st.dataframe(malote_atual[colunas_tabela], use_container_width=True)

    # --- FUNÇÃO PARA ABA 3: PERDIDOS (SOMENTE TENTATIVAS SEM SUCESSO) ---
    def renderizar_painel_perdidos(df_perdidos):
        st.subheader("Fila de Recuperação (Apenas: Tentativas de Contato Sem Sucesso)")
        st.caption("Leads que foram arquivados sem resposta do cliente e possuem maior potencial de conversão com um novo corretor.")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("0 a 3 dias", len(df_perdidos[df_perdidos['Faixa_Atraso'] == "0 a 3 dias"]))
        c2.metric("3 a 10 dias", len(df_perdidos[df_perdidos['Faixa_Atraso'] == "3 a 10 dias"]))
        c3.metric("Mais de 10 dias", len(df_perdidos[df_perdidos['Faixa_Atraso'] == "Mais de 10 dias"]))
        c4.metric("Já Redistribuídos", len(df_perdidos[df_perdidos['Status_Cobranca'] == "Já Cobrado/Passado"]))

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filtro_faixa = st.multiselect(
                "Filtrar Faixa de Dias da Perda:", 
                ["0 a 3 dias", "3 a 10 dias", "Mais de 10 dias"],
                default=["3 a 10 dias", "Mais de 10 dias"],
                key="faixa_perdidos"
            )
        with col_f2:
            filtro_cobranca = st.selectbox(
                "Filtrar Status de Redistribuição:", 
                ["Apenas Nunca Redistribuídos", "Todos", "Apenas Já Redistribuídos"],
                key="cob_perdidos"
            )
        with col_f3:
            donos_originais = ["Todos os Corretores de Origem"] + sorted([c for c in df_perdidos['Corretor'].dropna().unique() if str(c).strip() != ""])
            filtro_dono_orig = st.selectbox("Filtrar por Corretor Original (Dono do Lead):", donos_originais, key="orig_perdidos")

        dados_filtrados = df_perdidos[df_perdidos['Faixa_Atraso'].isin(filtro_faixa)]
        if filtro_cobranca == "Apenas Nunca Redistribuídos":
            dados_filtrados = dados_filtrados[dados_filtrados['Status_Cobranca'] == "Nunca Cobrado"]
        elif filtro_cobranca == "Apenas Já Redistribuídos":
            dados_filtrados = dados_filtrados[dados_filtrados['Status_Cobranca'] == "Já Cobrado/Passado"]

        if filtro_dono_orig != "Todos os Corretores de Origem":
            dados_filtrados = dados_filtrados[dados_filtrados['Corretor'] == filtro_dono_orig]

        st.markdown("---")

        total_disponivel = len(dados_filtrados)
        if total_disponivel == 0:
            st.info("Nenhum lead com 'Tentativas de contato sem sucesso' encontrado para os filtros selecionados.")
            return

        st.markdown("#### Configuração da Redistribuição do Malote")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            novo_destinatario = st.selectbox(
                "Para qual NOVO corretor você enviará esse malote?", 
                corretores_disponiveis, 
                key="destinatario_novo_perdidos"
            )
        with col_m2:
            tamanho_malote = st.number_input(
                f"Quantidade de leads neste malote (Disponíveis: {total_disponivel}):",
                min_value=1,
                max_value=total_disponivel,
                value=min(10, total_disponivel),
                step=1,
                key=f"num_perdidos_{novo_destinatario}"
            )

        malote_atual = dados_filtrados.head(int(tamanho_malote))

        # Texto do WhatsApp
        texto_whatsapp = f"*LISTA DE LEADS - RECUPERAÇÃO (TENTATIVAS SEM SUCESSO)*\n"
        texto_whatsapp += f"*Destinatário:* {novo_destinatario}\n"
        texto_whatsapp += f"*Data:* {hoje.strftime('%d/%m/%Y')}\n\n"

        leads_para_gravar = []
        for _, r in malote_atual.iterrows():
            texto_whatsapp += f"• *{r['Nome Cliente']}* - {r['Celular_Limpo']}\n"
            leads_para_gravar.append({
                'lead_key': r['lead_key'],
                'nome': r['Nome Cliente'],
                'celular': r['Celular_Limpo'],
                'corretor_orig': r['Corretor']
            })

        st.markdown(f"#### Copie a lista abaixo para enviar para **{novo_destinatario}**:")
        key_dinamica_perdidos = f"txt_perdidos_{novo_destinatario}_{len(malote_atual)}"
        st.text_area("Texto formatado:", value=texto_whatsapp, height=180, key=key_dinamica_perdidos)

        if st.button(f"Registrar Redistribuição do Malote para {novo_destinatario}", key=f"btn_perdidos_{novo_destinatario}"):
            registrar_lote_enviado(leads_para_gravar, novo_destinatario, "Perdidos Redistribuídos")
            st.success(f"Malote de {len(leads_para_gravar)} leads registrado como redistribuído para {novo_destinatario}!")
            st.rerun()

        st.markdown("#### Detalhes do Malote (Com Corretor Original)")
        df_exibicao = malote_atual.rename(columns={'Corretor': 'Corretor Original (Dono Anterior)'})
        colunas_tabela = [
            'Nome Cliente', 'Celular_Limpo', 'Corretor Original (Dono Anterior)', 
            'Motivo Perda', 'Faixa_Atraso', 'Dias_Sem_Interacao', 
            'Descrição Último Contato', 'Status_Cobranca'
        ]
        st.dataframe(df_exibicao[colunas_tabela], use_container_width=True)

    # --- EXECUÇÃO DAS ABAS ---
    with aba1:
        df_1 = df[df['Tipo_Lead'] == "1. Aguardando 1ª Interação"]
        renderizar_painel_corretor_fixo(df_1, "aba1", "Aguardando 1ª Interação")

    with aba2:
        df_2 = df[df['Tipo_Lead'] == "2. Em Atendimento"]
        renderizar_painel_corretor_fixo(df_2, "aba2", "Em Atendimento")

    with aba3:
        df_3 = df[df['Tipo_Lead'] == "3. Perdidos para Recuperação"]
        renderizar_painel_perdidos(df_3)

else:
    st.info("Faça o upload do relatório do CRM no menu à esquerda para iniciar.")
