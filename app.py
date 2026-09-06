import streamlit as st
import streamlit.components.v1 as components
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import datetime
import re
import json
import io

st.set_page_config(page_title="Gestão Comercial & Retrabalho de Leads", layout="wide")

# CSS para garantir quebra limpa
st.markdown("""
<style>
    div[data-baseweb="tab-list"] {
        flex-wrap: wrap !important;
        gap: 6px !important;
    }
</style>
""", unsafe_allow_html=True)

# --- CONEXÃO GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

COLS_ENVIOS = [
    'lead_key', 'nome', 'celular', 'corretor_cobrado', 'corretor_original',
    'tipo_lead', 'etapa_ao_enviar', 'data_envio', 'total_cobrancas', 'feedback_recuperacao'
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
            'total_cobrancas': 1,
            'feedback_recuperacao': 'Aguardando Retorno' if 'Perdidos' in tipo_lead else 'N/A'
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

def atualizar_feedback_recuperacao(lead_key, novo_status):
    df_atual = carregar_aba("controle_envios", COLS_ENVIOS)
    if not df_atual.empty:
        df_atual['lead_key'] = df_atual['lead_key'].astype(str)
        df_atual.loc[df_atual['lead_key'] == str(lead_key), 'feedback_recuperacao'] = novo_status
        conn.update(worksheet="controle_envios", data=df_atual)

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
    elif etapa_str in ['Em Atendimento - Primeiras Informações', 'Em Atendimento - Aguardando Disponibilidade']:
        return "2. Em Atendimento"
    elif etapa_str in ['Visita Agendada', 'Visita Realizada', 'Negócio Fechado.']:
        return "3. Visitas & Fechamento"
    elif etapa_str in ['Perdido', 'Visita Cancelada', 'Visita - Cliente Não Compareceu']:
        if motivo_perda.lower() == "tentativas de contato sem sucesso":
            return "4. Perdidos para Recuperação"
        else:
            return "Perdido (Outros Motivos)"
    return "Outros"

def parse_data_segura(val):
    if pd.isna(val) or str(val).strip() == "":
        return None
    try:
        return pd.to_datetime(val, dayfirst=True)
    except:
        return None

def formatar_tempo_passado(minutos_totais):
    if minutos_totais < 60:
        return f"{int(minutos_totais)} min atrás"
    horas = int(minutos_totais // 60)
    mins = int(minutos_totais % 60)
    if horas < 24:
        return f"{horas}h {mins}min atrás"
    dias = int(horas // 24)
    horas_rest = int(horas % 24)
    return f"{dias}d {horas_rest}h atrás"

def preparar_dataframe(df_raw):
    df = df_raw.copy()
    df['Celular_Limpo'] = df['Celular Cliente'].apply(limpar_celular)
    df['Recebido_Str'] = df['Recebido em'].astype(str)
    df['lead_key'] = df['Celular_Limpo'] + "_" + df['Recebido_Str']
    df['Descrição Último Contato'] = df['Descrição Último Contato'].fillna("Sem descrição registrada")
    df['Motivo Perda'] = df['Motivo Perda'].fillna("Não informado")
    df['Tipo_Lead'] = df.apply(classificar_tipo, axis=1)
    
    df['Recebido_DT'] = df['Recebido em'].apply(parse_data_segura)
    df['Ultimo_Contato_DT'] = df['Último Contato em'].apply(parse_data_segura)
    df['Primeiro_Contato_DT'] = df['Data Primeiro Contato'].apply(parse_data_segura)
    df['Perdido_DT'] = df['Negócio Perdido em'].apply(parse_data_segura)

    hoje = datetime.datetime.now()
    def calcular_dias(row):
        dt = row.get('Ultimo_Contato_DT')
        if not dt:
            dt = row.get('Recebido_DT')
        if dt:
            return max(0, (hoje - dt).days)
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

# --- BARRA LATERAL ---
st.sidebar.markdown("### 📁 Relatórios do CRM")
arquivo_atual = st.sidebar.file_uploader("1. Relatório Atual / Mais Recente (.xlsx)", type=["xlsx"])
arquivo_anterior = st.sidebar.file_uploader("2. Relatório Anterior (Opcional p/ Comparar)", type=["xlsx"])

st.sidebar.markdown("---")
st.sidebar.markdown("### 📌 Módulos do Sistema")

OPCOES_MODULOS = [
    "📊 Visão Geral",
    "⚡ Movimentações & Leads por Data",
    "1. Aguardando 1ª Interação (Em Tentativa)", 
    "2. Em Atendimento", 
    "3. Visitas & Fechamento",
    "4. Fila de Recuperação (Redistribuir)",
    "🎯 Auditoria: Cobrança de Carteira",
    "🔄 Auditoria: Fila de Recuperação (Blocklist + Resgates)",
    "6. Comparador de Planilhas (Raio-X)",
    "📑 Central de Relatórios",
    "🚫 Bloqueio de Leads"
]

modulo_ativo = st.sidebar.radio("Navegação:", OPCOES_MODULOS, index=0, label_visibility="collapsed")
st.sidebar.markdown("---")
st.sidebar.success("☁️ Google Sheets Conectado")

if arquivo_atual:
    df_crm_atual = pd.read_excel(arquivo_atual, sheet_name=0)
    df = preparar_dataframe(df_crm_atual)

    df_hist = get_historico()
    if not df_hist.empty:
        # Garante unicidade da chave no histórico antes de mesclar
        df_hist_unique = df_hist.drop_duplicates(subset=['lead_key'], keep='last')
        df = df.merge(
            df_hist_unique[['lead_key', 'corretor_cobrado', 'corretor_original', 'tipo_lead_envio', 'etapa_ao_enviar', 'data_ultima_cobranca', 'total_cobrancas', 'feedback_recuperacao']], 
            on='lead_key', 
            how='left'
        )
    else:
        df['corretor_cobrado'] = None
        df['corretor_original'] = None
        df['tipo_lead_envio'] = None
        df['etapa_ao_enviar'] = None
        df['data_ultima_cobranca'] = None
        df['total_cobrancas'] = 0
        df['feedback_recuperacao'] = None

    df['Status_Cobranca'] = df['data_ultima_cobranca'].apply(lambda x: "Já Cobrado/Passado" if pd.notna(x) and str(x).strip() != "" else "Nunca Cobrado")
    
    df_bloqueados = get_leads_bloqueados()
    telefones_bloqueados = set(df_bloqueados['celular'].dropna().astype(str).tolist()) if not df_bloqueados.empty else set()
    df['Lead_Bloqueado'] = df['Celular_Limpo'].astype(str).isin(telefones_bloqueados)

    corretores_disponiveis = sorted([c for c in df['Corretor'].dropna().unique() if str(c).strip() != ""])

    # --- MÓDULO 1: VISÃO GERAL ---
    if modulo_ativo == "📊 Visão Geral":
        st.subheader("Panorama Consolidado da Base Importada")
        st.caption("Visão macro de 100% dos leads carregados na planilha atual, segmentados por estágio, motivos de perda e corretores.")

        total_base = len(df)
        total_1a = len(df[df['Tipo_Lead'] == "1. Aguardando 1ª Interação"])
        total_atend = len(df[df['Tipo_Lead'] == "2. Em Atendimento"])
        total_vis = len(df[df['Tipo_Lead'] == "3. Visitas & Fechamento"])
        total_recup = len(df[df['Tipo_Lead'] == "4. Perdidos para Recuperação"])

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total de Leads na Planilha", total_base)
        m2.metric("Em Tentativa (1ª Interação)", total_1a)
        m3.metric("Em Atendimento Ativo", total_atend)
        m4.metric("Visitas & Fechamentos", total_vis)
        m5.metric("Fila de Recuperação", total_recup)

        st.markdown("---")
        col_v1, col_v2 = st.columns([1, 1])

        with col_v1:
            st.markdown("#### 📌 Distribuição por Etapa do Funil")
            df_etapas = df['Etapa do Funil'].value_counts().reset_index()
            df_etapas.columns = ['Etapa do Funil', 'Quantidade de Leads']
            df_etapas['% da Base'] = (df_etapas['Quantidade de Leads'] / total_base * 100).map("{:.1f}%".format)
            st.dataframe(df_etapas, use_container_width=True, hide_index=True)

        with col_v2:
            st.markdown("#### ❌ Análise dos Motivos de Perda (Percentual)")
            df_perdas_base = df[df['Motivo Perda'].notna() & (df['Motivo Perda'] != 'Não informado')].copy()
            total_perdas = len(df_perdas_base)
            if total_perdas > 0:
                loss_counts = df_perdas_base['Motivo Perda'].value_counts().reset_index()
                loss_counts.columns = ['Motivo de Perda', 'Quantidade']
                loss_counts['% dos Perdidos'] = (loss_counts['Quantidade'] / total_perdas * 100).map("{:.1f}%".format)
                loss_counts['% da Base Total'] = (loss_counts['Quantidade'] / total_base * 100).map("{:.1f}%".format)
                st.dataframe(loss_counts, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhum lead com motivo de perda informado.")

        st.markdown("---")
        st.markdown("#### 👥 Distribuição da Carteira por Corretor")
        df_dist_corr = pd.crosstab(df['Corretor'], df['Tipo_Lead'], margins=True, margins_name="Total")
        st.dataframe(df_dist_corr, use_container_width=True)

    # --- MÓDULO 2: MOVIMENTAÇÕES POR DATA ---
    elif modulo_ativo == "⚡ Movimentações & Leads por Data":
        st.subheader("⚡ Auditoria Diária: O que Entrou e o que foi Movimentado")
        st.caption("Filtre uma data exata para auditar: 1) Quais leads novos caíram e quem os recebeu; 2) Quais contatos foram feitos no CRM naquele dia.")

        datas_disponiveis = sorted(list(set(df['Recebido_DT'].dropna().dt.date.tolist() + df['Ultimo_Contato_DT'].dropna().dt.date.tolist())), reverse=True)
        data_padrao = datas_disponiveis[0] if datas_disponiveis else datetime.date.today()

        col_d1, col_d2 = st.columns([1, 2])
        with col_d1:
            data_selecionada = st.date_input("Escolha a data para auditar:", value=data_padrao, key="sel_data_audit_dia")

        df['Entrou_No_Dia'] = df['Recebido_DT'].apply(lambda d: d.date() == data_selecionada if pd.notna(d) else False)
        df_entradas_dia = df[df['Entrou_No_Dia']].copy()

        df['Contatado_No_Dia'] = df['Ultimo_Contato_DT'].apply(lambda d: d.date() == data_selecionada if pd.notna(d) else False)
        df['Perdido_No_Dia'] = df['Perdido_DT'].apply(lambda d: d.date() == data_selecionada if pd.notna(d) else False)
        df_acoes_dia = df[df['Contatado_No_Dia'] | df['Perdido_No_Dia']].copy()

        with col_d2:
            st.markdown(f"**Resumo de {data_selecionada.strftime('%d/%m/%Y')}:**")
            k1, k2, k3 = st.columns(3)
            k1.metric("Leads Entrados", len(df_entradas_dia))
            k2.metric("Contatados no Dia", len(df_acoes_dia[df_acoes_dia['Contatado_No_Dia']]))
            k3.metric("Descartados no Dia", len(df_acoes_dia[df_acoes_dia['Perdido_No_Dia']]))

        st.markdown("---")
        sub_d1, sub_d2 = st.tabs(["📥 1. Leads que Entraram Nesta Data", "📞 2. Leads com Contato/Ação Nesta Data"])

        with sub_d1:
            if df_entradas_dia.empty:
                st.info(f"Nenhum lead com data de entrada (`Recebido em`) registrada em {data_selecionada.strftime('%d/%m/%Y')}.")
            else:
                st.markdown(f"#### Foram recebidos **{len(df_entradas_dia)} leads** em {data_selecionada.strftime('%d/%m/%Y')}:")
                
                # Resumo por corretor
                dist_novos = df_entradas_dia.groupby('Corretor').agg(
                    Total_Recebido=('Nome Cliente', 'count'),
                    Em_Tentativa=('Etapa do Funil', lambda s: (s.isin(['Em Tentativa', 'Lead na Base'])).sum()),
                    Ja_Atendendo=('Etapa do Funil', lambda s: (~s.isin(['Em Tentativa', 'Lead na Base', 'Perdido'])).sum())
                ).reset_index()
                st.dataframe(dist_novos, use_container_width=True, hide_index=True)

                cols_entradas = [
                    'Nome Cliente', 'Celular_Limpo', 'Corretor', 'Recebido em',
                    'Etapa do Funil', 'Último Contato em', 'Descrição Último Contato', 'Origem (Tipo Mídia)'
                ]
                df_ent_show = df_entradas_dia[cols_entradas].rename(columns={
                    'Nome Cliente': 'Cliente',
                    'Celular_Limpo': 'Celular',
                    'Descrição Último Contato': 'Última Anotação'
                })
                st.dataframe(df_ent_show, use_container_width=True, hide_index=True)

        with sub_d2:
            if df_acoes_dia.empty:
                st.info(f"Nenhum atendimento ou alteração registrada no CRM com data de {data_selecionada.strftime('%d/%m/%Y')}.")
            else:
                st.markdown(f"#### Foram movimentados **{len(df_acoes_dia)} leads** no CRM em {data_selecionada.strftime('%d/%m/%Y')}:")
                resumo_acao_corr = df_acoes_dia.groupby(['Corretor', 'Etapa do Funil']).size().unstack(fill_value=0)
                st.dataframe(resumo_acao_corr, use_container_width=True)

                cols_acoes = [
                    'Nome Cliente', 'Celular_Limpo', 'Corretor', 'Etapa do Funil',
                    'Último Contato em', 'Descrição Último Contato', 'Motivo Perda'
                ]
                df_acoes_show = df_acoes_dia[cols_acoes].rename(columns={
                    'Nome Cliente': 'Cliente',
                    'Celular_Limpo': 'Celular',
                    'Descrição Último Contato': 'Anotação no CRM'
                })
                st.dataframe(df_acoes_show, use_container_width=True, hide_index=True)

    # --- PAINEL PADRÃO PARA CORRETOR FIXO ---
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
            texto_whatsapp += f"• *{r['Nome Cliente']}* - {r['Celular_Limpo']} ({r['Etapa do Funil']})\n"
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
        st.dataframe(malote_atual[['Nome Cliente', 'Celular_Limpo', 'Etapa do Funil', 'Faixa_Atraso', 'Dias_Sem_Interacao', 'Descrição Último Contato', 'Último Contato em', 'Status_Cobranca']], use_container_width=True)

    # --- MÓDULOS 1, 2, 3 ---
    if modulo_ativo == "1. Aguardando 1ª Interação (Em Tentativa)":
        df_1 = df[df['Tipo_Lead'] == "1. Aguardando 1ª Interação"]
        renderizar_painel_corretor_fixo(df_1, "m1", "Aguardando 1ª Interação (Em Tentativa)")

    elif modulo_ativo == "2. Em Atendimento":
        df_2 = df[df['Tipo_Lead'] == "2. Em Atendimento"]
        renderizar_painel_corretor_fixo(df_2, "m2", "Em Atendimento")

    elif modulo_ativo == "3. Visitas & Fechamento":
        df_vis = df[df['Tipo_Lead'] == "3. Visitas & Fechamento"]
        renderizar_painel_corretor_fixo(df_vis, "m3", "Visitas & Fechamento")

    # --- MÓDULO 4: FILA DE RECUPERAÇÃO ---
    elif modulo_ativo == "4. Fila de Recuperação (Redistribuir)":
        st.subheader("Fila de Recuperação (Apenas: Tentativas de Contato Sem Sucesso)")
        st.caption("Leads arquivados sem resposta. Registre a redistribuição para salvá-los no Google Sheets e retirá-los da fila ativa.")
        
        df_perdidos = df[df['Tipo_Lead'] == "4. Perdidos para Recuperação"]
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
        else:
            st.markdown("#### Configuração da Redistribuição do Malote")
            
            if filtro_dono_orig != "Todos os Corretores de Origem":
                destinatarios_possiveis = [c for c in corretores_disponiveis if c != filtro_dono_orig]
            else:
                destinatarios_possiveis = corretores_disponiveis

            if not destinatarios_possiveis:
                st.warning("Não há corretores de destino disponíveis.")
            else:
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

                if total_disponivel > 0 and qtd_final_perd > 0:
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

                    st.markdown("#### Detalhamento do Malote (Com Corretor Original)")
                    df_exibicao = malote_atual.rename(columns={'Corretor': 'Corretor Original (Dono Anterior)'})
                    st.dataframe(df_exibicao[['Nome Cliente', 'Celular_Limpo', 'Corretor Original (Dono Anterior)', 'Motivo Perda', 'Faixa_Atraso', 'Dias_Sem_Interacao', 'Descrição Último Contato']], use_container_width=True)
                else:
                    st.warning(f"Sem novos leads disponíveis para redistribuir para **{novo_destinatario}**.")

    # --- MÓDULO 5: AUDITORIA DE COBRANÇA DE CARTEIRA ---
    elif modulo_ativo == "🎯 Auditoria: Cobrança de Carteira":
        st.subheader("Auditoria de Cobrança de Carteira (1º Contato & Atendimento)")
        st.caption("Estes leads já pertencem ao corretor no CRM. Verificação cronológica: checamos se ele registrou contato no Latitude APÓS o envio da cobrança.")

        df_enviados_carteira = df[(df['Status_Cobranca'] == "Já Cobrado/Passado") & (df['tipo_lead_envio'] != "Perdidos Redistribuídos")].copy()

        if df_enviados_carteira.empty:
            st.info("Nenhum registro de cobrança de carteira localizado na planilha do Google Sheets até o momento.")
        else:
            def avaliar_carteira(row):
                data_envio_dt = parse_data_segura(row.get('data_ultima_cobranca'))
                data_contato_dt = row.get('Ultimo_Contato_DT')
                data_perdido_dt = row.get('Perdido_DT')

                etapa_crm_agora = str(row.get('Etapa do Funil', '')).strip()
                etapa_original_envio = str(row.get('etapa_ao_enviar', '')).strip()

                datas_acao = [d for d in [data_contato_dt, data_perdido_dt] if d is not None]
                ultima_acao_crm = max(datas_acao) if datas_acao else None

                interagiu_depois = False
                if data_envio_dt and ultima_acao_crm:
                    if ultima_acao_crm > data_envio_dt:
                        interagiu_depois = True

                if etapa_crm_agora != etapa_original_envio and etapa_crm_agora not in ['Em Tentativa', 'Lead na Base', 'Perdido']:
                    return "Convertido / Avançou 🎯"
                elif interagiu_depois:
                    return "Trabalhado no CRM (Pós-Envio) ✅"
                else:
                    return "Ignorado / Sem Contato Pós-Envio ⚠️"

            df_enviados_carteira['Status_Auditoria'] = df_enviados_carteira.apply(avaliar_carteira, axis=1)

            total_c = len(df_enviados_carteira)
            trab_c = len(df_enviados_carteira[df_enviados_carteira['Status_Auditoria'].str.contains("✅|🎯")])
            ign_c = len(df_enviados_carteira[df_enviados_carteira['Status_Auditoria'].str.contains("⚠️")])
            taxa_c = (trab_c / total_c * 100) if total_c > 0 else 0

            ac1, ac2, ac3, ac4 = st.columns(4)
            ac1.metric("Cobranças Enviadas", total_c)
            ac2.metric("Trabalhados no CRM", trab_c)
            ac3.metric("Ignorados / Sem Contato", ign_c, delta=f"-{ign_c}" if ign_c > 0 else "0", delta_color="inverse")
            ac4.metric("Aproveitamento Real", f"{taxa_c:.1f}%")

            st.markdown("---")
            st.markdown("### 🏆 Placar de Cobrança por Corretor")
            resumo_cart = df_enviados_carteira.groupby(['corretor_cobrado', 'Status_Auditoria']).size().unstack(fill_value=0)
            st.dataframe(resumo_cart, use_container_width=True)

            st.markdown("---")
            st.markdown("### 🔍 Detalhes e Cobrança Rápida de Pendências")
            corretor_sel_c = st.selectbox("Escolha o corretor cobrado:", sorted(df_enviados_carteira['corretor_cobrado'].dropna().unique().tolist()), key="sel_cart_corr")
            df_view_cart = df_enviados_carteira[df_enviados_carteira['corretor_cobrado'] == corretor_sel_c]
            pendentes_cart = df_view_cart[df_view_cart['Status_Auditoria'].str.contains("⚠️")]

            if not pendentes_cart.empty:
                st.warning(f"**{corretor_sel_c}** tem **{len(pendentes_cart)} leads cobrados** que ainda não tiveram contato posterior ao malote.")
                msg_cob_pend = f"Olá, *{corretor_sel_c}*! Tudo bem?\n\nCobramos estes leads recentemente, mas eles continuam sem registro de atendimento no CRM:\n\n"
                for _, r in pendentes_cart.head(15).iterrows():
                    msg_cob_pend += f"• *{r['Nome Cliente']}* - {r['Celular_Limpo']}\n"
                msg_cob_pend += "\nConsegue atualizar o status deles no sistema hoje? Obrigado!"
                render_botao_copiar(msg_cob_pend, f"📋 Copiar Cobrança de Carteira para {corretor_sel_c}")
            else:
                st.success(f"🎉 **{corretor_sel_c}** atendeu 100% dos leads cobrados da carteira!")

            cols_show_cart = ['Nome Cliente', 'Celular_Limpo', 'Status_Auditoria', 'data_ultima_cobranca', 'Último Contato em', 'Etapa do Funil', 'Descrição Último Contato']
            st.dataframe(df_view_cart[cols_show_cart], use_container_width=True, hide_index=True)

    # --- MÓDULO 6: AUDITORIA DA FILA DE RECUPERAÇÃO (BLOCKLIST + RESGATES CORRIGIDO) ---
    elif modulo_ativo == "🔄 Auditoria: Fila de Recuperação (Blocklist + Resgates)":
        st.subheader("Métrica de Ouro: Eficiência do Retrabalho por Corretor")
        st.caption("Avalia o retorno real dos leads perdidos redistribuídos: 1) Resgates vivos (viraram Atendimento/Visita no CRM); 2) Base limpa (leads qualificados que foram para a Blocklist).")

        df_hist_recup = df_hist[df_hist['tipo_lead_envio'] == "Perdidos Redistribuídos"].copy()

        if df_hist_recup.empty:
            st.info("Nenhum malote de recuperação foi redistribuído e salvo na planilha até o momento.")
        else:
            telefones_bloq_dict = dict(zip(df_bloqueados['celular'].astype(str), df_bloqueados['motivo_cancelamento'])) if not df_bloqueados.empty else {}
            
            # CORREÇÃO DO ÍNDICE DUPLICADO: DEDUP SEGURO ANTES DE TRANSFORMAR EM DICIONÁRIO
            df_crm_unique = df.drop_duplicates(subset=['lead_key'], keep='last')
            crm_leads_dict = df_crm_unique.set_index('lead_key').to_dict('index') if not df_crm_unique.empty else {}

            def diagnosticar_resultado_retrabalho(row):
                key = str(row['lead_key'])
                cel = str(row['celular'])
                novo_dono = str(row['corretor_cobrado']).strip()
                orig_dono = str(row['corretor_original']).strip()

                # 1. Checa se o lead foi para a Blocklist (Base Limpa)
                if cel in telefones_bloq_dict:
                    motivo_b = telefones_bloq_dict[cel]
                    return pd.Series([
                        "🧹 Base Limpa (Blocklist)",
                        f"Descarte Qualificado por {novo_dono}: {motivo_b}",
                        "Limpeza de Base"
                    ])

                # 2. Checa no CRM se o lead avançou ou trocou de titularidade
                if key in crm_leads_dict:
                    crm_info = crm_leads_dict[key]
                    etapa_atual = str(crm_info.get('Etapa do Funil', '')).strip()
                    dono_crm_atual = str(crm_info.get('Corretor', '')).strip()

                    if etapa_atual not in ['Perdido', 'Visita Cancelada', 'Visita - Cliente Não Compareceu']:
                        return pd.Series([
                            "🎯 Resgatado com Sucesso!",
                            f"Saiu de {orig_dono} ➔ Foi para {novo_dono} (Etapa: {etapa_atual})",
                            "Resgate Ativo"
                        ])
                    elif dono_crm_atual == novo_dono and etapa_atual != 'Perdido':
                        return pd.Series([
                            "🎯 Transferido & Reativado",
                            f"Titularidade assumida por {novo_dono} no CRM",
                            "Resgate Ativo"
                        ])

                # 3. Retorno manual registrado
                fb = str(row.get('feedback_recuperacao', '')).strip()
                if fb not in ['None', 'N/A', 'Aguardando Retorno', '']:
                    return pd.Series([
                        f"💬 {fb}",
                        f"Retorno do corretor {novo_dono}",
                        "Em Andamento"
                    ])

                return pd.Series([
                    "⏳ Aguardando Retorno / Sem Ação",
                    f"Lead entregue para {novo_dono}, sem alteração no CRM ou Blocklist",
                    "Pendente"
                ])

            df_hist_recup[['Status_Retrabalho', 'Detalhes_Resultado', 'Categoria_Metrica']] = df_hist_recup.apply(diagnosticar_resultado_retrabalho, axis=1)

            total_redistribuido = len(df_hist_recup)
            total_resgatados = len(df_hist_recup[df_hist_recup['Categoria_Metrica'] == "Resgate Ativo"])
            total_limpos = len(df_hist_recup[df_hist_recup['Categoria_Metrica'] == "Limpeza de Base"])
            total_resolvidos = total_resgatados + total_limpos
            taxa_eficiencia = (total_resolvidos / total_redistribuido * 100) if total_redistribuido > 0 else 0

            m_r1, m_r2, m_r3, m_r4 = st.columns(4)
            m_r1.metric("Leads Perdidos Redistribuídos", total_redistribuido)
            m_r2.metric("🎯 Resgatados no CRM", total_resgatados, help="Saíram de Perdido e viraram Atendimento ou Visita")
            m_r3.metric("🧹 Base Limpa (Blocklist)", total_limpos, help="Corretor confirmou descarte definitivo e limpamos a base")
            m_r4.metric("Taxa de Resolução Real", f"{taxa_eficiencia:.1f}%", help="% de leads que saíram do limbo (Resgates + Limpeza)")

            st.markdown("---")

            # PLACAR POR CORRETOR DESTINATÁRIO
            st.markdown("### 🏆 Placar de Eficiência do Retrabalho por Corretor Destinatário")
            st.caption("Mede o aproveitamento de cada corretor ao receber listas de leads frios/perdidos.")

            placar_corretores = []
            for c_nome, c_grp in df_hist_recup.groupby('corretor_cobrado'):
                tot_c = len(c_grp)
                resg_c = len(c_grp[c_grp['Categoria_Metrica'] == "Resgate Ativo"])
                limp_c = len(c_grp[c_grp['Categoria_Metrica'] == "Limpeza de Base"])
                pend_c = len(c_grp[c_grp['Categoria_Metrica'] == "Pendente"])
                resolv_c = resg_c + limp_c
                taxa_c = (resolv_c / tot_c * 100) if tot_c > 0 else 0

                blocos = int(taxa_c // 10)
                barra_c = "█" * blocos + "░" * (10 - blocos)

                if taxa_c >= 50:
                    status_c = "🟢 Alta Resolução"
                elif taxa_c >= 25:
                    status_c = "🟡 Moderado"
                else:
                    status_c = "🔴 Fila Travada / Sem Retorno"

                placar_corretores.append({
                    'Novo Corretor (Destino)': c_nome,
                    'Desempenho': status_c,
                    'Eficiência': f"{barra_c} ({taxa_c:.0f}%)",
                    'Total Recebido': tot_c,
                    '🎯 Resgatados (CRM)': resg_c,
                    '🧹 Base Limpa (Blocklist)': limp_c,
                    '⏳ Ainda Sem Ação': pend_c,
                    '% Resolução': f"{taxa_c:.1f}%"
                })

            df_placar_view = pd.DataFrame(placar_corretores).sort_values(by='🎯 Resgatados (CRM)', ascending=False)
            st.dataframe(df_placar_view, use_container_width=True, hide_index=True)

            st.markdown("---")

            # AUDITORIA DETALHADA LEAD A LEAD
            st.markdown("### 🔍 Detalhamento Lead a Lead: O que aconteceu com cada contato?")
            
            corr_dest_filtro = st.selectbox(
                "Filtrar por Corretor que recebeu os leads:",
                ["Todos os Corretores"] + sorted(df_hist_recup['corretor_cobrado'].dropna().unique().tolist()),
                key="sel_filtro_recup_detalhe"
            )

            df_recup_view = df_hist_recup if corr_dest_filtro == "Todos os Corretores" else df_hist_recup[df_hist_recup['corretor_cobrado'] == corr_dest_filtro]

            cols_recup_show = [
                'nome', 'celular', 'corretor_original', 'corretor_cobrado',
                'data_ultima_cobranca', 'Status_Retrabalho', 'Detalhes_Resultado'
            ]
            df_recup_display = df_recup_view[cols_recup_show].rename(columns={
                'nome': 'Cliente',
                'celular': 'Celular',
                'corretor_original': 'Dono Anterior (Origem)',
                'corretor_cobrado': 'Novo Dono (Destino)',
                'data_ultima_cobranca': 'Data da Entrega',
                'Status_Retrabalho': 'Resultado Atual',
                'Detalhes_Resultado': 'Diagnóstico da Operação'
            })
            st.dataframe(df_recup_display, use_container_width=True, hide_index=True)

    # --- MÓDULO 7: COMPARADOR DE PLANILHAS ---
    elif modulo_ativo == "6. Comparador de Planilhas (Raio-X)":
        st.subheader("Raio-X de Modificações por Corretor (Planilha Anterior vs. Atual)")
        st.caption("Descubra exatamente quais alterações de etapa, novos contatos e anotações cada corretor realizou no CRM entre os dois relatórios.")

        if not arquivo_anterior:
            st.info("👉 Para visualizar as alterações detalhadas da equipe, faça o upload do relatório anterior no campo **'2. Relatório Anterior'** na barra lateral.")
        else:
            df_crm_ant = pd.read_excel(arquivo_anterior, sheet_name=0)
            df_ant = preparar_dataframe(df_crm_ant)

            colunas_ant_selecao = [
                'lead_key', 'Nome Cliente', 'Celular_Limpo', 'Etapa do Funil',
                'Último Contato em', 'Descrição Último Contato', 'Corretor', 'Motivo Perda'
            ]
            colunas_ant_presentes = [c for c in colunas_ant_selecao if c in df_ant.columns]

            df_comp = df.merge(
                df_ant[colunas_ant_presentes], 
                on='lead_key', 
                how='inner', 
                suffixes=('_atual', '_anterior')
            )

            def extrair_coluna(df_in, prefixo):
                if f"{prefixo}_atual" in df_in.columns:
                    return df_in[f"{prefixo}_atual"]
                elif prefixo in df_in.columns:
                    return df_in[prefixo]
                return pd.Series([""] * len(df_in))

            df_comp['Nome_Exibicao'] = extrair_coluna(df_comp, 'Nome Cliente')
            df_comp['Celular_Exibicao'] = extrair_coluna(df_comp, 'Celular_Limpo')
            df_comp['Corretor_Exibicao'] = extrair_coluna(df_comp, 'Corretor')

            def auditar_alteracao_detalhada(row):
                etapa_ant = str(row.get('Etapa do Funil_anterior', '')).strip()
                etapa_atu = str(row.get('Etapa do Funil_atual', row.get('Etapa do Funil', ''))).strip()
                contato_ant = str(row.get('Último Contato em_anterior', '')).strip()
                contato_atu = str(row.get('Último Contato em_atual', row.get('Último Contato em', ''))).strip()
                desc_ant = str(row.get('Descrição Último Contato_anterior', '')).strip()
                desc_atu = str(row.get('Descrição Último Contato_atual', row.get('Descrição Último Contato', ''))).strip()
                corretor_ant = str(row.get('Corretor_anterior', '')).strip()
                corretor_atu = str(row.get('Corretor_atual', row.get('Corretor', ''))).strip()

                mudou_etapa = (etapa_ant != etapa_atu and etapa_ant != "")
                mudou_contato = (contato_atu != contato_ant and contato_atu != "")
                mudou_desc = (desc_atu != desc_ant and desc_atu != "" and desc_atu != "Sem descrição registrada")
                mudou_corretor = (corretor_ant != corretor_atu and corretor_ant != "")

                if etapa_ant == 'Perdido' and etapa_atu != 'Perdido':
                    tipo = "🎯 Resgatado de Perdido"
                elif etapa_atu == 'Perdido' and etapa_ant != 'Perdido':
                    tipo = "❌ Arquivado como Perdido"
                elif mudou_etapa:
                    tipo = "🚀 Mudou de Etapa"
                elif mudou_contato or mudou_desc:
                    tipo = "📞 Novo Contato / Anotação"
                elif mudou_corretor:
                    tipo = "🔄 Troca de Corretor"
                else:
                    tipo = "💤 Estagnado (Sem Alteração)"

                detalhes = []
                if mudou_etapa:
                    detalhes.append(f"Etapa: '{etapa_ant}' ➔ '{etapa_atu}'")
                if mudou_contato:
                    detalhes.append(f"Novo contato em: {contato_atu}")
                if mudou_desc:
                    detalhes.append(f"Nova anotação: \"{desc_atu}\"")
                if mudou_corretor:
                    detalhes.append(f"Dono anterior: {corretor_ant}")

                resumo_txt = " | ".join(detalhes) if detalhes else "Nenhuma modificação registrada no CRM."
                return pd.Series([tipo, resumo_txt, (tipo != "💤 Estagnado (Sem Alteração)")])

            df_comp[['Tipo_Movimentacao', 'Resumo_Modificacao', 'Teve_Movimentacao']] = df_comp.apply(auditar_alteracao_detalhada, axis=1)

            total_leads_comparados = len(df_comp)
            total_com_mov = len(df_comp[df_comp['Teve_Movimentacao']])
            total_estagnados = len(df_comp[~df_comp['Teve_Movimentacao']])
            taxa_global_mov = (total_com_mov / total_leads_comparados * 100) if total_leads_comparados > 0 else 0

            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Leads Comparados", total_leads_comparados)
            p2.metric("Com Alteração / Contato", total_com_mov)
            p3.metric("Estagnados (Sem Ação)", total_estagnados, delta=f"-{total_estagnados}" if total_estagnados > 0 else "0", delta_color="inverse")
            p4.metric("Índice de Atividade", f"{taxa_global_mov:.1f}%")

            st.markdown("---")
            st.markdown("### 🏆 Placar de Produtividade por Corretor (Quem Mais Mexeu no CRM)")
            
            resumo_corretores_lista = []
            for c_nome, c_grp in df_comp.groupby('Corretor_Exibicao'):
                c_total = len(c_grp)
                c_mov = len(c_grp[c_grp['Teve_Movimentacao']])
                c_parados = len(c_grp[~c_grp['Teve_Movimentacao']])
                c_avancou = len(c_grp[c_grp['Tipo_Movimentacao'].str.contains("🚀|🎯")])
                c_contatos = len(c_grp[c_grp['Tipo_Movimentacao'].str.contains("📞")])
                c_perdidos = len(c_grp[c_grp['Tipo_Movimentacao'].str.contains("❌")])
                c_taxa = (c_mov / c_total * 100) if c_total > 0 else 0

                blocos = int(c_taxa // 10)
                c_barra = "█" * blocos + "░" * (10 - blocos)

                if c_taxa >= 50:
                    status_c = "🟢 Alta Atividade"
                elif c_taxa >= 25:
                    status_c = "🟡 Média Atividade"
                else:
                    status_c = "🔴 Inércia / Pouca Ação"

                resumo_corretores_lista.append({
                    'Corretor': c_nome,
                    'Nível de Ação': status_c,
                    'Atividade': f"{c_barra} ({c_taxa:.0f}%)",
                    'Total Carteira': c_total,
                    'Movimentados': c_mov,
                    'Estagnados': c_parados,
                    'Avanços de Etapa': c_avancou,
                    'Novas Anotações': c_contatos,
                    'Marcou Perdido': c_perdidos,
                    'Taxa de Movimentação': f"{c_taxa:.1f}%"
                })

            df_resumo_corretores = pd.DataFrame(resumo_corretores_lista).sort_values(by='Movimentados', ascending=False)
            st.dataframe(
                df_resumo_corretores[['Corretor', 'Nível de Ação', 'Atividade', 'Total Carteira', 'Movimentados', 'Estagnados', 'Avanços de Etapa', 'Novas Anotações', 'Marcou Perdido', 'Taxa de Movimentação']],
                use_container_width=True,
                hide_index=True
            )

            st.markdown("---")
            st.markdown("### 🔍 Raio-X Detalhado do Corretor (Feed de Ações)")
            
            col_f_c1, col_f_c2 = st.columns([1, 1])
            with col_f_c1:
                corretor_alvo_comp = st.selectbox(
                    "Escolha o Corretor para ver exatamente o que ele mudou:",
                    ["Todos os Corretores"] + sorted(df_comp['Corretor_Exibicao'].dropna().unique().tolist()),
                    key="sel_feed_corretor"
                )
            with col_f_c2:
                filtro_tipo_mov = st.selectbox(
                    "Filtrar tipo de ocorrência:",
                    ["Apenas Leads que Mudaram (Ativos)", "Apenas Leads Estagnados (Sem Ação)", "Todos os Leads"],
                    key="sel_feed_tipo"
                )

            df_feed = df_comp if corretor_alvo_comp == "Todos os Corretores" else df_comp[df_comp['Corretor_Exibicao'] == corretor_alvo_comp]

            if filtro_tipo_mov == "Apenas Leads que Mudaram (Ativos)":
                df_feed = df_feed[df_feed['Teve_Movimentacao']]
            elif filtro_tipo_mov == "Apenas Leads Estagnados (Sem Ação)":
                df_feed = df_feed[~df_feed['Teve_Movimentacao']]

            if df_feed.empty:
                st.info("Nenhum lead encontrado com os filtros selecionados.")
            else:
                st.markdown(f"**Exibindo {len(df_feed)} leads:**")

                df_feed_display = pd.DataFrame({
                    'Cliente': df_feed['Nome_Exibicao'],
                    'Celular': df_feed['Celular_Exibicao'],
                    'Corretor': df_feed['Corretor_Exibicao'],
                    'Diagnóstico': df_feed['Tipo_Movimentacao'],
                    'O Que Foi Modificado': df_feed['Resumo_Modificacao'],
                    'Etapa Anterior': df_feed.get('Etapa do Funil_anterior', ''),
                    'Etapa Atual': df_feed.get('Etapa do Funil_atual', df_feed.get('Etapa do Funil', '')),
                    'Última Anotação no CRM': df_feed.get('Descrição Último Contato_atual', df_feed.get('Descrição Último Contato', '')),
                    'Data do Último Contato': df_feed.get('Último Contato em_atual', df_feed.get('Último Contato em', ''))
                })
                st.dataframe(df_feed_display, use_container_width=True, hide_index=True)

    # --- MÓDULO 8: CENTRAL DE RELATÓRIOS ---
    elif modulo_ativo == "📑 Central de Relatórios":
        st.subheader("Central de Relatórios Executivos")
        st.caption("Gere visões personalizadas: uma voltada para o corretor acompanhar sua carteira e outra para a loteadora avaliar o ROI e funil macro.")

        sub_aba_corr, sub_aba_loteadora = st.tabs(["👤 Relatório do Corretor", "🏢 Relatório da Loteadora"])

        with sub_aba_corr:
            st.markdown("### 📋 Extrato de Carteira do Corretor")
            corr_rel = st.selectbox("Selecione o Corretor:", corretores_disponiveis, key="sel_rep_corr")
            df_c_rel = df[df['Corretor'] == corr_rel].copy()

            t_c_total = len(df_c_rel)
            t_c_1a = len(df_c_rel[df_c_rel['Tipo_Lead'] == "1. Aguardando 1ª Interação"])
            t_c_atend = len(df_c_rel[df_c_rel['Tipo_Lead'] == "2. Em Atendimento"])
            t_c_vis = len(df_c_rel[df_c_rel['Tipo_Lead'] == "3. Visitas & Fechamento"])
            t_c_parados = len(df_c_rel[df_c_rel['Faixa_Atraso'] == "Mais de 10 dias"])

            rc1, rc2, rc3, rc4 = st.columns(4)
            rc1.metric("Total em Carteira", t_c_total)
            rc2.metric("Em Atendimento", t_c_atend)
            rc3.metric("Visitas / Fechamentos", t_c_vis)
            rc4.metric("Parados há +10 dias", t_c_parados, delta=f"-{t_c_parados}" if t_c_parados > 0 else "0", delta_color="inverse")

            st.markdown(f"#### Detalhamento de Leads de {corr_rel}")
            cols_show_corr = ['Nome Cliente', 'Celular_Limpo', 'Etapa do Funil', 'Dias_Sem_Interacao', 'Último Contato em', 'Descrição Último Contato']
            df_corr_export = df_c_rel[cols_show_corr].rename(columns={'Celular_Limpo': 'Celular'})
            st.dataframe(df_corr_export, use_container_width=True, hide_index=True)

            buffer_corr = io.BytesIO()
            with pd.ExcelWriter(buffer_corr, engine='openpyxl') as writer:
                df_corr_export.to_excel(writer, index=False, sheet_name=f"Carteira_{corr_rel[:15]}")
            st.download_button(
                label=f"📥 Baixar Relatório de {corr_rel} (.xlsx)",
                data=buffer_corr.getvalue(),
                file_name=f"relatorio_corretor_{corr_rel.replace(' ', '_')}_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        with sub_aba_loteadora:
            st.markdown("### 🏢 Dossiê Estratégico para a Loteadora")
            st.caption("Composição de canais de marketing, taxa de conversão, volume financeiro e motivos de descarte.")

            tot_leads = len(df)
            tot_visitas_agend = len(df[df['Etapa do Funil'] == 'Visita Agendada'])
            tot_visitas_realiz = len(df[df['Etapa do Funil'] == 'Visita Realizada'])
            tot_vendas = len(df[df['Etapa do Funil'] == 'Negócio Fechado.'])
            tx_visita = ((tot_visitas_agend + tot_visitas_realiz) / tot_leads * 100) if tot_leads > 0 else 0
            tx_venda = (tot_vendas / tot_leads * 100) if tot_leads > 0 else 0

            rl1, rl2, rl3, rl4 = st.columns(4)
            rl1.metric("Leads Totais Captados", tot_leads)
            rl2.metric("Visitas (Agendadas + Feitas)", tot_visitas_agend + tot_visitas_realiz, f"{tx_visita:.1f}% conversão")
            rl3.metric("Negócios Fechados", tot_vendas, f"{tx_venda:.2f}% de vendas")
            
            if 'VGN (Em negociação)' in df.columns:
                def limpar_vgn(v):
                    if pd.isna(v): return 0.0
                    s = str(v).replace('.', '').replace(',', '.')
                    try: return float(s)
                    except: return 0.0
                vgn_soma = df['VGN (Em negociação)'].apply(limpar_vgn).sum()
                rl4.metric("Pipeline VGN Ativo", f"R$ {vgn_soma:,.2f}")
            else:
                rl4.metric("Pipeline VGN", "N/D")

            st.markdown("---")
            col_lot1, col_lot2 = st.columns([1, 1])

            with col_lot1:
                st.markdown("#### 📢 Desempenho por Canal de Mídia (Origem)")
                if 'Origem (Tipo Mídia)' in df.columns:
                    orig_grp = df.groupby('Origem (Tipo Mídia)').agg(
                        Total_Leads=('Nome Cliente', 'count'),
                        Visitas=('Etapa do Funil', lambda s: s.isin(['Visita Agendada', 'Visita Realizada', 'Negócio Fechado.']).sum())
                    ).reset_index()
                    orig_grp['% Conversão em Visita'] = (orig_grp['Visitas'] / orig_grp['Total_Leads'] * 100).map("{:.1f}%".format)
                    st.dataframe(orig_grp.sort_values(by='Total_Leads', ascending=False), use_container_width=True, hide_index=True)

            with col_lot2:
                st.markdown("#### 🎯 Desempenho por Campanha de Tráfego")
                if 'Campanha' in df.columns:
                    camp_grp = df.groupby('Campanha').agg(
                        Total_Leads=('Nome Cliente', 'count'),
                        Visitas=('Etapa do Funil', lambda s: s.isin(['Visita Agendada', 'Visita Realizada', 'Negócio Fechado.']).sum())
                    ).reset_index()
                    camp_grp['% Visita'] = (camp_grp['Visitas'] / camp_grp['Total_Leads'] * 100).map("{:.1f}%".format)
                    st.dataframe(camp_grp.sort_values(by='Total_Leads', ascending=False), use_container_width=True, hide_index=True)

            st.markdown("---")
            st.markdown("#### 🏆 Performance Geral dos Corretores para a Loteadora")
            perf_loteadora = df.groupby('Corretor').agg(
                Total_Recebido=('Nome Cliente', 'count'),
                Em_Atendimento=('Tipo_Lead', lambda s: (s == "2. Em Atendimento").sum()),
                Visitas=('Etapa do Funil', lambda s: s.isin(['Visita Agendada', 'Visita Realizada']).sum()),
                Vendas=('Etapa do Funil', lambda s: (s == 'Negócio Fechado.').sum()),
                Perdidos=('Etapa do Funil', lambda s: s.str.contains('Perdido').sum())
            ).reset_index()
            perf_loteadora['% Aproveitamento'] = ((perf_loteadora['Visitas'] + perf_loteadora['Vendas']) / perf_loteadora['Total_Recebido'] * 100).map("{:.1f}%".format)
            st.dataframe(perf_loteadora.sort_values(by='Visitas', ascending=False), use_container_width=True, hide_index=True)

            buffer_lot = io.BytesIO()
            with pd.ExcelWriter(buffer_lot, engine='openpyxl') as writer:
                perf_loteadora.to_excel(writer, index=False, sheet_name="Resumo_Corretores")
                if 'Origem (Tipo Mídia)' in df.columns:
                    orig_grp.to_excel(writer, index=False, sheet_name="Origem_Midia")
                total_perdas_lot = len(df[df['Motivo Perda'].notna() & (df['Motivo Perda'] != 'Não informado')])
                if total_perdas_lot > 0:
                    loss_counts = df[df['Motivo Perda'].notna() & (df['Motivo Perda'] != 'Não informado')]['Motivo Perda'].value_counts().reset_index()
                    loss_counts.columns = ['Motivo de Perda', 'Quantidade']
                    loss_counts.to_excel(writer, index=False, sheet_name="Motivos_Perda")
            st.download_button(
                label="📥 Baixar Dossiê Executivo da Loteadora (.xlsx)",
                data=buffer_lot.getvalue(),
                file_name=f"dossie_executivo_loteadora_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    # --- MÓDULO 9: BLOQUEIO DE LEADS ---
    elif modulo_ativo == "🚫 Bloqueio de Leads":
        st.subheader("Bloqueio de Leads (Remover Definitivamente da Base / Retrabalho)")
        st.caption("Use esta área para cancelar leads que informaram que acharam caro, não gostaram da localização, já compraram de concorrente ou pediram para não ser contatados.")

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
                    "Achou o valor alto / Fora do orçamento",
                    "Não gostou da localização / Muito longe",
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
