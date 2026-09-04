import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sqlite3
import datetime
import re
import json

st.set_page_config(page_title="Gestão de Retrabalho Comercial", layout="wide")

DB_FILE = "retrabalho_historico.db"

# --- BANCO DE DADOS LOCAL (COM MIGRAÇÃO AUTOMÁTICA DE COLUNAS) ---
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
            etapa_ao_enviar TEXT,
            data_envio TEXT,
            total_cobrancas INTEGER DEFAULT 1
        )
    ''')
    
    # Migrações seguras: adiciona colunas caso a tabela tenha sido criada em versão anterior
    c.execute("PRAGMA table_info(controle_envios)")
    colunas_existentes = [col[1] for col in c.fetchall()]
    
    if "corretor_original" not in colunas_existentes:
        c.execute("ALTER TABLE controle_envios ADD COLUMN corretor_original TEXT")
    if "etapa_ao_enviar" not in colunas_existentes:
        c.execute("ALTER TABLE controle_envios ADD COLUMN etapa_ao_enviar TEXT")
        
    c.execute('''
        CREATE TABLE IF NOT EXISTS leads_bloqueados (
            celular TEXT PRIMARY KEY,
            nome TEXT,
            motivo_cancelamento TEXT,
            data_bloqueio TEXT
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
            INSERT INTO controle_envios (lead_key, nome, celular, corretor_cobrado, corretor_original, tipo_lead, etapa_ao_enviar, data_envio, total_cobrancas)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(lead_key) DO UPDATE SET
                corretor_cobrado = ?,
                data_envio = ?,
                tipo_lead = ?,
                etapa_ao_enviar = ?,
                total_cobrancas = total_cobrancas + 1
        ''', (l['lead_key'], l['nome'], l['celular'], corretor_destino, l.get('corretor_orig', ''), tipo_lead, l.get('etapa_atual', ''), agora, corretor_destino, agora, tipo_lead, l.get('etapa_atual', '')))
    conn.commit()
    conn.close()

def get_historico():
    conn = sqlite3.connect(DB_FILE)
    df_hist = pd.read_sql_query("SELECT lead_key, corretor_cobrado, corretor_original, tipo_lead as tipo_lead_envio, etapa_ao_enviar, data_envio as data_ultima_cobranca, total_cobrancas FROM controle_envios", conn)
    conn.close()
    return df_hist

def bloquear_lead_db(celular, nome, motivo):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    c.execute('''
        INSERT INTO leads_bloqueados (celular, nome, motivo_cancelamento, data_bloqueio)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(celular) DO UPDATE SET
            motivo_cancelamento = ?,
            data_bloqueio = ?
    ''', (celular, nome, motivo, agora, motivo, agora))
    conn.commit()
    conn.close()

def desbloquear_lead_db(celular):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM leads_bloqueados WHERE celular = ?", (celular,))
    conn.commit()
    conn.close()

def get_leads_bloqueados():
    conn = sqlite3.connect(DB_FILE)
    df_bloq = pd.read_sql_query("SELECT * FROM leads_bloqueados", conn)
    conn.close()
    return df_bloq

def render_botao_copiar(texto_para_copiar, rotulo="📋 Copiar Lista para o WhatsApp"):
    texto_escapado = json.dumps(texto_para_copiar)
    html_code = f"""
    <button id="btn_copiar" style="
        background-color: #25D366;
        color: white;
        border: none;
        padding: 10px 18px;
        font-size: 15px;
        font-weight: bold;
        border-radius: 8px;
        cursor: pointer;
        width: 100%;
        margin-top: 6px;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
    ">
        {rotulo}
    </button>
    <div id="status_copia" style="font-size: 13px; color: #155724; font-weight: 500; text-align: center; display: none;">
        ✅ Lista copiada com sucesso para sua área de transferência!
    </div>
    <script>
    document.getElementById("btn_copiar").addEventListener("click", function() {{
        const text = {texto_escapado};
        if (navigator.clipboard && window.isSecureContext) {{
            navigator.clipboard.writeText(text).then(() => {{
                mostrarSucesso();
            }}).catch(() => {{
                fallbackCopy(text);
            }});
        }} else {{
            fallbackCopy(text);
        }}
    }});

    function fallbackCopy(text) {{
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        textArea.style.left = "-999999px";
        textArea.style.top = "-999999px";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {{
            document.execCommand('copy');
            mostrarSucesso();
        }} catch (err) {{
            alert('Não foi possível copiar automaticamente. Use o ícone de cópia no bloco de texto.');
        }}
        document.body.removeChild(textArea);
    }}

    function mostrarSucesso() {{
        const status = document.getElementById("status_copia");
        status.style.display = "block";
        setTimeout(() => {{
            status.style.display = "none";
        }}, 3500);
    }}
    </script>
    """
    components.html(html_code, height=75)

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
        df['corretor_original'] = None
        df['tipo_lead_envio'] = None
        df['etapa_ao_enviar'] = None
        df['data_ultima_cobranca'] = None
        df['total_cobrancas'] = 0

    df['Status_Cobranca'] = df['data_ultima_cobranca'].apply(lambda x: "Já Cobrado/Passado" if pd.notna(x) else "Nunca Cobrado")
    
    df_bloqueados = get_leads_bloqueados()
    telefones_bloqueados = set(df_bloqueados['celular'].tolist()) if not df_bloqueados.empty else set()
    df['Lead_Bloqueado'] = df['Celular_Limpo'].isin(telefones_bloqueados)

    corretores_disponiveis = sorted([c for c in df['Corretor'].dropna().unique() if str(c).strip() != ""])

    aba1, aba2, aba3, aba4, aba5, aba6 = st.tabs([
        "1. Aguardando 1ª Interação", 
        "2. Em Atendimento", 
        "3. Perdidos para Recuperação",
        "4. Auditoria de Malotes Enviados",
        "5. Comparador de Planilhas",
        "6. Bloqueio de Leads"
    ])

    # --- ABAS 1 E 2 ---
    def renderizar_painel_corretor_fixo(df_tipo, chave_aba, titulo_aba):
        st.subheader(f"{titulo_aba} (Cobrança do Corretor Responsável)")
        df_ativos = df_tipo[~df_tipo['Lead_Bloqueado']].copy()
        
        corretores_com_leads = sorted([c for c in df_ativos['Corretor'].dropna().unique() if str(c).strip() != ""])
        if not corretores_com_leads:
            st.info("Nenhum lead ativo encontrado nesta categoria.")
            return

        corretor_alvo = st.selectbox("Selecione o Corretor que será cobrado:", corretores_com_leads, key=f"sel_corretor_{chave_aba}")
        dados = df_ativos[df_ativos['Corretor'] == corretor_alvo].copy()

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
            leads_para_gravar.append({
                'lead_key': r['lead_key'], 
                'nome': r['Nome Cliente'], 
                'celular': r['Celular_Limpo'], 
                'corretor_orig': r['Corretor'],
                'etapa_atual': r['Etapa do Funil']
            })

        st.markdown(f"#### Lista do Malote para **{corretor_alvo}**:")
        render_botao_copiar(texto_whatsapp, f"📋 Copiar Lista ({len(leads_para_gravar)} leads) para Área de Transferência")
        st.code(texto_whatsapp, language="text")

        if st.button(f"✅ Confirmar e Registrar Envio do Malote para {corretor_alvo}", key=f"btn_reg_{chave_aba}_{corretor_alvo}", type="primary"):
            registrar_lote_enviado(leads_para_gravar, corretor_alvo, titulo_aba)
            st.success(f"Malote de {len(leads_para_gravar)} leads registrado como enviado para {corretor_alvo}!")
            st.rerun()

        st.markdown("#### Detalhamento dos Leads Deste Malote")
        st.dataframe(malote_atual[['Nome Cliente', 'Celular_Limpo', 'Faixa_Atraso', 'Dias_Sem_Interacao', 'Descrição Último Contato', 'Último Contato em', 'Status_Cobranca']], use_container_width=True)

    # --- ABA 3: PERDIDOS ---
    def renderizar_painel_perdidos(df_perdidos):
        st.subheader("Fila de Recuperação (Apenas: Tentativas de Contato Sem Sucesso)")
        st.caption("Leads arquivados sem resposta. Registre a redistribuição para removê-los da fila ativa.")
        
        df_perdidos_ativos = df_perdidos[~df_perdidos['Lead_Bloqueado']].copy()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("0 a 3 dias", len(df_perdidos_ativos[df_perdidos_ativos['Faixa_Atraso'] == "0 a 3 dias"]))
        c2.metric("3 a 10 dias", len(df_perdidos_ativos[df_perdidos_ativos['Faixa_Atraso'] == "3 a 10 dias"]))
        c3.metric("Mais de 10 dias", len(df_perdidos_ativos[df_perdidos_ativos['Faixa_Atraso'] == "Mais de 10 dias"]))
        c4.metric("Já Redistribuídos", len(df_perdidos_ativos[df_perdidos_ativos['Status_Cobranca'] == "Já Cobrado/Passado"]))

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filtro_faixa = st.multiselect("Filtrar Faixa de Dias da Perda:", ["0 a 3 dias", "3 a 10 dias", "Mais de 10 dias"], default=["3 a 10 dias", "Mais de 10 dias"], key="faixa_perdidos")
        with col_f2:
            filtro_cobranca = st.selectbox("Visualização da Fila:", ["Apenas Pendentes (Nunca Redistribuídos)", "Já Redistribuídos (Para Consulta)", "Todos"], key="cob_perdidos")
        with col_f3:
            donos_originais = ["Todos os Corretores de Origem"] + sorted([c for c in df_perdidos_ativos['Corretor'].dropna().unique() if str(c).strip() != ""])
            filtro_dono_orig = st.selectbox("Filtrar por Corretor Original (Dono Anterior):", donos_originais, key="orig_perdidos")

        dados_base = df_perdidos_ativos[df_perdidos_ativos['Faixa_Atraso'].isin(filtro_faixa)].copy()
        
        if filtro_cobranca == "Apenas Pendentes (Nunca Redistribuídos)":
            dados_base = dados_base[dados_base['Status_Cobranca'] == "Nunca Cobrado"]
        elif filtro_cobranca == "Já Redistribuídos (Para Consulta)":
            dados_base = dados_base[dados_base['Status_Cobranca'] == "Já Cobrado/Passado"]

        if filtro_dono_orig != "Todos os Corretores de Origem":
            dados_base = dados_base[dados_base['Corretor'] == filtro_dono_orig]

        st.markdown("---")
        
        if filtro_cobranca == "Já Redistribuídos (Para Consulta)":
            st.info("Visualizando leads que já foram redistribuídos anteriormente.")
            st.dataframe(dados_base[['Nome Cliente', 'Celular_Limpo', 'Corretor', 'corretor_cobrado', 'data_ultima_cobranca', 'Motivo Perda']], use_container_width=True)
            return

        st.markdown("#### Configuração da Redistribuição do Malote")
        
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

        dados_filtrados = dados_base[dados_base['Corretor'] != novo_destinatario].copy()
        total_disponivel = len(dados_filtrados)

        with col_m2:
            if total_disponivel > 0:
                tamanho_malote = st.number_input(f"Quantidade no malote (Disponíveis: {total_disponivel}):", min_value=1, max_value=total_disponivel, value=min(10, total_disponivel), step=1, key=f"num_perdidos_{novo_destinatario}")
            else:
                st.write("**Disponíveis:** 0 leads livres")
                tamanho_malote = 0

        if total_disponivel == 0:
            st.warning(f"Sem novos leads disponíveis para redistribuir para **{novo_destinatario}**.")
            return

        malote_atual = dados_filtrados.head(int(tamanho_malote))

        hoje = datetime.datetime.now()
        texto_whatsapp = f"*LISTA DE LEADS - RECUPERAÇÃO (TENTATIVAS SEM SUCESSO)*\n*Destinatário:* {novo_destinatario}\n*Data:* {hoje.strftime('%d/%m/%Y')}\n\n"

        leads_para_gravar = []
        for _, r in malote_atual.iterrows():
            texto_whatsapp += f"• *{r['Nome Cliente']}* - {r['Celular_Limpo']}\n"
            leads_para_gravar.append({
                'lead_key': r['lead_key'], 
                'nome': r['Nome Cliente'], 
                'celular': r['Celular_Limpo'], 
                'corretor_orig': r['Corretor'],
                'etapa_atual': r['Etapa do Funil']
            })

        st.markdown(f"#### Lista do Malote para **{novo_destinatario}**:")
        render_botao_copiar(texto_whatsapp, f"📋 Copiar Lista ({len(leads_para_gravar)} leads) para Área de Transferência")
        st.code(texto_whatsapp, language="text")

        if st.button(f"✅ Confirmar e Registrar Redistribuição para {novo_destinatario}", key=f"btn_reg_perdidos_{novo_destinatario}", type="primary"):
            registrar_lote_enviado(leads_para_gravar, novo_destinatario, "Perdidos Redistribuídos")
            st.success(f"Sucesso! {len(leads_para_gravar)} leads redistribuídos para {novo_destinatario} e removidos da fila ativa.")
            st.rerun()

        st.markdown("#### Detalhamento do Malote (Com Corretor Original)")
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

    # --- ABA 4: AUDITORIA DE MALOTES ENVIADOS ---
    with aba4:
        st.subheader("Auditoria de Malotes Enviados (Evolução no CRM pós-disparo)")
        st.caption("Esta tela audita se os corretores realmente entraram em contato com os leads que você enviou a eles no WhatsApp.")

        df_enviados = df[df['Status_Cobranca'] == "Já Cobrado/Passado"].copy()

        if df_enviados.empty:
            st.info("Você ainda não registrou nenhum malote de cobrança ou redistribuição no aplicativo.")
        else:
            def avaliar_atendimento_pos_envio(row):
                data_envio_str = str(row.get('data_ultima_cobranca', '')).strip()
                data_contato_crm = str(row.get('Último Contato em', '')).strip()
                etapa_crm_agora = str(row.get('Etapa do Funil', '')).strip()
                etapa_original_envio = str(row.get('etapa_ao_enviar', '')).strip()

                interagiu = False
                try:
                    d_envio = pd.to_datetime(data_envio_str, format="%d/%m/%Y %H:%M")
                    if data_contato_crm != "":
                        d_contato = pd.to_datetime(data_contato_crm, format="%d/%m/%Y %H:%M")
                        if d_contato >= d_envio:
                            interagiu = True
                except:
                    pass

                if etapa_crm_agora != etapa_original_envio and etapa_crm_agora not in ['Em Tentativa', 'Lead na Base', 'Perdido']:
                    return "Convertido / Avançou de Etapa 🎯"
                elif interagiu:
                    return "Trabalhado (Novo Contato no CRM) ✅"
                else:
                    return "Ignorado / Sem Contato Registrado ⚠️"

            df_enviados['Status_Auditoria'] = df_enviados.apply(avaliar_atendimento_pos_envio, axis=1)

            total_env = len(df_enviados)
            trabalhados = len(df_enviados[df_enviados['Status_Auditoria'].str.contains("✅|🎯")])
            ignorados = len(df_enviados[df_enviados['Status_Auditoria'].str.contains("⚠️")])
            taxa_trabalho = (trabalhados / total_env * 100) if total_env > 0 else 0

            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Total de Leads Enviados", total_env)
            a2.metric("Trabalhados pelos Corretores", trabalhados)
            a3.metric("Ignorados / Sem Contato", ignorados)
            a4.metric("Taxa de Execução", f"{taxa_trabalho:.1f}%")

            st.markdown("---")
            st.markdown("### Placar de Execução por Corretor Cobrado")
            resumo_execucao = df_enviados.groupby(['corretor_cobrado', 'Status_Auditoria']).size().unstack(fill_value=0)
            st.dataframe(resumo_execucao, use_container_width=True)

            st.markdown("---")
            st.markdown("### Detalhamento por Corretor")
            corretor_auditado = st.selectbox("Escolha o corretor para ver o status dos leads enviados:", ["Todos"] + sorted(df_enviados['corretor_cobrado'].dropna().unique().tolist()), key="sel_auditoria_corretor")

            filtro_auditoria_status = st.selectbox("Filtrar por Status de Execução:", ["Apenas Ignorados / Sem Contato", "Todos", "Apenas Trabalhados / Convertidos"], key="sel_auditoria_status")

            df_auditoria_view = df_enviados if corretor_auditado == "Todos" else df_enviados[df_enviados['corretor_cobrado'] == corretor_auditado]

            if filtro_auditoria_status == "Apenas Ignorados / Sem Contato":
                df_auditoria_view = df_auditoria_view[df_auditoria_view['Status_Auditoria'].str.contains("⚠️")]
            elif filtro_auditoria_status == "Apenas Trabalhados / Convertidos":
                df_auditoria_view = df_auditoria_view[df_auditoria_view['Status_Auditoria'].str.contains("✅|🎯")]

            colunas_auditoria = [
                'Nome Cliente', 'Celular_Limpo', 'corretor_cobrado', 'tipo_lead_envio',
                'Status_Auditoria', 'data_ultima_cobranca', 'Último Contato em', 
                'Etapa do Funil', 'Descrição Último Contato'
            ]
            st.dataframe(df_auditoria_view[colunas_auditoria], use_container_width=True)

    # --- ABA 5: COMPARADOR ENTRE PLANILHAS ---
    with aba5:
        st.subheader("Análise Comparativa Geral (Planilha Anterior vs. Atual)")
        with st.expander("ℹ️ GUIA RÁPIDO: O que significa cada status de evolução?", expanded=True):
            st.markdown("""
            Esta tela compara a planilha anterior com a atual cruzando o telefone e data do lead:
            
            * 🚀 **Avançou de Etapa (1ª Interação -> Atendimento):** O lead saiu de tentativa para atendimento ativo.
            * 📞 **Novo Contato Registrado:** A data do `Último Contato em` foi atualizada no CRM.
            * 🎯 **Recuperado com Sucesso:** Lead que estava arquivado como *Perdido* e foi resgatado.
            * ❌ **Marcado como Perdido:** O lead foi finalizado como perdido no período.
            * ⚠️ **Sem Alteração no CRM:** Nenhuma alteração de fase ou contato registrado desde a última planilha.
            """)

        if not arquivo_anterior:
            st.info("Para comparar duas versões de relatórios do CRM, suba o relatório no campo **'2. Relatório Anterior'** na barra lateral.")
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

    # --- ABA 6: CANCELAR / BLOQUEAR LEADS ---
    with aba6:
        st.subheader("Bloqueio de Leads (Remover Definitivamente da Redistribuição)")
        st.caption("Use esta área para cancelar leads que informaram que já compraram de concorrente, pediram para não ser contatados ou não têm interesse.")

        col_b1, col_b2 = st.columns([1, 1])

        with col_b1:
            st.markdown("#### Bloquear Novo Lead")
            busca_cliente = st.text_input("Buscar por Nome ou Telefone na base atual:")
            leads_encontrados = pd.DataFrame()
            if busca_cliente.strip():
                leads_encontrados = df[
                    df['Nome Cliente'].astype(str).str.contains(busca_cliente, case=False, na=False) |
                    df['Celular_Limpo'].astype(str).str.contains(busca_cliente, case=False, na=False)
                ].head(10)

            celular_alvo = ""
            nome_alvo = ""

            if not leads_encontrados.empty:
                opcao_sel = st.selectbox(
                    "Selecione o lead encontrado:",
                    options=leads_encontrados['lead_key'].tolist(),
                    format_func=lambda x: f"{leads_encontrados.loc[leads_encontrados['lead_key']==x, 'Nome Cliente'].values[0]} ({leads_encontrados.loc[leads_encontrados['lead_key']==x, 'Celular_Limpo'].values[0]})"
                )
                lead_escolhido = leads_encontrados[leads_encontrados['lead_key'] == opcao_sel].iloc[0]
                celular_alvo = lead_escolhido['Celular_Limpo']
                nome_alvo = lead_escolhido['Nome Cliente']
            else:
                celular_alvo = st.text_input("Ou digite o Celular (apenas dígitos):", value="")
                nome_alvo = st.text_input("Nome do Cliente (opcional):", value="")

            motivo_cancel = st.selectbox(
                "Motivo do Bloqueio:",
                [
                    "Já comprou de concorrente",
                    "Pediu para não entrar em contato",
                    "Número errado / Inexistente",
                    "Sem interesse definitivo",
                    "Outro motivo"
                ]
            )

            if st.button("Confirmar Bloqueio do Lead"):
                cel_limpo = limpar_celular(celular_alvo)
                if len(cel_limpo) < 8:
                    st.error("Informe um número de celular válido para bloquear.")
                else:
                    bloquear_lead_db(cel_limpo, nome_alvo or "Cliente", motivo_cancel)
                    st.success(f"Lead {nome_alvo} ({cel_limpo}) foi BLOQUEADO com sucesso!")
                    st.rerun()

        with col_b2:
            st.markdown("#### Leads Bloqueados Atualmente")
            df_bloq_exibir = get_leads_bloqueados()
            st.metric("Total de Leads Bloqueados", len(df_bloq_exibir))

            if not df_bloq_exibir.empty:
                st.dataframe(df_bloq_exibir[['celular', 'nome', 'motivo_cancelamento', 'data_bloqueio']], use_container_width=True)

                tel_desbloquear = st.selectbox("Deseja reativar/desbloquear algum lead?", ["Nenhum"] + df_bloq_exibir['celular'].tolist())
                if tel_desbloquear != "Nenhum" and st.button(f"Desbloquear {tel_desbloquear}"):
                    desbloquear_lead_db(tel_desbloquear)
                    st.success(f"Lead {tel_desbloquear} desbloqueado e liberado novamente!")
                    st.rerun()
            else:
                st.info("Nenhum lead bloqueado até o momento.")

else:
    st.info("Faça o upload do relatório diário na barra lateral para iniciar.")
