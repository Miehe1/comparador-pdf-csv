import os
import sys
import re
import io
import json
import tempfile
import threading
import webbrowser
from collections import Counter
from flask import Flask, render_template, request, jsonify, send_file
import pdfplumber

# ── Caminho base: funciona tanto em modo dev quanto como .exe (PyInstaller) ───
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB

# ── Helpers ────────────────────────────────────────────────────────────────────

def limpar(s):
    return s.strip().strip('"').strip()

def normalizar_valor(valor_str):
    v = limpar(valor_str).replace('.', '').replace(',', '.')
    try:
        return round(float(v), 2)
    except:
        return None

CARD_HEADER  = re.compile(r'^([A-Z][A-Z\s]+?)\.+\s+\d{3,6}\s+\d+-\s*\d')
CONTINUATION = re.compile(r'^\d{3,6}\s+\d+-\s*\d')
VALUE_REGEX  = re.compile(r'\b(\d[\d\.]*,\d{2})\s*\|')
PAGE_HEADER  = re.compile(
    r'^(MERCADO ALICE|Movimento|Lj\.Ven|VENDA|Nome C|Total do cliente|Total do caixa)',
    re.IGNORECASE
)
CAIXA_START  = re.compile(r'Caixa->\s*(\d+)\s*-\s*CAIXA(\d+)', re.IGNORECASE)
CAIXA_TOTAL  = re.compile(r'Total do caixa.*CAIXA(\d+)', re.IGNORECASE)

# ── Parser PDF ─────────────────────────────────────────────────────────────────

def parse_pdf(pdf_bytes):
    """
    Retorna dict: { caixa_num (int) -> [(card_type, valor)] }
    """
    pdf_lines = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pdf_lines.extend(text.splitlines())

    resultado = {}
    current_caixa = None
    current_card = None

    for line in pdf_lines:
        s = line.strip()

        m = CAIXA_START.match(s)
        if m:
            current_caixa = int(m.group(1))
            if current_caixa not in resultado:
                resultado[current_caixa] = []
            current_card = None
            continue

        if current_caixa is None:
            continue

        mt = CAIXA_TOTAL.match(s)
        if mt and int(mt.group(1)) == current_caixa:
            current_caixa = None
            current_card = None
            continue

        if PAGE_HEADER.match(s):
            continue

        mc = CARD_HEADER.match(s)
        if mc:
            current_card = mc.group(1).strip().rstrip('.')
            vm = VALUE_REGEX.search(s)
            if vm:
                v = normalizar_valor(vm.group(1))
                if v is not None:
                    resultado[current_caixa].append((current_card, v))
            continue

        if CONTINUATION.match(s) and current_card:
            vm = VALUE_REGEX.search(s)
            if vm:
                v = normalizar_valor(vm.group(1))
                if v is not None:
                    resultado[current_caixa].append((current_card, v))

    return resultado

# ── Parser CSV ─────────────────────────────────────────────────────────────────

def parse_csv(csv_bytes):
    """
    Retorna dict: { caixa_num (int) -> [row_dict] }
    Apenas transações com estado 'Efetuada PDV'.
    Também retorna todos os estados para exibição.
    """
    try:
        text = csv_bytes.decode('latin-1')
    except:
        text = csv_bytes.decode('utf-8', errors='replace')

    lines = text.splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if 'PDV' in line and 'Valor' in line and 'NSU' in line:
            header_idx = i
            break
    if header_idx is None:
        return {}, {}

    header_parts = [limpar(p) for p in lines[header_idx].split(';')]

    IDX_PDV    = 3
    IDX_NSU    = 4
    IDX_VALOR  = 7
    IDX_PROD   = 15
    IDX_DESC   = 16
    IDX_ESTADO = 18
    IDX_CUPOM  = 19
    IDX_HORA   = next((i for i, c in enumerate(header_parts) if c.lower() == 'hora'), None)
    IDX_DATA   = 0

    resultado_ok  = {}  # caixa -> [rows efetuadas]
    resultado_all = {}  # caixa -> [todas as rows]

    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        parts = line.split(';')
        if len(parts) <= IDX_ESTADO:
            continue

        pdv = limpar(parts[IDX_PDV])
        if not pdv.startswith('LJ'):
            continue

        # Extrair número do caixa do PDV (ex: LJ010008 -> 8)
        try:
            caixa_num = int(pdv[-2:])
        except:
            continue

        estado  = limpar(parts[IDX_ESTADO])
        produto = limpar(parts[IDX_PROD])
        valor   = normalizar_valor(limpar(parts[IDX_VALOR]))
        nsu     = limpar(parts[IDX_NSU])
        cupom   = limpar(parts[IDX_CUPOM])
        hora    = limpar(parts[IDX_HORA]) if IDX_HORA and IDX_HORA < len(parts) else ''
        desc    = limpar(parts[IDX_DESC])
        data    = limpar(parts[IDX_DATA])

        if valor is None:
            continue

        row = {
            'estado': estado, 'produto': produto, 'desc': desc,
            'valor': valor, 'hora': hora, 'cupom': cupom,
            'nsu': nsu, 'data': data, 'pdv': pdv,
        }

        resultado_all.setdefault(caixa_num, []).append(row)
        if 'efetuada' in estado.lower():
            resultado_ok.setdefault(caixa_num, []).append(row)

    return resultado_ok, resultado_all

# ── Comparação ─────────────────────────────────────────────────────────────────

def comparar(pdf_data, csv_ok, csv_all, caixas_selecionadas):
    """
    pdf_data: dict caixa -> [(card, valor)]
    csv_ok:   dict caixa -> [rows efetuadas]
    csv_all:  dict caixa -> [todas as rows]
    caixas_selecionadas: list[int]

    Retorna list de resultados por caixa.
    """
    resultados = []

    for caixa in sorted(caixas_selecionadas):
        pdf_trans  = pdf_data.get(caixa, [])
        csv_trans  = csv_ok.get(caixa, [])
        csv_todos  = csv_all.get(caixa, [])

        pdf_counter = Counter(v for _, v in pdf_trans)
        csv_counter = Counter(r['valor'] for r in csv_trans)

        faltando_counter = csv_counter - pdf_counter
        sobra_counter    = pdf_counter - csv_counter

        # Montar lista detalhada dos faltantes
        usados = Counter()
        faltantes = []
        for r in sorted(csv_trans, key=lambda x: x['hora']):
            val = r['valor']
            if faltando_counter.get(val, 0) > usados.get(val, 0):
                faltantes.append(r)
                usados[val] += 1

        total_faltando = sum(r['valor'] for r in faltantes)

        estados = Counter(r['estado'] for r in csv_todos)

        nao_efetuadas = sorted(
            [r for r in csv_todos if 'efetuada' not in r['estado'].lower()],
            key=lambda x: x['hora']
        )

        resultados.append({
            'caixa': caixa,
            'pdf_total': len(pdf_trans),
            'csv_total': len(csv_todos),
            'csv_efetuadas': len(csv_trans),
            'faltantes': faltantes,
            'total_faltando': total_faltando,
            'nao_efetuadas': nao_efetuadas,
            'sobra_pdf': [
                {'valor': v, 'qtd': q,
                 'tipos': list(set(c for c, vv in pdf_trans if vv == v))}
                for v, q in sorted(sobra_counter.items())
            ],
            'estados': dict(estados.most_common()),
        })

    return resultados

# ── Rotas Flask ────────────────────────────────────────────────────────────────

_session_data = {}  # armazenamento em memória simples

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    pdf_file = request.files.get('pdf')
    csv_file = request.files.get('csv')

    if not csv_file:
        return jsonify({'error': 'Envie ao menos o arquivo CSV.'}), 400

    csv_bytes = csv_file.read()
    has_pdf = pdf_file is not None and pdf_file.filename != ''

    try:
        if has_pdf:
            pdf_bytes = pdf_file.read()
            pdf_data = parse_pdf(pdf_bytes)
        else:
            pdf_bytes = b'placeholder'
            pdf_data = {}
        csv_ok, csv_all = parse_csv(csv_bytes)
    except Exception as e:
        return jsonify({'error': f'Erro ao processar arquivos: {str(e)}'}), 500

    # Descobrir caixas disponíveis
    caixas_pdf = set(pdf_data.keys())
    caixas_csv = set(csv_ok.keys()) | set(csv_all.keys())
    caixas_comuns = sorted(caixas_pdf & caixas_csv) if has_pdf else sorted(caixas_csv)
    caixas_so_pdf = sorted(caixas_pdf - caixas_csv)
    caixas_so_csv = sorted(caixas_csv - caixas_pdf) if has_pdf else []

    session_id = id(csv_bytes)
    _session_data[session_id] = {
        'pdf_data': pdf_data,
        'csv_ok': csv_ok,
        'csv_all': csv_all,
        'has_pdf': has_pdf,
    }

    return jsonify({
        'session_id': session_id,
        'has_pdf': has_pdf,
        'caixas_comuns': caixas_comuns,
        'caixas_so_pdf': caixas_so_pdf,
        'caixas_so_csv': caixas_so_csv,
        'resumo_pdf': {k: len(v) for k, v in pdf_data.items()},
        'resumo_csv': {k: len(v) for k, v in csv_ok.items()},
    })

@app.route('/compare', methods=['POST'])
def compare():
    body = request.get_json()
    session_id = body.get('session_id')
    caixas = body.get('caixas', [])

    dados = _session_data.get(session_id)
    if not dados:
        return jsonify({'error': 'Sessão expirada. Faça upload novamente.'}), 400

    try:
        resultados = comparar(
            dados['pdf_data'],
            dados['csv_ok'],
            dados['csv_all'],
            [int(c) for c in caixas],
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'resultados': resultados, 'has_pdf': dados.get('has_pdf', True)})

@app.route('/exportar', methods=['POST'])
def exportar():
    body = request.get_json()
    resultados = body.get('resultados', [])

    linhas = []
    for r in resultados:
        linhas.append('=' * 90)
        linhas.append(f"CAIXA {r['caixa']:02d}")
        linhas.append('=' * 90)
        linhas.append(f"PDF: {r['pdf_total']} transacoes encontradas")
        linhas.append(f"CSV: {r['csv_total']} transacoes no total | {r['csv_efetuadas']} efetuadas")
        linhas.append(f"Faltando no PDF: {len(r['faltantes'])} transacoes")
        linhas.append(f"Total valor faltando: R$ {r['total_faltando']:,.2f}".replace(',','X').replace('.',',').replace('X','.'))
        linhas.append('')

        if r['faltantes']:
            linhas.append(f"{'#':<4} {'Hora':<10} {'Produto':<22} {'Tipo':<20} {'Valor':>10}  {'NSU':<10} Cupom Fiscal")
            linhas.append('-' * 85)
            for i, f in enumerate(r['faltantes'], 1):
                linhas.append(
                    f"{i:<4} {f['hora']:<10} {f['produto']:<22} {f['desc']:<20} "
                    f"{f['valor']:>10.2f}  {f['nsu']:<10} {f['cupom']}"
                )
        else:
            linhas.append('Nenhuma transacao faltando - PDF e CSV alinhados.')

        nao_ef = r.get('nao_efetuadas', [])
        if nao_ef:
            linhas.append('')
            linhas.append(f'NEGADAS / CANCELADAS: {len(nao_ef)} transacoes')
            linhas.append('')
            linhas.append(f"{'#':<4} {'Hora':<10} {'Produto':<22} {'Tipo':<20} {'Valor':>10}  {'NSU':<10} {'Cupom':<15} Estado")
            linhas.append('-' * 100)
            for i, n in enumerate(nao_ef, 1):
                linhas.append(
                    f"{i:<4} {n['hora']:<10} {n['produto']:<22} {n['desc']:<20} "
                    f"{n['valor']:>10.2f}  {n['nsu']:<10} {n['cupom']:<15} {n['estado']}"
                )

        if r['sobra_pdf']:
            linhas.append('')
            linhas.append('Valores no PDF sem correspondencia no CSV:')
            for s in r['sobra_pdf']:
                linhas.append(f"  R$ {s['valor']:.2f} ({s['qtd']}x) - {', '.join(s['tipos'])}")

        linhas.append('')
        linhas.append('Estados no CSV:')
        for est, qtd in r['estados'].items():
            linhas.append(f"  {est}: {qtd}")
        linhas.append('')

    output = '\n'.join(linhas)
    buf = io.BytesIO(output.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype='text/plain',
                     as_attachment=True, download_name='comparacao_caixas.txt')

if __name__ == '__main__':
    port = 5000
    is_exe = getattr(sys, 'frozen', False)

    if is_exe:
        # Abre o navegador automaticamente após 1.5s
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
        print(f"\n  Comparador PDF x CSV iniciado!")
        print(f"  Acesse: http://127.0.0.1:{port}")
        print(f"  Feche esta janela para encerrar.\n")
        app.run(debug=False, port=port)
    else:
        app.run(debug=True, port=port)
