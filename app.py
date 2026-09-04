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
        if motivo_perda.lower() == "tentativas de contato sem sucesso":
            return "3. Perdidos para Recuperação"
        else:
            return "Perdido (Outros Motivos)"
    return "Outros"

def preparar_dataframe(df_raw):
    df = df_raw.copy()
    df['Celular_Limpo'] = df['Celular Cliente'].apply(limpar_celular)
    df['Recebido_Str'] = df['Recebido em'].astype(str)
    df['lead_key'] = df['Celular_Limpo'] + "_" + df['Recebido_Str']
    df['Descrição Último Contato'] = df['Descrição Último Contato'].fillna("Sem descrição registrada")
    df['Motivo Perda'] = df['Motivo Perda'].fillna("Não informado")
    df['Tipo_Lead'] = df.apply(classificar_tipo, axis=1)
    
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
    df['Dias_Sem_Interacao'] = df.apply(calcular_dias, axis=1)

    def faixa_dias(dias):
        if dias <= 3:
            return "0 a 3 dias"
        elif dias <= 10:
            return "3 a 10 dias"
        else:
            return "Mais de 10 dias"
    df['Faixa_Atraso'] = df['Dias_Sem_Interacao'].apply(faixa_dias)
    return df

st.title("Gestão Comercial & Retrabalho de Leads")

st.sidebar.markdown("### Upload de Relatórios")
arquivo_atual = st.sidebar.file_uploader("1. Relatório Atual / Mais Recente (.xlsx)", type=["xlsx"])
arquivo_anterior = st.sidebar.file_uploader("2. Relatório Anterior (Opcional p/ Comparar)", type=["xlsx"])

if arquivo_atual:
    df_crm_atual = pd.read_excel(arquivo_atual, sheet_name=0)
    df = preparar_dataframe(df_crm_atual)

    df_hist = get_historico()
    if not df_hist.empty:
        df = df.merge(df_hist, on='lead_key', how='left')
    else:
        df['corretor_cobrado'] = None
        df['data_ultima_cobranca'] = None
        df['total_cobrancas'] = 0

    df['Status_Cobranca'] = df['data_ultima_cobranca'].apply(lambda x: "Já Cobrado/Passado" if pd.notna(x) else "Nunca Cobrado")
    corretores_disponiveis = sorted([c for c in df['Corretor'].dropna().unique() if str(c).strip() != ""])

    aba1, aba2, aba3, aba4 = st.tabs([
        "1. Aguardando 1ª Interação", 
        "2. Em Atendimento", 
        "3. Perdidos para Recuperação (Tentativas Sem Sucesso)",
        "4. Comparador de Evolução (Antes vs. Depois)"
    ])

    # --- ABAS 1 E 2 ---
    def renderizar_painel_corretor_fixo(df_tipo, chave_aba, titulo_aba):
        st.subheader(f"{titulo_aba} (Cobrança do Corretor Responsável)")
        corretores_com_leads = sorted([c for c in df_tipo['Corretor'].dropna().unique() if str(c).strip() != ""])
        if not corretores_com_leads:
            st.info("Nenhum lead encontrado nesta categoria.")
            return

        corretor_alvo = st.selectbox("Selecione o Corretor que será cobrado:", corretores_com_leads, key=f"sel_corretor_{chave_aba}")
        dados = df_tipo[df_tipo['Corretor'] == corretor_alvo].copy()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("0 a 3 dias", len(dados[dados['Faixa_Atraso'] == "0 a 3 dias"]))
        c2.metric("3 a 10 dias", len(dados[dados['Faixa_Atraso'] == "3 a 10 dias"]))
        c3.metric("Mais de 10 dias", len(dados[dados['Faixa_Atraso'] == "Mais de 10 dias"]))
        c4.metric("Já Cobrados", len(dados[dados['Status_Cobranca'] == "Já Cobrado/Passado"]))

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filtro_faixa = st.multiselect("Filtrar Faixa de Dias:", ["0 a 3 dias", "3 a 10 dias", "Mais de 10 dias"], default=["3 a 10 dias", "Mais de 10 dias"], key=f"faixa_{chave_aba}")
        with col_f2:
            filtro_cobranca = st.selectbox("Filtrar por Status de Envio:", ["Apenas Nunca Cobrados", "Todos", "Apenas Já Cobrados"], key=f"cob_{chave_aba}")

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

        tamanho_malote = st.number_input(f"Quantidade de leads para este malote (Disponíveis: {total_disponivel}):", min_value=1, max_value=total_disponivel, value=min(10, total_disponivel), step=1, key=f"num_{chave_aba}_{corretor_alvo}")
        malote_atual = dados_filtrados.head(int(tamanho_malote))

        hoje = datetime.datetime.now()
        texto_whatsapp = f"*LISTA DE LEADS - {titulo_aba.upper()}*\n*Destinatário:* {corretor_alvo}\n*Data:* {hoje.strftime('%d/%m/%Y')}\n\n"

        leads_para_gravar = []
        for _, r in malote_atual.iterrows():
            texto_whatsapp += f"• *{r['Nome Cliente']}* - {r['Celular_Limpo']}\n"
            leads_para_gravar.append({'lead_key': r['lead_key'], 'nome': r['Nome Cliente'], 'celular': r['Celular_Limpo'], 'corretor_orig': r['Corretor']})

        st.markdown(f"#### Copie a lista abaixo para enviar para **{corretor_alvo}**:")
        key_dinamica = f"txt_{chave_aba}_{corretor_alvo}_{len(malote_atual)}"
        st.text_area("Texto formatado:", value=texto_whatsapp, height=180, key=key_dinamica)

        if st.button(f"Registrar Envio do Malote para {corretor_alvo}", key=f"btn_{chave_aba}_{corretor_alvo}"):
            registrar_lote_enviado(leads_para_gravar, corretor_alvo, titulo_aba)
            st.success(f"Malote de {len(leads_para_gravar)} leads registrado como enviado para {corretor_alvo}!")
            st.rerun()

        st.markdown("#### Detalhamento dos Leads Deste Malote")
        st.dataframe(malote_atual[['Nome Cliente', 'Celular_Limpo', 'Faixa_Atraso', 'Dias_Sem_Interacao', 'Descrição Último Contato', 'Último Contato em', 'Status_Cobranca']], use_container_width=True)

    # --- ABA 3: PERDIDOS (COM TRAVA ANTIDUPLICIDADE ABSOLUTA) ---
    def renderizar_painel_perdidos(df_perdidos):
        st.subheader("Fila de Recuperação (Apenas: Tentativas de Contato Sem Sucesso)")
        st.caption("Leads arquivados sem resposta. Quando você redistribui um malote, esses leads saem da fila para evitar qualquer duplicidade.")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("0 a 3 dias", len(df_perdidos[df_perdidos['Faixa_Atraso'] == "0 a 3 dias"]))
        c2.metric("3 a 10 dias", len(df_perdidos[df_perdidos['Faixa_Atraso'] == "3 a 10 dias"]))
        c3.metric("Mais de 10 dias", len(df_perdidos[df_perdidos['Faixa_Atraso'] == "Mais de 10 dias"]))
        c4.metric("Já Redistribuídos (Histórico)", len(df_perdidos[df_perdidos['Status_Cobranca'] == "Já Cobrado/Passado"]))

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filtro_faixa = st.multiselect("Filtrar Faixa de Dias da Perda:", ["0 a 3 dias", "3 a 10 dias", "Mais de 10 dias"], default=["3 a 10 dias", "Mais de 10 dias"], key="faixa_perdidos")
        with col_f2:
            # TRAVA: Por padrão fica estritamente nos NUNCA REDISTRIBUÍDOS
            filtro_cobranca = st.selectbox("Visualização da Fila:", ["Apenas Pendentes (Nunca Redistribuídos)", "Já Redistribuídos (Para Consulta)", "Todos"], key="cob_perdidos")
        with col_f3:
            donos_originais = ["Todos os Corretores de Origem"] + sorted([c for c in df_perdidos['Corretor'].dropna().unique() if str(c).strip() != ""])
            filtro_dono_orig = st.selectbox("Filtrar por Corretor Original (Dono Anterior):", donos_originais, key="orig_perdidos")

        dados_base = df_perdidos[df_perdidos['Faixa_Atraso'].isin(filtro_faixa)].copy()
        
        # Aplicação rigorosa da trava
        if filtro_cobranca == "Apenas Pendentes (Nunca Redistribuídos)":
            dados_base = dados_base[dados_base['Status_Cobranca'] == "Nunca Cobrado"]
        elif filtro_cobranca == "Já Redistribuídos (Para Consulta)":
            dados_base = dados_base[dados_base['Status_Cobranca'] == "Já Cobrado/Passado"]

        if filtro_dono_orig != "Todos os Corretores de Origem":
            dados_base = dados_base[dados_base['Corretor'] == filtro_dono_orig]

        st.markdown("---")
        
        if filtro_cobranca == "Já Redistribuídos (Para Consulta)":
            st.info("Visualizando leads que já foram redistribuídos anteriormente. Use esta tela apenas para consulta e auditoria.")
            st.dataframe(dados_base[['Nome Cliente', 'Celular_Limpo', 'Corretor', 'corretor_cobrado', 'data_ultima_cobranca', 'Motivo Perda']], use_container_width=True)
            return

        st.markdown("#### Configuração da Redistribuição do Malote")
        
        # Regra 1: o corretor de origem filtrado não pode receber seus próprios leads
        if filtro_dono_orig != "Todos os Corretores de Origem":
            destinatarios_possiveis = [c for c in corretores_disponiveis if c != filtro_dono_orig]
        else:
            destinatarios_possiveis = corretores_disponiveis

        if not destinatarios_possiveis:
            st.warning("Não há corretores de destino disponíveis.")
            return

        col_m1, col_m2 = st.columns(2)
        with col_m1:
            novo_destinatario = st.selectbox("Para qual NOVO corretor você enviará esse malote?", destinatarios_possiveis, key="destinatario_novo_perdidos")

        # Regra 2: remove da lista qualquer lead cujo dono original seja o próprio novo_destinatario
        dados_filtrados = dados_base[dados_base['Corretor'] != novo_destinatario].copy()
        total_disponivel = len(dados_filtrados)

        with col_m2:
            if total_disponivel > 0:
                tamanho_malote = st.number_input(f"Quantidade no malote (Disponíveis: {total_disponivel}):", min_value=1, max_value=total_disponivel, value=min(10, total_disponivel), step=1, key=f"num_perdidos_{novo_destinatario}")
            else:
                st.write("**Disponíveis:** 0 leads livres")
                tamanho_malote = 0

        if total_disponivel == 0:
            st.warning(f"Sem novos leads disponíveis para redistribuir para **{novo_destinatario}** (todos os pendentes já foram enviados ou pertenciam a ele).")
            return

        malote_atual = dados_filtrados.head(int(tamanho_malote))

        hoje = datetime.datetime.now()
        texto_whatsapp = f"*LISTA DE LEADS - RECUPERAÇÃO (TENTATIVAS SEM SUCESSO)*\n*Destinatário:* {novo_destinatario}\n*Data:* {hoje.strftime('%d/%m/%Y')}\n\n"

        leads_para_gravar = []
        for _, r in malote_atual.iterrows():
            texto_whatsapp += f"• *{r['Nome Cliente']}* - {r['Celular_Limpo']}\n"
            leads_para_gravar.append({'lead_key': r['lead_key'], 'nome': r['Nome Cliente'], 'celular': r['Celular_Limpo'], 'corretor_orig': r['Corretor']})

        st.markdown(f"#### Copie a lista abaixo para enviar para **{novo_destinatario}**:")
        key_dinamica_perdidos = f"txt_perdidos_{novo_destinatario}_{len(malote_atual)}"
        st.text_area("Texto formatado:", value=texto_whatsapp, height=180, key=key_dinamica_perdidos)

        if st.button(f"Registrar Redistribuição do Malote para {novo_destinatario}", key=f"btn_perdidos_{novo_destinatario}"):
            registrar_lote_enviado(leads_para_gravar, novo_destinatario, "Perdidos Redistribuídos")
            st.success(f"Sucesso! {len(leads_para_gravar)} leads redistribuídos para {novo_destinatario} e REMOVIDOS da fila ativa.")
            st.rerun()

        st.markdown("#### Detalhes do Malote (Com Corretor Original)")
        df_exibicao = malote_atual.rename(columns={'Corretor': 'Corretor Original (Dono Anterior)'})
        st.dataframe(df_exibicao[['Nome Cliente', 'Celular_Limpo', 'Corretor Original (Dono Anterior)', 'Motivo Perda', 'Faixa_Atraso', 'Dias_Sem_Interacao', 'Descrição Último Contato']], use_container_width=True)

    with aba1:
        df_1 = df[df['Tipo_Lead'] == "1. Aguardando 1ª Interação"]
        renderizar_painel_corretor_fixo(df_1, "aba1", "Aguardando 1ª Interação")

    with aba2:
        df_2 = df[df['Tipo_Lead'] == "2. Em Atendimento"]
        renderizar_painel_corretor_fixo(df_2, "aba2", "Em Atendimento")

    with aba3:
        df_3 = df[df['Tipo_Lead'] == "3. Perdidos para Recuperação"]
        renderizar_painel_perdidos(df_3)

    # --- ABA 4: COMPARADOR ENTRE PLANILHAS ---
    with aba4:
        st.subheader("Análise Comparativa de Evolução da Equipe")
        with st.expander("ℹ️ GUIA RÁPIDO: O que significa cada status de evolução?", expanded=True):
            st.markdown("""
            Esta tela compara a planilha anterior com a atual cruzando o telefone e data do lead:
            
            * 🚀 **Avançou de Etapa (1ª Interação -> Atendimento):**  
              *O cliente respondeu!* O lead saiu do status de tentativa (*Em Tentativa / Lead na Base*) e foi para atendimento ativo (*Visita, Negociação, etc.*).
              
            * 📞 **Novo Contato Registrado:**  
              *O corretor trabalhou o lead!* A fase ainda não mudou, mas a data do `Último Contato em` foi atualizada no CRM com nova ligação ou mensagem.
              
            * 🎯 **Recuperado com Sucesso:**  
              *A redistribuição deu certo!* Lead que na planilha anterior estava arquivado como *Perdido* e agora foi resgatado para *Em Atendimento*.
              
            * ❌ **Marcado como Perdido:**  
              *Descarte de carteira.* O lead estava ativo na planilha anterior e foi finalizado como perdido no período analisado.
              
            * ⚠️ **Sem Alteração no CRM:**  
              *Lead estagnado.* Não houve alteração de fase e nenhuma nova data de contato foi registrada pelo corretor desde a última planilha. Ideal para cobrança.
            """)

        if not arquivo_anterior:
            st.info("Para comparar, suba o relatório anterior no campo **'2. Relatório Anterior'** na barra lateral.")
        else:
            df_crm_ant = pd.read_excel(arquivo_anterior, sheet_name=0)
            df_ant = preparar_dataframe(df_crm_ant)

            df_comp = df.merge(
                df_ant[['lead_key', 'Etapa do Funil', 'Último Contato em', 'Corretor']], 
                on='lead_key', 
                how='inner', 
                suffixes=('_atual', '_anterior')
            )

            def diagnosticar_evolucao(row):
                etapa_ant = str(row['Etapa do Funil_anterior']).strip()
                etapa_atu = str(row['Etapa do Funil_atual']).strip()
                contato_ant = str(row['Último Contato em_anterior']).strip()
                contato_atu = str(row['Último Contato em_atual']).strip()

                if etapa_ant in ['Em Tentativa', 'Lead na Base'] and etapa_atu not in ['Em Tentativa', 'Lead na Base', 'Perdido']:
                    return "Avançou de Etapa (1ª Interação -> Atendimento)"
                elif etapa_ant == 'Perdido' and etapa_atu != 'Perdido':
                    return "Recuperado com Sucesso"
                elif etapa_atu == 'Perdido' and etapa_ant != 'Perdido':
                    return "Marcado como Perdido"
                elif contato_atu != contato_ant and contato_atu != "":
                    return "Novo Contato Registrado"
                else:
                    return "Sem Alteração no CRM"

            df_comp['Status_Evolucao'] = df_comp.apply(diagnosticar_evolucao, axis=1)

            st.markdown("### Resumo Geral de Movimentação")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Avançaram de Etapa", len(df_comp[df_comp['Status_Evolucao'].str.contains("Avançou")]))
            m2.metric("Novos Contatos Realizados", len(df_comp[df_comp['Status_Evolucao'] == "Novo Contato Registrado"]))
            m3.metric("Leads Recuperados", len(df_comp[df_comp['Status_Evolucao'] == "Recuperado com Sucesso"]))
            m4.metric("Perdidos no Período", len(df_comp[df_comp['Status_Evolucao'] == "Marcado como Perdido"]))

            st.markdown("---")
            st.markdown("### Desempenho Consolidado por Corretor")
            resumo_corretores = df_comp.groupby(['Corretor_atual', 'Status_Evolucao']).size().unstack(fill_value=0)
            st.dataframe(resumo_corretores, use_container_width=True)

            st.markdown("### Filtrar e Auditar Leads")
            corretor_filtro_comp = st.selectbox("Selecione um Corretor para auditar:", ["Todos"] + corretores_disponiveis, key="filtro_comp_corretor")
            
            df_comp_exibir = df_comp if corretor_filtro_comp == "Todos" else df_comp[df_comp['Corretor_atual'] == corretor_filtro_comp]

            colunas_comp = [
                'Nome Cliente', 'Celular_Limpo', 'Corretor_atual', 'Status_Evolucao',
                'Etapa do Funil_anterior', 'Etapa do Funil_atual', 
                'Último Contato em_anterior', 'Último Contato em_atual'
            ]
            st.dataframe(df_comp_exibir[colunas_comp], use_container_width=True)
else:
    st.info("Faça o upload do relatório diário na barra lateral para iniciar.")
