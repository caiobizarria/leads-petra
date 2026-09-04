import streamlit as st
import streamlit.components.v1 as components
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import datetime
import re
import json

st.set_page_config(page_title="Gestão Comercial & Retrabalho de Leads", layout="wide")

# --- CONEXÃO GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

COLS_ENVIOS = [
    'lead_key', 'nome', 'celular', 'corretor_cobrado', 'corretor_original',
    'tipo_lead', 'etapa_ao_enviar', 'data_envio', 'total_cobrancas'
]
COLS_BLOQUEADOS = ['celular', 'nome', 'motivo_cancelamento', 'data_bloqueio']

def carregar_aba(nome_aba, colunas_padrao):
    try:
        df_sheet = conn.read(worksheet=nome_aba, ttl=0)
        if df_sheet is None or df_sheet.empty:
            return pd.DataFrame(columns=colunas_padrao)
        df_sheet = df_sheet.dropna(how='all')
        for c in colunas_padrao:
            if c not in df_sheet.columns:
                df_sheet[c] = None
        return df_sheet
    except Exception:
        return pd.DataFrame(columns=colunas_padrao)

def get_historico():
    df_env = carregar_aba("controle_envios", COLS_ENVIOS)
    if not df_env.empty:
        df_env = df_env.rename(columns={
            'tipo_lead': 'tipo_lead_envio',
            'data_envio': 'data_ultima_cobranca'
        })
    return df_env

def get_leads_bloqueados():
    return carregar_aba("leads_bloqueados", COLS_BLOQUEADOS)

def registrar_lote_enviado(leads_para_gravar, corretor_destino, tipo_lead):
    df_atual = carregar_aba("controle_envios", COLS_ENVIOS)
    agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    
    novos_registros = []
    for l in leads_para_gravar:
        novos_registros.append({
            'lead_key': str(l['lead_key']),
            'nome': str(l['nome']),
            'celular': str(l['celular']),
            'corretor_cobrado': str(corretor_destino),
            'corretor_original': str(l.get('corretor_orig', '')),
            'tipo_lead': str(tipo_lead),
            'etapa_ao_enviar': str(l.get('etapa_atual', '')),
            'data_envio': agora,
            'total_cobrancas': 1
        })
    df_novos = pd.DataFrame(novos_registros)

    if df_atual.empty:
        df_final = df_novos
    else:
        df_atual['lead_key'] = df_atual['lead_key'].astype(str)
        keys_novas = set(df_novos['lead_key'])
        df_mantidos = df_atual[~df_atual['lead_key'].isin(keys_novas)].copy()
        
        cob_ant = df_atual.set_index('lead_key')['total_cobrancas'].to_dict()
        df_novos['total_cobrancas'] = df_novos['lead_key'].apply(lambda k: int(cob_ant.get(k, 0)) + 1)
        
        df_final = pd.concat([df_mantidos, df_novos], ignore_index=True)

    conn.update(worksheet="controle_envios", data=df_final)

def bloquear_lead_db(celular, nome, motivo):
    df_bloq = carregar_aba("leads_bloqueados", COLS_BLOQUEADOS)
    agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    novo = pd.DataFrame([{
        'celular': str(celular),
        'nome': str(nome),
        'motivo_cancelamento': str(motivo),
        'data_bloqueio': agora
    }])
    if df_bloq.empty:
        df_final = novo
    else:
        df_bloq['celular'] = df_bloq['celular'].astype(str)
        df_final = pd.concat([df_bloq[df_bloq['celular'] != str(celular)], novo], ignore_index=True)
    conn.update(worksheet="leads_bloqueados", data=df_final)

def desbloquear_lead_db(celular):
    df_bloq = carregar_aba("leads_bloqueados", COLS_BLOQUEADOS)
    if not df_bloq.empty:
        df_bloq['celular'] = df_bloq['celular'].astype(str)
        df_final = df_bloq[df_bloq['celular'] != str(celular)]
        conn.update(worksheet="leads_bloqueados", data=df_final)

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
            alert('Não foi possível copiar automaticamente. Use o bloco de texto para copiar.');
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

st.sidebar.markdown("### 📁 Relatórios do CRM")
arquivo_atual = st.sidebar.file_uploader("1. Relatório Atual / Mais Recente (.xlsx)", type=["xlsx"])
arquivo_anterior = st.sidebar.file_uploader("2. Relatório Anterior (Opcional p/ Comparar)", type=["xlsx"])

st.sidebar.markdown("---")
st.sidebar.success("☁️ Conectado ao Google Sheets (Persistência Permanente)")

if arquivo_atual:
    df_crm_atual = pd.read_excel(arquivo_atual, sheet_name=0)
    df = preparar_dataframe(df_crm_atual)

    df_hist = get_historico()
    if not df_hist.empty:
        df = df.merge(df_hist[['lead_key', 'corretor_cobrado', 'corretor_original', 'tipo_lead_envio', 'etapa_ao_enviar', 'data_ultima_cobranca', 'total_cobrancas']], on='lead_key', how='left')
    else:
        df['corretor_cobrado'] = None
        df['corretor_original'] = None
        df['tipo_lead_envio'] = None
        df['etapa_ao_enviar'] = None
        df['data_ultima_cobranca'] = None
        df['total_cobrancas'] = 0

    df['Status_Cobranca'] = df['data_ultima_cobranca'].apply(lambda x: "Já Cobrado/Passado" if pd.notna(x) and str(x).strip() != "" else "Nunca Cobrado")
    
    df_bloqueados = get_leads_bloqueados()
    telefones_bloqueados = set(df_bloqueados['celular'].dropna().astype(str).tolist()) if not df_bloqueados.empty else set()
    df['Lead_Bloqueado'] = df['Celular_Limpo'].astype(str).isin(telefones_bloqueados)

    corretores_disponiveis = sorted([c for c in df['Corretor'].dropna().unique() if str(c).strip() != ""])

    aba1, aba2, aba3, aba4, aba5, aba6 = st.tabs([
        "1. Aguardando 1ª Interação", 
        "2. Em Atendimento", 
        "3. Perdidos para Recuperação",
        "4. Auditoria de Malotes (Google Sheets)",
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

        default_val = min(10, total_disponivel)
        widget_key = f"num_{chave_aba}_{corretor_alvo}_{total_disponivel}"
        
        tamanho_malote = st.number_input(
            f"Quantidade de leads para este malote (Disponíveis: {total_disponivel}):",
            min_value=1,
            max_value=max(1, total_disponivel),
            value=max(1, default_val),
            step=1,
            key=widget_key
        )

        qtd_final = max(1, min(int(tamanho_malote or 1), total_disponivel))
        malote_atual = dados_filtrados.head(qtd_final)

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

        if st.button(f"✅ Confirmar e Salvar Envio no Google Sheets ({corretor_alvo})", key=f"btn_reg_{chave_aba}_{corretor_alvo}", type="primary"):
            with st.spinner("Salvando na planilha..."):
                registrar_lote_enviado(leads_para_gravar, corretor_alvo, titulo_aba)
            st.success(f"Malote de {len(leads_para_gravar)} leads registrado para {corretor_alvo} no Google Sheets!")
            st.rerun()

        st.markdown("#### Detalhamento dos Leads Deste Malote")
        st.dataframe(malote_atual[['Nome Cliente', 'Celular_Limpo', 'Faixa_Atraso', 'Dias_Sem_Interacao', 'Descrição Último Contato', 'Último Contato em', 'Status_Cobranca']], use_container_width=True)

    # --- ABA 3: PERDIDOS ---
    def renderizar_painel_perdidos(df_perdidos):
        st.subheader("Fila de Recuperação (Apenas: Tentativas de Contato Sem Sucesso)")
        st.caption("Leads arquivados sem resposta. Registre a redistribuição para salvá-los no Google Sheets e retirá-los da fila ativa.")
        
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
                default_perd = min(10, total_disponivel)
                widget_key_perd = f"num_perd_{novo_destinatario}_{total_disponivel}"
                tamanho_malote = st.number_input(
                    f"Quantidade no malote (Disponíveis: {total_disponivel}):",
                    min_value=1,
                    max_value=max(1, total_disponivel),
                    value=max(1, default_perd),
                    step=1,
                    key=widget_key_perd
                )
                qtd_final_perd = max(1, min(int(tamanho_malote or 1), total_disponivel))
            else:
                st.write("**Disponíveis:** 0 leads livres")
                qtd_final_perd = 0

        if total_disponivel == 0 or qtd_final_perd == 0:
            st.warning(f"Sem novos leads disponíveis para redistribuir para **{novo_destinatario}**.")
            return

        malote_atual = dados_filtrados.head(qtd_final_perd)

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

        if st.button(f"✅ Confirmar e Salvar Redistribuição no Google Sheets ({novo_destinatario})", key=f"btn_reg_perdidos_{novo_destinatario}", type="primary"):
            with st.spinner("Salvando na planilha..."):
                registrar_lote_enviado(leads_para_gravar, novo_destinatario, "Perdidos Redistribuídos")
            st.success(f"Sucesso! {len(leads_para_gravar)} leads redistribuídos para {novo_destinatario} gravados na nuvem e removidos da fila ativa.")
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

    # --- ABA 4: AUDITORIA VISUAL DE MALOTES (NOVO DASHBOARD) ---
    with aba4:
        st.subheader("Auditoria de Malotes Enviados (Cruzamento com Google Sheets)")
        st.caption("Visão executiva do cumprimento de tarefas por cada corretor desde a entrega dos malotes.")

        df_enviados = df[df['Status_Cobranca'] == "Já Cobrado/Passado"].copy()

        if df_enviados.empty:
            st.info("Nenhum registro de malote localizado na planilha do Google Sheets até o momento.")
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
                    return "Convertido / Avançou 🎯"
                elif interagiu:
                    return "Trabalhado no CRM ✅"
                else:
                    return "Ignorado / Parado ⚠️"

            df_enviados['Status_Auditoria'] = df_enviados.apply(avaliar_atendimento_pos_envio, axis=1)

            # Métricas Globais
            total_env = len(df_enviados)
            trabalhados = len(df_enviados[df_enviados['Status_Auditoria'].str.contains("✅|🎯")])
            ignorados = len(df_enviados[df_enviados['Status_Auditoria'].str.contains("⚠️")])
            taxa_trabalho = (trabalhados / total_env * 100) if total_env > 0 else 0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total de Leads Entregues", total_env)
            m2.metric("Trabalhados / Convertidos", trabalhados)
            m3.metric("Ignorados / Sem Contato", ignorados, delta=f"-{ignorados}" if ignorados > 0 else "0", delta_color="inverse")
            m4.metric("Aproveitamento Geral", f"{taxa_trabalho:.1f}%")

            st.markdown("---")

            # 1. TABELA COMPARATIVA VISUAL (RANKING POR CORRETOR COM SEMÁFORO)
            st.markdown("### 🏆 Ranking Comparativo de Execução por Corretor")
            
            # Agregação por Corretor
            corretores_grp = []
            for corr, grp in df_enviados.groupby('corretor_cobrado'):
                total_c = len(grp)
                trab_c = len(grp[grp['Status_Auditoria'].str.contains("✅|🎯")])
                ign_c = len(grp[grp['Status_Auditoria'].str.contains("⚠️")])
                taxa_c = (trab_c / total_c * 100) if total_c > 0 else 0
                
                # Barra de progresso visual em texto
                blocos_cheios = int(taxa_c // 10)
                barra_visual = "█" * blocos_cheios + "░" * (10 - blocos_cheios)
                
                # Classificação de Semáforo
                if taxa_c >= 70:
                    status_semaforo = "🟢 Excelente"
                elif taxa_c >= 40:
                    status_semaforo = "🟡 Atenção"
                else:
                    status_semaforo = "🔴 Gargalo Crítico"

                corretores_grp.append({
                    'Corretor': corr,
                    'Status Operacional': status_semaforo,
                    'Leads Entregues': total_c,
                    'Trabalhados': trab_c,
                    'Ignorados / Parados': ign_c,
                    'Taxa de Atendimento': f"{taxa_c:.1f}%",
                    'Progresso': f"{barra_visual} ({taxa_c:.0f}%)"
                })

            df_ranking = pd.DataFrame(corretores_grp).sort_values(by='Ignorados / Parados', ascending=False)
            st.dataframe(df_ranking[['Corretor', 'Status Operacional', 'Progresso', 'Leads Entregues', 'Trabalhados', 'Ignorados / Parados', 'Taxa de Atendimento']], use_container_width=True, hide_index=True)

            # 2. GRÁFICO COMPARATIVO DIRETO
            st.markdown("### 📊 Gráfico de Volume: Trabalhados vs. Ignorados")
            df_chart_dados = df_enviados.groupby(['corretor_cobrado', 'Status_Auditoria']).size().unstack(fill_value=0)
            st.bar_chart(df_chart_dados)

            st.markdown("---")

            # 3. DIAGNÓSTICO INDIVIDUAL (1 a 1) E COBRANÇA REINCIDENTE
            st.markdown("### 🔍 Diagnóstico Individual e Cobrança Direta")
            corretor_selecionado = st.selectbox(
                "Selecione um Corretor para auditar e cobrar pendências:",
                sorted(df_enviados['corretor_cobrado'].dropna().unique().tolist()),
                key="sel_1a1_corretor"
            )

            df_1a1 = df_enviados[df_enviados['corretor_cobrado'] == corretor_selecionado].copy()
            pendentes_1a1 = df_1a1[df_1a1['Status_Auditoria'].str.contains("⚠️")]

            col_c1, col_c2, col_c3 = st.columns(3)
            col_c1.metric("Leads Entregues para ele(a)", len(df_1a1))
            col_c2.metric("Trabalhados", len(df_1a1) - len(pendentes_1a1))
            col_c3.metric("Ainda Sem Contato", len(pendentes_1a1), delta=f"{len(pendentes_1a1)} pendentes" if len(pendentes_1a1) > 0 else "Em dia", delta_color="inverse")

            if not pendentes_1a1.empty:
                st.warning(f"**{corretor_selecionado}** possui **{len(pendentes_1a1)} leads** entregues que ainda não têm registro de contato no CRM.")
                
                # Gera mensagem de cobrança individual
                msg_cobranca = f"Olá, *{corretor_selecionado}*! Tudo bem?\n\nConsta aqui no nosso acompanhamento que você recebeu uma lista de leads para retrabalho recentemente, mas estes contatos ainda constam sem nova interação registrada no sistema:\n\n"
                for _, r in pendentes_1a1.head(15).iterrows():
                    msg_cobranca += f"• *{r['Nome Cliente']}* - {r['Celular_Limpo']}\n"
                msg_cobranca += "\nConsegue dar prioridade nesse contato e atualizar o CRM hoje? Obrigado!"

                with st.expander("👁️ Ver mensagem pronta para cobrar este corretor no WhatsApp:", expanded=True):
                    render_botao_copiar(msg_cobranca, f"📋 Copiar Mensagem de Cobrança para {corretor_selecionado}")
                    st.code(msg_cobranca, language="text")

                st.markdown("#### Lista detalhada de leads ignorados deste corretor:")
                st.dataframe(pendentes_1a1[['Nome Cliente', 'Celular_Limpo', 'data_ultima_cobranca', 'Etapa do Funil', 'Descrição Último Contato']], use_container_width=True)
            else:
                st.success(f"🎉 Excelente! **{corretor_selecionado}** já iniciou contato com 100% dos leads que foram entregues a ele(a).")

    # --- ABA 5: COMPARADOR ENTRE PLANILHAS (VISÃO EXECUTIVA) ---
    with aba5:
        st.subheader("Análise Comparativa Geral (Planilha Anterior vs. Atual)")
        with st.expander("ℹ️ GUIA RÁPIDO: O que significa cada status de evolução?", expanded=False):
            st.markdown("""
            Esta tela compara a planilha anterior com a atual cruzando o telefone e data do lead:
            
            * 🚀 **Avançou de Etapa:** O lead saiu de tentativa para atendimento ativo.
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

            if st.button("Confirmar Bloqueio do Lead no Google Sheets"):
                cel_limpo = limpar_celular(celular_alvo)
                if len(cel_limpo) < 8:
                    st.error("Informe um número de celular válido para bloquear.")
                else:
                    with st.spinner("Salvando bloqueio na planilha..."):
                        bloquear_lead_db(cel_limpo, nome_alvo or "Cliente", motivo_cancel)
                    st.success(f"Lead {nome_alvo} ({cel_limpo}) foi BLOQUEADO com sucesso no Google Sheets!")
                    st.rerun()

        with col_b2:
            st.markdown("#### Leads Bloqueados Atualmente (Planilha)")
            df_bloq_exibir = get_leads_bloqueados()
            st.metric("Total de Leads Bloqueados", len(df_bloq_exibir))

            if not df_bloq_exibir.empty:
                st.dataframe(df_bloq_exibir[['celular', 'nome', 'motivo_cancelamento', 'data_bloqueio']], use_container_width=True)

                tel_desbloquear = st.selectbox("Deseja reativar/desbloquear algum lead?", ["Nenhum"] + df_bloq_exibir['celular'].dropna().astype(str).tolist())
                if tel_desbloquear != "Nenhum" and st.button(f"Desbloquear {tel_desbloquear}"):
                    with st.spinner("Removendo da lista de bloqueio..."):
                        desbloquear_lead_db(tel_desbloquear)
                    st.success(f"Lead {tel_desbloquear} desbloqueado e liberado novamente!")
                    st.rerun()
            else:
                st.info("Nenhum lead bloqueado até o momento.")

else:
    st.info("Faça o upload do relatório diário na barra lateral para iniciar.")
