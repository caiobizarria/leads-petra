import streamlit as st
import streamlit.components.v1 as components
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import datetime
import re
import json
import io

st.set_page_config(page_title="Gestão Comercial & Retrabalho de Leads", layout="wide")

# CSS para layout limpo
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
    val_str = str(val).strip()
    if val_str.endswith('.0'):
        val_str = val_str[:-2]
    digits = re.sub(r'\D', '', val_str)
    
    if digits.startswith('0') and len(digits) in [11, 12]:
        digits = digits[1:]
        
    if digits.startswith('55') and len(digits) in [12, 13]:
        digits = digits[2:]
        
    return digits

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

def classificar_etapa_simples(etapa_str):
    etapa_str = str(etapa_str).strip()
    if etapa_str in ['Em Tentativa', 'Lead na Base']:
        return "Em Tentativa"
    elif 'Em Atendimento' in etapa_str:
        return "Em Atendimento"
    elif etapa_str == 'Visita Agendada':
        return "Visita Agendada"
    elif etapa_str == 'Visita Realizada':
        return "Visita Realizada"
    return None

def parse_data_segura(val):
    if pd.isna(val) or str(val).strip() == "":
        return None
    try:
        return pd.to_datetime(val, dayfirst=True)
    except:
        return None

def preparar_dataframe(df_raw, data_referencia=None):
    df = df_raw.copy()
    df['Celular_Limpo'] = df['Celular Cliente'].apply(limpar_celular)
    df['Recebido_Str'] = df['Recebido em'].astype(str)
    df['lead_key'] = df['Celular_Limpo'] + "_" + df['Recebido_Str']
    df['Descrição Último Contato'] = df['Descrição Último Contato'].fillna("Sem descrição registrada")
    df['Motivo Perda'] = df['Motivo Perda'].fillna("Não informado")
    df['Tipo_Lead'] = df.apply(classificar_tipo, axis=1)
    df['Etapa_Macro'] = df['Etapa do Funil'].apply(classificar_etapa_simples)
    
    df['Recebido_DT'] = pd.to_datetime(df['Recebido em'], dayfirst=True, errors='coerce')
    df['Ultimo_Contato_DT'] = pd.to_datetime(df['Último Contato em'], dayfirst=True, errors='coerce')
    df['Primeiro_Contato_DT'] = pd.to_datetime(df['Data Primeiro Contato'], dayfirst=True, errors='coerce')
    df['Perdido_DT'] = pd.to_datetime(df['Negócio Perdido em'], dayfirst=True, errors='coerce')

    df['Data_Referencia_Lead'] = df['Ultimo_Contato_DT'].combine_first(df['Recebido_DT'])

    if data_referencia is None:
        data_referencia = pd.Timestamp.now()
    else:
        data_referencia = pd.to_datetime(data_referencia)

    dias_calculados = (data_referencia - df['Data_Referencia_Lead']).dt.days
    df['Dias_Sem_Interacao'] = dias_calculados.fillna(999).clip(lower=0).astype(int)

    def faixa_dias_exata(d):
        if d <= 3:
            return "0 a 3 dias"
        elif 4 <= d <= 10:
            return "4 a 10 dias"
        else:
            return "Mais de 10 dias"

    df['Faixa_Atraso'] = df['Dias_Sem_Interacao'].apply(faixa_dias_exata)
    return df

st.title("Gestão Comercial & Retrabalho de Leads")

# --- BARRA LATERAL ---
st.sidebar.markdown("### 📁 Relatórios do CRM")
arquivo_atual = st.sidebar.file_uploader("1. Relatório Atual / Mais Recente (.xlsx)", type=["xlsx"])
arquivo_anterior = st.sidebar.file_uploader("2. Relatório Anterior (Opcional p/ Comparar)", type=["xlsx"])

st.sidebar.markdown("---")
st.sidebar.markdown("### ⏱️ Base de Cálculo do Atraso")
tipo_base_data = st.sidebar.radio(
    "Calcular dias sem contato em relação a:",
    ["Data de Hoje", "Data Mais Recente do Arquivo"],
    index=0
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📌 Módulos do Sistema")

OPCOES_MODULOS = [
    "📊 Visão Geral da Carteira",
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
    
    if tipo_base_data == "Data Mais Recente do Arquivo":
        dts = pd.to_datetime(df_crm_atual['Último Contato em'], dayfirst=True, errors='coerce').dropna()
        ref_dt = dts.max() if not dts.empty else pd.Timestamp.now()
    else:
        ref_dt = pd.Timestamp.now()

    df = preparar_dataframe(df_crm_atual, data_referencia=ref_dt)

    df_hist = get_historico()
    if not df_hist.empty:
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

    # --- MÓDULO 1: VISÃO GERAL REFORMULADA (MACRO PRIMEIRO, DETALHES DEPOIS) ---
    if modulo_ativo == "📊 Visão Geral da Carteira":
        st.subheader("Panorama Comercial da Carteira Ativa")
        st.caption("Visão consolidada por corretor, separando Em Tentativa, Em Atendimento e Visitas.")

        df_ativos_funil = df[df['Etapa_Macro'].notna() & (~df['Lead_Bloqueado'])].copy()

        # 1. RESUMO EXECUTIVO DO TOPO
        t_tent = len(df_ativos_funil[df_ativos_funil['Etapa_Macro'] == "Em Tentativa"])
        t_atend = len(df_ativos_funil[df_ativos_funil['Etapa_Macro'] == "Em Atendimento"])
        t_vagend = len(df_ativos_funil[df_ativos_funil['Etapa_Macro'] == "Visita Agendada"])
        t_vrealiz = len(df_ativos_funil[df_ativos_funil['Etapa_Macro'] == "Visita Realizada"])
        t_total_ativo = len(df_ativos_funil)

        c_top1, c_top2, c_top3, c_top4, c_top5 = st.columns(5)
        c_top1.metric("1. Em Tentativa", t_tent)
        c_top2.metric("2. Em Atendimento", t_atend)
        c_top3.metric("3. Visitas Agendadas", t_vagend)
        c_top4.metric("4. Visitas Realizadas", t_vrealiz)
        c_top5.metric("Total Carteira Ativa", t_total_ativo)

        st.markdown("---")

        # 2. TABELA MACRO LIMPA: TOTAIS POR CORRETOR (EXATAMENTE COMO PEDIDO)
        st.markdown("### 📋 1. Totais por Corretor (Visão Geral Limpa)")
        st.caption("Enxergue primeiro os volumes totais de cada corretor em Tentativa e Atendimento:")

        tabela_macro_dados = []
        for corr in sorted(df_ativos_funil['Corretor'].dropna().unique()):
            df_c = df_ativos_funil[df_ativos_funil['Corretor'] == corr]
            tabela_macro_dados.append({
                'Corretor': corr,
                'Em Tentativa (Total)': len(df_c[df_c['Etapa_Macro'] == "Em Tentativa"]),
                'Em Atendimento (Total)': len(df_c[df_c['Etapa_Macro'] == "Em Atendimento"]),
                'Visitas Agendadas': len(df_c[df_c['Etapa_Macro'] == "Visita Agendada"]),
                'Visitas Realizadas': len(df_c[df_c['Etapa_Macro'] == "Visita Realizada"]),
                'Total Ativos': len(df_c)
            })

        df_macro_tabela = pd.DataFrame(tabela_macro_dados).sort_values(by='Total Ativos', ascending=False)
        st.dataframe(df_macro_tabela, use_container_width=True, hide_index=True)

        st.markdown("---")

        # 3. SEGUNDO PASSO: DETALHAMENTO DA ETAPA E TEMPO (0 a 3, 4 a 10, +10 dias)
        st.markdown("### 🔍 2. Detalhar Etapa e Tempo Sem Contato")
        st.caption("Escolha a etapa que você quer abrir para ver a divisão de tempo (0 a 3 dias, 4 a 10 dias e mais de 10 dias) de cada corretor.")

        etapa_escolhida_detalhe = st.radio(
            "Selecione a etapa para ver a quebra por dias:",
            ["Em Tentativa", "Em Atendimento", "Visitas (Agendadas + Realizadas)"],
            horizontal=True
        )

        if etapa_escolhida_detalhe == "Visitas (Agendadas + Realizadas)":
            df_etapa_sub = df_ativos_funil[df_ativos_funil['Etapa_Macro'].isin(["Visita Agendada", "Visita Realizada"])].copy()
        else:
            df_etapa_sub = df_ativos_funil[df_ativos_funil['Etapa_Macro'] == etapa_escolhida_detalhe].copy()

        # Cards do tempo para a etapa selecionada
        n_0_3 = len(df_etapa_sub[df_etapa_sub['Faixa_Atraso'] == "0 a 3 dias"])
        n_4_10 = len(df_etapa_sub[df_etapa_sub['Faixa_Atraso'] == "4 a 10 dias"])
        n_mais_10 = len(df_etapa_sub[df_etapa_sub['Faixa_Atraso'] == "Mais de 10 dias"])

        col_t1, col_t2, col_t3 = st.columns(3)
        col_t1.metric(f"{etapa_escolhida_detalhe}: 0 a 3 dias (Em Dia)", n_0_3)
        col_t2.metric(f"{etapa_escolhida_detalhe}: 4 a 10 dias (Atenção)", n_4_10)
        col_t3.metric(f"{etapa_escolhida_detalhe}: Mais de 10 dias (Crítico)", n_mais_10, delta=f"-{n_mais_10}" if n_mais_10 > 0 else "0", delta_color="inverse")

        # Tabela por Corretor na Etapa Selecionada
        tabela_tempo_corretores = []
        for corr in sorted(df_etapa_sub['Corretor'].dropna().unique()):
            df_c_etapa = df_etapa_sub[df_etapa_sub['Corretor'] == corr]
            tabela_tempo_corretores.append({
                'Corretor': corr,
                '0 a 3 dias': len(df_c_etapa[df_c_etapa['Faixa_Atraso'] == "0 a 3 dias"]),
                '4 a 10 dias': len(df_c_etapa[df_c_etapa['Faixa_Atraso'] == "4 a 10 dias"]),
                'Mais de 10 dias': len(df_c_etapa[df_c_etapa['Faixa_Atraso'] == "Mais de 10 dias"]),
                'Total na Etapa': len(df_c_etapa)
            })

        df_tempo_view = pd.DataFrame(tabela_tempo_corretores).sort_values(by='Mais de 10 dias', ascending=False)
        st.dataframe(df_tempo_view, use_container_width=True, hide_index=True)

        # 4. LISTA NOMINAL DOS LEADS COM FILTRO DIRETO
        st.markdown(f"#### 👤 Ver Leads Individuais de **{etapa_escolhida_detalhe}**")
        col_f_c1, col_f_c2 = st.columns(2)
        with col_f_c1:
            filtro_corr_drill = st.selectbox("Escolha o Corretor:", ["Todos os Corretores"] + sorted(df_etapa_sub['Corretor'].dropna().unique().tolist()), key="sel_corr_drill_list")
        with col_f_c2:
            filtro_faixa_drill = st.selectbox("Escolha a Faixa de Atraso:", ["Todas as Faixas", "Mais de 10 dias (Apenas Críticos)", "4 a 10 dias", "0 a 3 dias"], key="sel_faixa_drill_list")

        df_drill_final = df_etapa_sub.copy()
        if filtro_corr_drill != "Todos os Corretores":
            df_drill_final = df_drill_final[df_drill_final['Corretor'] == filtro_corr_drill]

        if filtro_faixa_drill == "Mais de 10 dias (Apenas Críticos)":
            df_drill_final = df_drill_final[df_drill_final['Faixa_Atraso'] == "Mais de 10 dias"]
        elif filtro_faixa_drill != "Todas as Faixas":
            df_drill_final = df_drill_final[df_drill_final['Faixa_Atraso'] == filtro_faixa_drill]

        st.caption(f"Mostrando {len(df_drill_final)} leads:")
        cols_show_det = ['Nome Cliente', 'Celular_Limpo', 'Corretor', 'Etapa do Funil', 'Dias_Sem_Interacao', 'Faixa_Atraso', 'Último Contato em', 'Descrição Último Contato']
        st.dataframe(df_drill_final[cols_show_det].rename(columns={
            'Nome Cliente': 'Cliente',
            'Celular_Limpo': 'Celular',
            'Dias_Sem_Interacao': 'Dias Parado',
            'Descrição Último Contato': 'Última Anotação'
        }), use_container_width=True, hide_index=True)

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
        c2.metric("4 a 10 dias", len(dados[dados['Faixa_Atraso'] == "4 a 10 dias"]))
        c3.metric("Mais de 10 dias", len(dados[dados['Faixa_Atraso'] == "Mais de 10 dias"]))
        c4.metric("Já Cobrados", len(dados[dados['Status_Cobranca'] == "Já Cobrado/Passado"]))

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filtro_faixa = st.multiselect("Filtrar Faixa de Dias:", ["0 a 3 dias", "4 a 10 dias", "Mais de 10 dias"], default=["4 a 10 dias", "Mais de 10 dias"], key=f"faixa_{chave_aba}")
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
        st.dataframe(malote_atual[['Nome Cliente', 'Celular_Limpo', 'Etapa do Funil', 'Dias_Sem_Interacao', 'Faixa_Atraso', 'Último Contato em', 'Descrição Último Contato', 'Status_Cobranca']], use_container_width=True)

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
        c2.metric("4 a 10 dias", len(df_perdidos_ativos[df_perdidos_ativos['Faixa_Atraso'] == "4 a 10 dias"]))
        c3.metric("Mais de 10 dias", len(df_perdidos_ativos[df_perdidos_ativos['Faixa_Atraso'] == "Mais de 10 dias"]))
        c4.metric("Já Redistribuídos", len(df_perdidos_ativos[df_perdidos_ativos['Status_Cobranca'] == "Já Cobrado/Passado"]))

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filtro_faixa = st.multiselect("Filtrar Faixa de Dias da Perda:", ["0 a 3 dias", "4 a 10 dias", "Mais de 10 dias"], default=["4 a 10 dias", "Mais de 10 dias"], key="faixa_perdidos")
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
                    st.dataframe(df_exibicao[['Nome Cliente', 'Celular_Limpo', 'Corretor Original (Dono Anterior)', 'Motivo Perda', 'Dias_Sem_Interacao', 'Faixa_Atraso', 'Descrição Último Contato']], use_container_width=True)
                else:
                    st.warning(f"Sem novos leads disponíveis para redistribuir para **{novo_destinatario}**.")

    # --- MÓDULO 5: AUDITORIA DE COBRANÇA DE CARTEIRA ---
    elif modulo_ativo == "🎯 Auditoria: Cobrança de Carteira":
        st.subheader("Auditoria de Cobrança de Carteira: Evolução Real de Status")
        st.caption("Cruzamos todos os leads cobrados salvos no Google Sheets com o relatório atual do CRM para ver exatamente quem mudou de etapa e quem continua parado.")

        df_cobrados_base = df_hist[df_hist['tipo_lead_envio'] != "Perdidos Redistribuídos"].copy()

        if df_cobrados_base.empty:
            st.info("Nenhum registro de cobrança de carteira localizado na planilha do Google Sheets até o momento.")
        else:
            df_crm_map = df.drop_duplicates(subset=['lead_key'], keep='last').set_index('lead_key').to_dict('index')

            def auditar_evolucao_cobranca(row):
                key = str(row['lead_key'])
                etapa_ao_cobrar = str(row.get('etapa_ao_enviar', '')).strip()
                data_cobranca_str = str(row.get('data_ultima_cobranca', '')).strip()
                dt_cobranca = parse_data_segura(data_cobranca_str)

                if key in df_crm_map:
                    info_crm = df_crm_map[key]
                    etapa_atual_crm = str(info_crm.get('Etapa do Funil', '')).strip()
                    dt_contato_crm = info_crm.get('Ultimo_Contato_DT')
                    desc_crm = str(info_crm.get('Descrição Último Contato', '')).strip()

                    teve_contato_depois = False
                    if dt_cobranca and pd.notna(dt_contato_crm):
                        if dt_contato_crm > dt_cobranca:
                            teve_contato_depois = True

                    if etapa_ao_cobrar != "" and etapa_atual_crm != etapa_ao_cobrar:
                        if etapa_atual_crm in ['Perdido', 'Visita Cancelada']:
                            diag = "❌ Marcado como Perdido no CRM"
                        elif etapa_atual_crm in ['Visita Agendada', 'Visita Realizada', 'Negócio Fechado.']:
                            diag = "🎯 Avançou para Visita / Fechamento!"
                        else:
                            diag = "🚀 Avançou de Etapa no CRM"
                        mudou_status = "Sim (Mudou de Etapa)"
                    elif teve_contato_depois:
                        diag = "📞 Novo Contato Feito (Mesma Etapa)"
                        mudou_status = "Sim (Novo Contato)"
                    else:
                        diag = "⚠️ Parado / Sem Alteração de Status"
                        mudou_status = "Não (Parado)"

                    return pd.Series([
                        etapa_atual_crm,
                        mudou_status,
                        diag,
                        f"De: '{etapa_ao_cobrar}' ➔ Para: '{etapa_atual_crm}'",
                        str(info_crm.get('Último Contato em', '')),
                        desc_crm
                    ])
                else:
                    return pd.Series([
                        "Não encontrado no CRM atual",
                        "Desconhecido",
                        "❓ Lead não localizado no arquivo subido",
                        "Sem dados",
                        "-",
                        "-"
                    ])

            df_cobrados_base[[
                'Etapa_Atual_CRM', 'Alterou_Status', 'Diagnóstico_Auditoria',
                'Evolucao_Texto', 'Data_Ultimo_Contato_CRM', 'Anotacao_CRM'
            ]] = df_cobrados_base.apply(auditar_evolucao_cobranca, axis=1)

            total_cobrancas = len(df_cobrados_base)
            total_mudaram = len(df_cobrados_base[df_cobrados_base['Alterou_Status'].str.startswith("Sim")])
            total_parados = len(df_cobrados_base[df_cobrados_base['Alterou_Status'].str.startswith("Não")])
            taxa_evolucao = (total_mudaram / total_cobrancas * 100) if total_cobrancas > 0 else 0

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Leads Cobrados", total_cobrancas)
            k2.metric("Com Alteração de Status", total_mudaram, f"{taxa_evolucao:.1f}% da lista")
            k3.metric("Sem Nenhuma Alteração", total_parados, delta=f"-{total_parados}" if total_parados > 0 else "0", delta_color="inverse")
            k4.metric("Efetividade da Cobrança", f"{taxa_evolucao:.1f}%")

            st.markdown("---")

            st.markdown("### 🏆 Comparativo de Resposta por Corretor Cobrado")
            resumo_corretores_cob = []
            for corr, grp in df_cobrados_base.groupby('corretor_cobrado'):
                tot_corr = len(grp)
                mud_corr = len(grp[grp['Alterou_Status'].str.startswith("Sim")])
                par_corr = len(grp[grp['Alterou_Status'].str.startswith("Não")])
                tx_corr = (mud_corr / tot_corr * 100) if tot_corr > 0 else 0

                blocos = int(tx_corr // 10)
                barra_txt = "█" * blocos + "░" * (10 - blocos)

                resumo_corretores_cob.append({
                    'Corretor': corr,
                    'Taxa de Resposta': f"{barra_txt} ({tx_corr:.0f}%)",
                    'Total Cobrado': tot_corr,
                    'Alterou Status': mud_corr,
                    'Continuam Parados': par_corr,
                    '% Eficiência': f"{tx_corr:.1f}%"
                })

            df_resumo_c_view = pd.DataFrame(resumo_corretores_cob).sort_values(by='Continuam Parados', ascending=False)
            st.dataframe(df_resumo_c_view, use_container_width=True, hide_index=True)

            st.markdown("---")

            st.markdown("### 🔍 Detalhamento: O que mudou em cada lead cobrado?")
            
            col_fc1, col_fc2 = st.columns(2)
            with col_fc1:
                filtro_corr_view = st.selectbox(
                    "Filtrar por Corretor:",
                    ["Todos os Corretores"] + sorted(df_cobrados_base['corretor_cobrado'].dropna().unique().tolist()),
                    key="sel_f_corr_cart"
                )
            with col_fc2:
                filtro_status_view = st.selectbox(
                    "Filtrar por Resposta do Lead:",
                    ["Todos os Leads Cobrados", "Apenas que Mudaram de Status", "Apenas que NÃO Mudaram (Parados)"],
                    key="sel_f_stat_cart"
                )

            df_view_tabela = df_cobrados_base.copy()
            if filtro_corr_view != "Todos os Corretores":
                df_view_tabela = df_view_tabela[df_view_tabela['corretor_cobrado'] == filtro_corr_view]

            if filtro_status_view == "Apenas que Mudaram de Status":
                df_view_tabela = df_view_tabela[df_view_tabela['Alterou_Status'].str.startswith("Sim")]
            elif filtro_status_view == "Apenas que NÃO Mudaram (Parados)":
                df_view_tabela = df_view_tabela[df_view_tabela['Alterou_Status'].str.startswith("Não")]

            if df_view_tabela.empty:
                st.info("Nenhum lead localizado nos filtros selecionados.")
            else:
                if filtro_corr_view != "Todos os Corretores" and filtro_status_view == "Apenas que NÃO Mudaram (Parados)":
                    msg_reinc = f"Olá, *{filtro_corr_view}*! Tudo bem?\n\nIdentificamos que estes leads cobrados anteriormente continuam *sem nenhuma alteração de etapa ou novo contato* no sistema:\n\n"
                    for _, r in df_view_tabela.head(15).iterrows():
                        msg_reinc += f"• *{r['nome']}* - {r['celular']} (Parado em: {r['etapa_ao_enviar']})\n"
                    msg_reinc += "\nConsegue dar um retorno sobre eles hoje? Obrigado!"
                    render_botao_copiar(msg_reinc, f"📋 Copiar Cobrança de Reincidência para {filtro_corr_view}")

                cols_display_final = [
                    'nome', 'celular', 'corretor_cobrado', 'data_ultima_cobranca',
                    'etapa_ao_enviar', 'Etapa_Atual_CRM', 'Diagnóstico_Auditoria',
                    'Data_Ultimo_Contato_CRM', 'Anotacao_CRM'
                ]
                df_tab_show = df_view_tabela[cols_display_final].rename(columns={
                    'nome': 'Cliente',
                    'celular': 'Celular',
                    'corretor_cobrado': 'Corretor',
                    'data_ultima_cobranca': 'Data da Cobrança',
                    'etapa_ao_enviar': 'Etapa ao Cobrar',
                    'Etapa_Atual_CRM': 'Etapa Atual no CRM',
                    'Diagnóstico_Auditoria': 'Status da Cobrança',
                    'Data_Ultimo_Contato_CRM': 'Data Último Contato CRM',
                    'Anotacao_CRM': 'Anotação no CRM'
                })
                st.dataframe(df_tab_show, use_container_width=True, hide_index=True)

    # --- MÓDULO 6: AUDITORIA DA FILA DE RECUPERAÇÃO (BLOCKLIST + RESGATES) ---
    elif modulo_ativo == "🔄 Auditoria: Fila de Recuperação (Blocklist + Resgates)":
        st.subheader("Métrica de Ouro: Eficiência do Retrabalho por Corretor")
        st.caption("Avalia o retorno real dos leads perdidos redistribuídos: 1) Resgates vivos (viraram Atendimento/Visita no CRM); 2) Base limpa (leads qualificados que foram para a Blocklist).")

        df_hist_recup = df_hist[df_hist['tipo_lead_envio'] == "Perdidos Redistribuídos"].copy()

        if df_hist_recup.empty:
            st.info("Nenhum malote de recuperação foi redistribuído e salvo na planilha até o momento.")
        else:
            telefones_bloq_dict = dict(zip(df_bloqueados['celular'].astype(str), df_bloqueados['motivo_cancelamento'])) if not df_bloqueados.empty else {}
            df_crm_unique = df.drop_duplicates(subset=['lead_key'], keep='last')
            crm_leads_dict = df_crm_unique.set_index('lead_key').to_dict('index') if not df_crm_unique.empty else {}

            def diagnosticar_resultado_retrabalho(row):
                key = str(row['lead_key'])
                cel = str(row['celular'])
                novo_dono = str(row['corretor_cobrado']).strip()
                orig_dono = str(row['corretor_original']).strip()

                if cel in telefones_bloq_dict:
                    motivo_b = telefones_bloq_dict[cel]
                    return pd.Series([
                        "🧹 Base Limpa (Blocklist)",
                        f"Descarte Qualificado por {novo_dono}: {motivo_b}",
                        "Limpeza de Base"
                    ])

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
            m_r2.metric("🎯 Resgatados no CRM", total_resgatados)
            m_r3.metric("🧹 Base Limpa (Blocklist)", total_limpos)
            m_r4.metric("Taxa de Resolução Real", f"{taxa_eficiencia:.1f}%")

            st.markdown("---")

            st.markdown("### 🏆 Placar de Eficiência do Retrabalho por Corretor Destinatário")
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

            st.markdown("### 🔍 Detalhamento Lead a Lead")
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
            df_ant = preparar_dataframe(df_crm_ant, data_referencia=ref_dt)

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
            cols_show_corr = ['Nome Cliente', 'Celular_Limpo', 'Etapa do Funil', 'Dias_Sem_Interacao', 'Faixa_Atraso', 'Último Contato em', 'Descrição Último Contato']
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
