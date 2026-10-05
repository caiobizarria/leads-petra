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
COLS_INVESTIDORES = ['celular', 'nome', 'corretor', 'observacao', 'data_registro']

MOTIVOS_DESCARTE_REAL = [
    "Achou o valor alto / Fora do orçamento",
    "Não gostou da localização / Muito longe",
    "Já comprou de concorrente",
    "Pediu para não entrar em contato",
    "Número errado / Inexistente",
    "Sem interesse definitivo",
    "Outro motivo"
]

PALAVRAS_INVESTIDOR = ['invest', 'investidor', 'investimento', 'investir', 'rentabilidade', 'locação', 'construir para vender']

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

def get_leads_investidores():
    return carregar_aba("leads_investidores", COLS_INVESTIDORES)

def registrar_investidor_db(celular, nome, corretor, observacao):
    df_inv = carregar_aba("leads_investidores", COLS_INVESTIDORES)
    agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    novo = pd.DataFrame([{
        'celular': str(celular),
        'nome': str(nome),
        'corretor': str(corretor),
        'observacao': str(observacao),
        'data_registro': agora
    }])
    if df_inv.empty:
        df_final = novo
    else:
        df_inv['celular'] = df_inv['celular'].astype(str)
        df_final = pd.concat([df_inv[df_inv['celular'] != str(celular)], novo], ignore_index=True)
    conn.update(worksheet="leads_investidores", data=df_final)

def remover_investidor_db(celular):
    df_inv = carregar_aba("leads_investidores", COLS_INVESTIDORES)
    if not df_inv.empty:
        df_inv['celular'] = df_inv['celular'].astype(str)
        df_final = df_inv[df_inv['celular'] != str(celular)]
        conn.update(worksheet="leads_investidores", data=df_final)

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

def atualizar_feedback_recuperacao(lead_key_ou_cel, novo_status):
    df_atual = carregar_aba("controle_envios", COLS_ENVIOS)
    if not df_atual.empty:
        df_atual['lead_key'] = df_atual['lead_key'].astype(str)
        df_atual['celular'] = df_atual['celular'].astype(str)
        mask = (df_atual['lead_key'] == str(lead_key_ou_cel)) | (df_atual['celular'] == str(lead_key_ou_cel))
        if mask.any():
            df_atual.loc[mask, 'feedback_recuperacao'] = novo_status
            conn.update(worksheet="controle_envios", data=df_atual)

def registrar_status_lead_db(celular, nome, motivo):
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

    if motivo == "🎯 Cliente resgatado em contato com corretor":
        atualizar_feedback_recuperacao(celular, "🎯 Resgatado em Contato com Corretor")
    else:
        atualizar_feedback_recuperacao(celular, f"❌ Descartado: {motivo}")

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
        ✅ Copiado com sucesso para sua área de transferência!
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
    elif 'Perdido' in etapa_str or etapa_str in ['Visita Cancelada', 'Visita - Cliente Não Compareceu']:
        return "Perdido"
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

    # Detecção automática de palavras de investidor nas anotações
    def checar_investidor_auto(row):
        texto = (str(row.get('Descrição Último Contato', '')) + " " + str(row.get('Campanha', '')) + " " + str(row.get('Observações Perda', ''))).lower()
        for p in PALAVRAS_INVESTIDOR:
            if p in texto:
                return True
        return False

    df['Investidor_Detectado_Auto'] = df.apply(checar_investidor_auto, axis=1)
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
    "💎 Radar de Investidores",
    "📑 Central de Relatórios (Corretores & Loteadora)",
    "⚡ Movimentações & Leads por Data",
    "1. Aguardando 1ª Interação (Em Tentativa)", 
    "2. Em Atendimento", 
    "3. Visitas & Fechamento",
    "4. Fila de Recuperação (Redistribuir)",
    "🎯 Auditoria: Cobrança de Carteira",
    "🔄 Auditoria: Fila de Recuperação (Blocklist + Resgates)",
    "6. Comparador de Planilhas (Raio-X)",
    "🚫 Gestão de Retornos & Bloqueio de Leads"
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
    
    # IDENTIFICAÇÃO DE RESGATADOS, INVESTIDORES E BLOQUEADOS
    df_bloqueados = get_leads_bloqueados()
    if not df_bloqueados.empty:
        df_bloqueados_reais = df_bloqueados[df_bloqueados['motivo_cancelamento'].isin(MOTIVOS_DESCARTE_REAL)]
        telefones_bloqueados = set(df_bloqueados_reais['celular'].dropna().astype(str).tolist())
        
        df_resgatados_reais = df_bloqueados[df_bloqueados['motivo_cancelamento'] == "🎯 Cliente resgatado em contato com corretor"]
        telefones_resgatados = set(df_resgatados_reais['celular'].dropna().astype(str).tolist())
    else:
        telefones_bloqueados = set()
        telefones_resgatados = set()

    df_inv_db = get_leads_investidores()
    telefones_investidores_manuais = set(df_inv_db['celular'].dropna().astype(str).tolist()) if not df_inv_db.empty else set()

    df['Lead_Bloqueado'] = df['Celular_Limpo'].astype(str).isin(telefones_bloqueados)
    df['Lead_Resgatado'] = df['Celular_Limpo'].astype(str).isin(telefones_resgatados)
    df['Lead_Investidor_Manual'] = df['Celular_Limpo'].astype(str).isin(telefones_investidores_manuais)
    df['Perfil_Investidor'] = df['Lead_Investidor_Manual'] | df['Investidor_Detectado_Auto']

    def ajustar_etapa_com_resgate(row):
        if row['Lead_Resgatado']:
            return "🎯 Resgatado em Contato"
        return row['Etapa_Macro']

    df['Etapa_Ativa_Final'] = df.apply(ajustar_etapa_com_resgate, axis=1)

    def definir_corretor_ativo(row):
        if row['Lead_Resgatado'] and pd.notna(row.get('corretor_cobrado')) and str(row.get('corretor_cobrado')).strip() != "":
            return str(row['corretor_cobrado']).strip()
        return str(row.get('Corretor', '')).strip()

    df['Corretor_Ativo'] = df.apply(definir_corretor_ativo, axis=1)
    corretores_disponiveis = sorted([c for c in df['Corretor_Ativo'].dropna().unique() if str(c).strip() != ""])

    df_ant = None
    if arquivo_anterior:
        try:
            df_crm_ant = pd.read_excel(arquivo_anterior, sheet_name=0)
            df_ant = preparar_dataframe(df_crm_ant, data_referencia=ref_dt)
        except Exception:
            df_ant = None

    # --- MÓDULO 1: VISÃO GERAL ---
    if modulo_ativo == "📊 Visão Geral da Carteira":
        st.subheader("Panorama Comercial da Carteira & Base Total")
        st.caption("Visão macro consolidada por corretor: Em Tentativa, Em Atendimento, Visitas, Resgatados e Leads Perdidos.")

        df_ativos_funil = df[df['Etapa_Ativa_Final'].isin(["Em Tentativa", "Em Atendimento", "Visita Agendada", "Visita Realizada", "🎯 Resgatado em Contato"]) & (~df['Lead_Bloqueado'])].copy()
        df_perdidos_total = df[df['Etapa_Ativa_Final'] == "Perdido"].copy()

        total_geral_base = len(df)
        t_tent = len(df_ativos_funil[df_ativos_funil['Etapa_Ativa_Final'] == "Em Tentativa"])
        t_atend = len(df_ativos_funil[df_ativos_funil['Etapa_Ativa_Final'] == "Em Atendimento"])
        t_vagend = len(df_ativos_funil[df_ativos_funil['Etapa_Ativa_Final'] == "Visita Agendada"])
        t_vrealiz = len(df_ativos_funil[df_ativos_funil['Etapa_Ativa_Final'] == "Visita Realizada"])
        t_resgatados = len(df_ativos_funil[df_ativos_funil['Etapa_Ativa_Final'] == "🎯 Resgatado em Contato"])
        t_investidores = len(df[df['Perfil_Investidor']])
        t_total_ativo = len(df_ativos_funil)
        t_perdidos = len(df_perdidos_total)

        c_top1, c_top2, c_top3, c_top4, c_top5, c_top6 = st.columns(6)
        c_top1.metric("1. Em Tentativa", t_tent)
        c_top2.metric("2. Em Atendimento", t_atend)
        c_top3.metric("3. Visitas (Agend + Realiz)", t_vagend + t_vrealiz)
        c_top4.metric("💎 Investidores", t_investidores, help="Leads com perfil de investimento identificado")
        c_top5.metric("Total Carteira Ativa", t_total_ativo)
        c_top6.metric(
            "❌ Leads Perdidos", 
            t_perdidos, 
            delta=f"{(t_perdidos / total_geral_base * 100):.1f}% da base" if total_geral_base > 0 else "0%",
            delta_color="inverse"
        )

        st.markdown("---")
        st.markdown("### 📋 1. Totais por Corretor (Carteira Ativa vs. Perdidos)")
        st.caption("Acompanhe o volume sob responsabilidade de cada corretor, incluindo leads perdidos e investidores:")

        todos_corretores_base = sorted(list(set(df_ativos_funil['Corretor_Ativo'].dropna().unique().tolist() + df_perdidos_total['Corretor_Ativo'].dropna().unique().tolist())))

        tabela_macro_dados = []
        for corr in todos_corretores_base:
            df_c_ativo = df_ativos_funil[df_ativos_funil['Corretor_Ativo'] == corr]
            df_c_perdido = df_perdidos_total[df_perdidos_total['Corretor_Ativo'] == corr]
            df_c_total = df[df['Corretor_Ativo'] == corr]

            qtd_tent = len(df_c_ativo[df_c_ativo['Etapa_Ativa_Final'] == "Em Tentativa"])
            qtd_atend = len(df_c_ativo[df_c_ativo['Etapa_Ativa_Final'] == "Em Atendimento"])
            qtd_vagend = len(df_c_ativo[df_c_ativo['Etapa_Ativa_Final'] == "Visita Agendada"])
            qtd_vrealiz = len(df_c_ativo[df_c_ativo['Etapa_Ativa_Final'] == "Visita Realizada"])
            qtd_resg = len(df_c_ativo[df_c_ativo['Etapa_Ativa_Final'] == "🎯 Resgatado em Contato"])
            qtd_inv = len(df_c_total[df_c_total['Perfil_Investidor']])
            qtd_ativos_total = len(df_c_ativo)
            qtd_perd = len(df_c_perdido)
            qtd_total_geral = qtd_ativos_total + qtd_perd

            tabela_macro_dados.append({
                'Corretor': corr,
                'Em Tentativa': qtd_tent,
                'Em Atendimento': qtd_atend,
                'Visitas Agendadas': qtd_vagend,
                'Visitas Realizadas': qtd_vrealiz,
                '🎯 Resgatados': qtd_resg,
                '💎 Investidores': qtd_inv,
                'Total Carteira Ativa': qtd_ativos_total,
                '❌ Leads Perdidos': qtd_perd,
                'Total Geral Recebido': qtd_total_geral
            })

        df_macro_tabela = pd.DataFrame(tabela_macro_dados).sort_values(by='Total Carteira Ativa', ascending=False)
        st.dataframe(df_macro_tabela, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("### 🔍 2. Detalhamento de Etapa & Tempo Sem Contato")
        st.caption("Escolha a etapa para abrir a quebra por dias sem interação (0 a 3 dias, 4 a 10 dias e mais de 10 dias).")

        etapa_escolhida_detalhe = st.radio(
            "Selecione a etapa para ver a quebra de atraso:",
            ["Em Tentativa", "Em Atendimento", "🎯 Resgatados em Contato", "Visitas (Agendadas + Realizadas)", "❌ Leads Perdidos"],
            horizontal=True
        )

        if etapa_escolhida_detalhe == "Visitas (Agendadas + Realizadas)":
            df_etapa_sub = df_ativos_funil[df_ativos_funil['Etapa_Ativa_Final'].isin(["Visita Agendada", "Visita Realizada"])].copy()
        elif etapa_escolhida_detalhe == "❌ Leads Perdidos":
            df_etapa_sub = df_perdidos_total.copy()
        else:
            df_etapa_sub = df_ativos_funil[df_ativos_funil['Etapa_Ativa_Final'] == etapa_escolhida_detalhe].copy()

        n_0_3 = len(df_etapa_sub[df_etapa_sub['Faixa_Atraso'] == "0 a 3 dias"])
        n_4_10 = len(df_etapa_sub[df_etapa_sub['Faixa_Atraso'] == "4 a 10 dias"])
        n_mais_10 = len(df_etapa_sub[df_etapa_sub['Faixa_Atraso'] == "Mais de 10 dias"])

        col_t1, col_t2, col_t3 = st.columns(3)
        rotulo_bloco = etapa_escolhida_detalhe.replace("❌ ", "").replace("🎯 ", "")
        col_t1.metric(f"{rotulo_bloco}: 0 a 3 dias", n_0_3)
        col_t2.metric(f"{rotulo_bloco}: 4 a 10 dias", n_4_10)
        col_t3.metric(f"{rotulo_bloco}: Mais de 10 dias", n_mais_10, delta=f"-{n_mais_10}" if n_mais_10 > 0 else "0", delta_color="inverse")

        tabela_tempo_corretores = []
        for corr in sorted(df_etapa_sub['Corretor_Ativo'].dropna().unique()):
            df_c_etapa = df_etapa_sub[df_etapa_sub['Corretor_Ativo'] == corr]
            tabela_tempo_corretores.append({
                'Corretor': corr,
                '0 a 3 dias': len(df_c_etapa[df_c_etapa['Faixa_Atraso'] == "0 a 3 dias"]),
                '4 a 10 dias': len(df_c_etapa[df_c_etapa['Faixa_Atraso'] == "4 a 10 dias"]),
                'Mais de 10 dias': len(df_c_etapa[df_c_etapa['Faixa_Atraso'] == "Mais de 10 dias"]),
                'Total na Etapa': len(df_c_etapa)
            })

        df_tempo_view = pd.DataFrame(tabela_tempo_corretores).sort_values(by='Total na Etapa', ascending=False)
        st.dataframe(df_tempo_view, use_container_width=True, hide_index=True)

        st.markdown(f"#### 👤 Ver Leads Individuais de **{etapa_escolhida_detalhe}**")
        col_f_c1, col_f_c2 = st.columns(2)
        with col_f_c1:
            filtro_corr_drill = st.selectbox("Escolha o Corretor:", ["Todos os Corretores"] + sorted(df_etapa_sub['Corretor_Ativo'].dropna().unique().tolist()), key="sel_corr_drill_list")
        with col_f_c2:
            filtro_faixa_drill = st.selectbox("Escolha a Faixa de Atraso:", ["Todas as Faixas", "Mais de 10 dias (Apenas Críticos)", "4 a 10 dias", "0 a 3 dias"], key="sel_faixa_drill_list")

        df_drill_final = df_etapa_sub.copy()
        if filtro_corr_drill != "Todos os Corretores":
            df_drill_final = df_drill_final[df_drill_final['Corretor_Ativo'] == filtro_corr_drill]

        if filtro_faixa_drill == "Mais de 10 dias (Apenas Críticos)":
            df_drill_final = df_drill_final[df_drill_final['Faixa_Atraso'] == "Mais de 10 dias"]
        elif filtro_faixa_drill != "Todas as Faixas":
            df_drill_final = df_drill_final[df_drill_final['Faixa_Atraso'] == filtro_faixa_drill]

        st.caption(f"Mostrando {len(df_drill_final)} leads:")
        cols_show_det = ['Nome Cliente', 'Celular_Limpo', 'Corretor_Ativo', 'Etapa do Funil', 'Motivo Perda', 'Dias_Sem_Interacao', 'Faixa_Atraso', 'Último Contato em', 'Descrição Último Contato']
        st.dataframe(df_drill_final[cols_show_det].rename(columns={
            'Nome Cliente': 'Cliente',
            'Celular_Limpo': 'Celular',
            'Corretor_Ativo': 'Corretor Responsável',
            'Dias_Sem_Interacao': 'Dias Sem Contato',
            'Descrição Último Contato': 'Última Anotação no CRM'
        }), use_container_width=True, hide_index=True)

    # --- MÓDULO NOVO: RADAR DE INVESTIDORES ---
    elif modulo_ativo == "💎 Radar de Investidores":
        st.subheader("💎 Radar de Investidores da Base")
        st.caption("Clientes identificados com perfil de investimento (por notas de histórico do CRM ou marcados manualmente na nuvem).")

        df_investidores = df[df['Perfil_Investidor']].copy()

        # Métricas do Módulo
        tot_inv = len(df_investidores)
        inv_atend = len(df_investidores[df_investidores['Etapa_Macro'] == "Em Atendimento"])
        inv_visitas = len(df_investidores[df_investidores['Etapa_Macro'].isin(["Visita Agendada", "Visita Realizada"])])
        inv_perdidos = len(df_investidores[df_investidores['Etapa_Macro'] == "Perdido"])

        mi1, mi2, mi3, mi4 = st.columns(4)
        mi1.metric("Total de Investidores Identificados", tot_inv)
        mi2.metric("Em Atendimento Ativo", inv_atend)
        mi3.metric("Visitas Agendadas/Feitas", inv_visitas)
        mi4.metric("Arquivados / Perdidos", inv_perdidos, help="Investidores arquivados que podem ser resgatados com nova oferta!")

        st.markdown("---")

        col_inv_esq, col_inv_dir = st.columns([1, 1])

        with col_inv_esq:
            st.markdown("#### ➕ Marcar Novo Lead como Investidor (Salva na Nuvem)")
            busca_inv = st.text_input("Buscar cliente por Nome ou Telefone para marcar como Investidor:", key="busca_inv_input")
            leads_inv_encontrados = pd.DataFrame()
            if busca_inv.strip():
                leads_inv_encontrados = df[
                    df['Nome Cliente'].astype(str).str.contains(busca_inv, case=False, na=False) |
                    df['Celular_Limpo'].astype(str).str.contains(busca_inv, case=False, na=False)
                ].head(10)

            cel_inv_alvo = ""
            nome_inv_alvo = ""
            corr_inv_alvo = ""

            if not leads_inv_encontrados.empty:
                op_inv = st.selectbox(
                    "Selecione o lead encontrado:",
                    options=leads_inv_encontrados['lead_key'].tolist(),
                    format_func=lambda x: f"{leads_inv_encontrados.loc[leads_inv_encontrados['lead_key']==x, 'Nome Cliente'].values[0]} ({leads_inv_encontrados.loc[leads_inv_encontrados['lead_key']==x, 'Celular_Limpo'].values[0]}) - {leads_inv_encontrados.loc[leads_inv_encontrados['lead_key']==x, 'Corretor'].values[0]}",
                    key="sel_lead_inv_match"
                )
                l_escolhido = leads_inv_encontrados[leads_inv_encontrados['lead_key'] == op_inv].iloc[0]
                cel_inv_alvo = l_escolhido['Celular_Limpo']
                nome_inv_alvo = l_escolhido['Nome Cliente']
                corr_inv_alvo = l_escolhido['Corretor']
            else:
                cel_inv_alvo = st.text_input("Ou digite o Celular:", value="", key="cel_inv_manual")
                nome_inv_alvo = st.text_input("Nome do Cliente:", value="", key="nome_inv_manual")
                corr_inv_alvo = st.selectbox("Corretor Responsável:", corretores_disponiveis, key="corr_inv_manual")

            obs_inv = st.text_input("Observação / Perfil (ex: Quer comprar 2 lotes, busca rentabilidade, etc.):", value="Perfil Investidor Confirmado", key="obs_inv_txt")

            if st.button("💎 Confirmar e Salvar como Investidor no Google Sheets", key="btn_salvar_inv"):
                cel_l = limpar_celular(cel_inv_alvo)
                if len(cel_l) < 8:
                    st.error("Informe um celular válido.")
                else:
                    with st.spinner("Salvando investidor..."):
                        registrar_investidor_db(cel_l, nome_inv_alvo or "Cliente", corr_inv_alvo, obs_inv)
                    st.success(f"Lead {nome_inv_alvo} ({cel_l}) adicionado ao Radar de Investidores!")
                    st.rerun()

        with col_inv_dir:
            st.markdown("#### 👥 Investidores por Corretor")
            if not df_investidores.empty:
                dist_inv_corr = df_investidores.groupby('Corretor_Ativo').agg(
                    Total_Investidores=('Nome Cliente', 'count'),
                    Em_Atendimento=('Etapa_Macro', lambda s: (s == "Em Atendimento").sum()),
                    Visitas=('Etapa_Macro', lambda s: s.isin(["Visita Agendada", "Visita Realizada"]).sum()),
                    Perdidos=('Etapa_Macro', lambda s: (s == "Perdido").sum())
                ).reset_index().rename(columns={'Corretor_Ativo': 'Corretor'})
                st.dataframe(dist_inv_corr, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhum investidor identificado ainda.")

        st.markdown("---")

        # TABELA COMPLETA DE INVESTIDORES COM DISPARO WHATSAPP E DOWNLOAD EXCEL
        st.markdown("### 📋 Carteira Completa de Investidores")
        
        col_fi1, col_fi2 = st.columns(2)
        with col_fi1:
            filtro_corr_inv = st.selectbox("Filtrar por Corretor:", ["Todos os Corretores"] + sorted(df_investidores['Corretor_Ativo'].dropna().unique().tolist()), key="f_corr_inv_tab")
        with col_fi2:
            filtro_etapa_inv = st.selectbox("Filtrar por Etapa:", ["Todas as Etapas", "Apenas Ativos (Atendimento/Visita)", "Apenas Perdidos (Para Resgate)"], key="f_etapa_inv_tab")

        df_inv_view = df_investidores.copy()
        if filtro_corr_inv != "Todos os Corretores":
            df_inv_view = df_inv_view[df_inv_view['Corretor_Ativo'] == filtro_corr_inv]

        if filtro_etapa_inv == "Apenas Ativos (Atendimento/Visita)":
            df_inv_view = df_inv_view[df_inv_view['Etapa_Macro'].isin(["Em Atendimento", "Visita Agendada", "Visita Realizada", "Em Tentativa"])]
        elif filtro_etapa_inv == "Apenas Perdidos (Para Resgate)":
            df_inv_view = df_inv_view[df_inv_view['Etapa_Macro'] == "Perdido"]

        if df_inv_view.empty:
            st.info("Nenhum investidor encontrado com os filtros selecionados.")
        else:
            # Mensagem WhatsApp com lista de investidores
            msg_inv_whats = f"*LISTA EXCLUSIVA - CLIENTES INVESTIDORES*\n*Data:* {datetime.datetime.now().strftime('%d/%m/%Y')}\n"
            if filtro_corr_inv != "Todos os Corretores":
                msg_inv_whats += f"*Consultor Responsável:* {filtro_corr_inv}\n"
            msg_inv_whats += f"━━━━━━━━━━━━━━━━━━━━━━\n"
            for _, r_inv in df_inv_view.head(20).iterrows():
                msg_inv_whats += f"• *{r_inv['Nome Cliente']}* - {r_inv['Celular_Limpo']} ({r_inv['Etapa do Funil']})\n"
            msg_inv_whats += f"\n💡 *Oportunidade:* Apresentar lotes com condições especiais e retorno de valorização!"

            with st.expander("👁️ Ver Lista Formatada para Disparo no WhatsApp:", expanded=False):
                render_botao_copiar(msg_inv_whats, "📋 Copiar Lista de Investidores para WhatsApp")
                st.code(msg_inv_whats, language="text")

            cols_inv_tabela = [
                'Nome Cliente', 'Celular_Limpo', 'Corretor_Ativo', 'Etapa do Funil',
                'Dias_Sem_Interacao', 'Faixa_Atraso', 'Último Contato em', 'Descrição Último Contato'
            ]
            st.dataframe(df_inv_view[cols_inv_tabela].rename(columns={
                'Nome Cliente': 'Cliente',
                'Celular_Limpo': 'Celular',
                'Corretor_Ativo': 'Corretor',
                'Dias_Sem_Interacao': 'Dias Parado',
                'Descrição Último Contato': 'Última Anotação'
            }), use_container_width=True, hide_index=True)

            # Download da lista de investidores
            buffer_inv_excel = io.BytesIO()
            with pd.ExcelWriter(buffer_inv_excel, engine='openpyxl') as writer:
                df_inv_view[cols_inv_tabela].to_excel(writer, index=False, sheet_name="Investidores")
            st.download_button(
                label="📥 Baixar Lista de Investidores (.xlsx)",
                data=buffer_inv_excel.getvalue>,
                file_name=f"radar_investidores_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    # --- MÓDULO: CENTRAL DE RELATÓRIOS ---
    elif modulo_ativo == "📑 Central de Relatórios (Corretores & Loteadora)":
        st.subheader("Central de Relatórios Executivos & Disparos Individuais")
        st.caption("Gere o relatório individual de evolução para cada corretor e o dossiê estratégico para a loteadora.")

        sub_aba_corr, sub_aba_loteadora = st.tabs(["👤 Relatório Individual do Corretor (com Evolução)", "🏢 Dossiê da Loteadora"])

        with sub_aba_corr:
            st.markdown("### 📤 Gerador de Relatório Individual para o Corretor")
            st.caption("Gera um relatório pronto para WhatsApp com a evolução e a lista dos leads para cobrar prioridade.")

            corr_alvo_rel = st.selectbox("Selecione o Corretor:", corretores_disponiveis, key="sel_rep_indiv_corr")
            df_c_base = df[df['Corretor_Ativo'] == corr_alvo_rel].copy()
            df_c_ativos = df_c_base[df_c_base['Etapa_Ativa_Final'].notna() & (~df_c_base['Lead_Bloqueado']) & (df_c_base['Etapa_Ativa_Final'] != "Perdido")].copy()
            df_c_perdidos = df_c_base[df_c_base['Etapa_Ativa_Final'] == "Perdido"].copy()

            tot_corr_ativos = len(df_c_ativos)
            c_tent = len(df_c_ativos[df_c_ativos['Etapa_Ativa_Final'] == 'Em Tentativa'])
            c_atend = len(df_c_ativos[df_c_ativos['Etapa_Ativa_Final'] == 'Em Atendimento'])
            c_vis_ag = len(df_c_ativos[df_c_ativos['Etapa_Ativa_Final'] == 'Visita Agendada'])
            c_vis_re = len(df_c_ativos[df_c_ativos['Etapa_Ativa_Final'] == 'Visita Realizada'])
            c_resgatados_corr = len(df_c_ativos[df_c_ativos['Etapa_Ativa_Final'] == '🎯 Resgatado em Contato'])
            c_inv_corr = len(df_c_base[df_c_base['Perfil_Investidor']])
            c_perdidos_total = len(df_c_perdidos)

            c_0_3 = len(df_c_ativos[df_c_ativos['Faixa_Atraso'] == '0 a 3 dias'])
            c_4_10 = len(df_c_ativos[df_c_ativos['Faixa_Atraso'] == '4 a 10 dias'])
            c_mais_10 = len(df_c_ativos[df_c_ativos['Faixa_Atraso'] == 'Mais de 10 dias'])

            r_c1, r_c2, r_c3, r_c4, r_c5 = st.columns(5)
            r_c1.metric("Total Carteira Ativa", tot_corr_ativos)
            r_c2.metric("💎 Investidores", c_inv_corr)
            r_c3.metric("🟢 Em dia (0 a 3 dias)", c_0_3)
            r_c4.metric("🔴 Crítico (+10 dias)", c_mais_10, delta=f"-{c_mais_10}" if c_mais_10 > 0 else "0", delta_color="inverse")
            r_c5.metric("❌ Leads Perdidos", c_perdidos_total)

            evolucao_texto_whats = ""
            if df_ant is not None:
                df_ant_c = df_ant[df_ant['Corretor'] == corr_alvo_rel]
                ant_map = df_ant_c.set_index('lead_key')['Etapa do Funil'].to_dict()
                
                avancos = 0
                for _, r_now in df_c_base.iterrows():
                    k = r_now['lead_key']
                    if k in ant_map:
                        etapa_antiga = str(ant_map[k]).strip()
                        etapa_nova = str(r_now['Etapa do Funil']).strip()
                        if etapa_antiga != etapa_nova and etapa_nova not in ['Em Tentativa', 'Perdido']:
                            avancos += 1

                evolucao_texto_whats = f"\n📈 *EVOLUÇÃO RECENTE (VS. RELATÓRIO ANTERIOR):*\n• Leads que avançaram de etapa: *{avancos}*\n"

            hoje_formatada = datetime.datetime.now().strftime("%d/%m/%Y")
            msg_whatsapp_corretor = f"📊 *RAIO-X DE CARTEIRA & EVOLUÇÃO COMERCIAL*\n"
            msg_whatsapp_corretor += f"👤 *Consultor:* {corr_alvo_rel}\n"
            msg_whatsapp_corretor += f"📅 *Posição em:* {hoje_formatada}\n"
            msg_whatsapp_corretor += f"━━━━━━━━━━━━━━━━━━━━━━\n"
            msg_whatsapp_corretor += f"🎯 *SUA CARTEIRA ATIVA ({tot_corr_ativos} leads):*\n"
            msg_whatsapp_corretor += f"• Em Tentativa (1º Contato): {c_tent}\n"
            msg_whatsapp_corretor += f"• Em Atendimento Ativo: {c_atend}\n"
            msg_whatsapp_corretor += f"• Visitas Agendadas: {c_vis_ag}\n"
            msg_whatsapp_corretor += f"• Visitas Realizadas: {c_vis_re}\n"
            if c_resgatados_corr > 0:
                msg_whatsapp_corretor += f"• 🎯 *Clientes Resgatados com Sucesso: {c_resgatados_corr}*\n"
            if c_inv_corr > 0:
                msg_whatsapp_corretor += f"• 💎 *Clientes Perfil Investidor: {c_inv_corr}*\n"
            msg_whatsapp_corretor += f"• ❌ Total Histórico de Perdidos: {c_perdidos_total}\n"
            msg_whatsapp_corretor += f"{evolucao_texto_whats}"
            msg_whatsapp_corretor += f"\n⏱️ *TEMPERATURA DOS SEUS CONTATOS ATIVOS:*\n"
            msg_whatsapp_corretor += f"🟢 *0 a 3 dias (Em dia):* {c_0_3} clientes\n"
            msg_whatsapp_corretor += f"🟡 *4 a 10 dias (Atenção):* {c_4_10} clientes\n"
            msg_whatsapp_corretor += f"🔴 *+10 dias (Crítico / Sem contato):* {c_mais_10} clientes\n"

            df_criticos_corr = df_c_ativos[df_c_ativos['Faixa_Atraso'] == 'Mais de 10 dias'].sort_values(by='Dias_Sem_Interacao', ascending=False)
            if not df_criticos_corr.empty:
                msg_whatsapp_corretor += f"\n🚨 *PRIORIDADE DE HOJE (+10 DIAS PARADOS):*\n"
                for _, r_crit in df_criticos_corr.head(10).iterrows():
                    msg_whatsapp_corretor += f"• *{r_crit['Nome Cliente']}* - {r_crit['Celular_Limpo']} ({r_crit['Etapa do Funil']}) | Parado há {r_crit['Dias_Sem_Interacao']} dias\n"
                if len(df_criticos_corr) > 10:
                    msg_whatsapp_corretor += f"... e mais {len(df_criticos_corr) - 10} leads críticos.\n"
            
            msg_whatsapp_corretor += f"━━━━━━━━━━━━━━━━━━━━━━\n"
            msg_whatsapp_corretor += f"💡 *Foco:* Fazer contato com os clientes em atenção/críticos e atualizar as anotações no CRM hoje!"

            st.markdown("---")
            st.markdown("#### 📱 Mensagem Pronta para o WhatsApp do Corretor:")
            render_botao_copiar(msg_whatsapp_corretor, f"📋 Copiar Relatório Completo de {corr_alvo_rel}")
            st.code(msg_whatsapp_corretor, language="text")

            st.markdown("---")
            st.markdown(f"#### 📥 Baixar Relatório em Planilha Excel ({corr_alvo_rel})")
            
            buffer_corr_excel = io.BytesIO()
            with pd.ExcelWriter(buffer_corr_excel, engine='openpyxl') as writer:
                df_resumo_exp = pd.DataFrame([{
                    'Consultor': corr_alvo_rel,
                    'Total Carteira Ativa': tot_corr_ativos,
                    'Em Tentativa': c_tent,
                    'Em Atendimento': c_atend,
                    'Visitas Agendadas': c_vis_ag,
                    'Visitas Realizadas': c_vis_re,
                    'Resgatados': c_resgatados_corr,
                    'Investidores': c_inv_corr,
                    'Leads Perdidos': c_perdidos_total,
                    '0 a 3 dias (Em dia)': c_0_3,
                    '4 a 10 dias (Atenção)': c_4_10,
                    'Mais de 10 dias (Crítico)': c_mais_10
                }])
                df_resumo_exp.to_excel(writer, index=False, sheet_name="Resumo_Carteira")
                
                cols_exp = ['Nome Cliente', 'Celular_Limpo', 'Etapa do Funil', 'Dias_Sem_Interacao', 'Faixa_Atraso', 'Último Contato em', 'Descrição Último Contato']
                
                if not df_criticos_corr.empty:
                    df_criticos_corr[cols_exp].to_excel(writer, index=False, sheet_name="Criticos_Mais_10_Dias")
                
                df_atend_corr = df_c_ativos[df_c_ativos['Etapa_Ativa_Final'] == 'Em Atendimento']
                if not df_atend_corr.empty:
                    df_atend_corr[cols_exp].to_excel(writer, index=False, sheet_name="Em_Atendimento")
                
                df_tent_corr = df_c_ativos[df_c_ativos['Etapa_Ativa_Final'] == 'Em Tentativa']
                if not df_tent_corr.empty:
                    df_tent_corr[cols_exp].to_excel(writer, index=False, sheet_name="Em_Tentativa")

                df_resg_corr = df_c_ativos[df_c_ativos['Etapa_Ativa_Final'] == '🎯 Resgatado em Contato']
                if not df_resg_corr.empty:
                    df_resg_corr[cols_exp].to_excel(writer, index=False, sheet_name="Resgatados_Contato")

            st.download_button(
                label=f"📥 Baixar Dossiê Excel de {corr_alvo_rel} (.xlsx)",
                data=buffer_corr_excel.getvalue(),
                file_name=f"relatorio_evolucao_{corr_alvo_rel.replace(' ', '_')}_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx",
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
            perf_loteadora = df.groupby('Corretor_Ativo').agg(
                Total_Recebido=('Nome Cliente', 'count'),
                Em_Atendimento=('Etapa_Ativa_Final', lambda s: (s == "Em Atendimento").sum()),
                Visitas=('Etapa_Ativa_Final', lambda s: s.isin(['Visita Agendada', 'Visita Realizada']).sum()),
                Resgatados=('Etapa_Ativa_Final', lambda s: (s == '🎯 Resgatado em Contato').sum()),
                Investidores=('Perfil_Investidor', 'sum'),
                Vendas=('Etapa do Funil', lambda s: (s == 'Negócio Fechado.').sum()),
                Perdidos=('Etapa do Funil', lambda s: s.str.contains('Perdido').sum())
            ).reset_index().rename(columns={'Corretor_Ativo': 'Corretor'})
            perf_loteadora['% Aproveitamento'] = ((perf_loteadora['Visitas'] + perf_loteadora['Vendas'] + perf_loteadora['Resgatados']) / perf_loteadora['Total_Recebido'] * 100).map("{:.1f}%".format)
            st.dataframe(perf_loteadora.sort_values(by='Visitas', ascending=False), use_container_width=True, hide_index=True)

            buffer_lot = io.BytesIO()
            with pd.ExcelWriter(buffer_lot, engine='openpyxl') as writer:
                perf_lote
