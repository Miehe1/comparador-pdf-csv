# Comparador PDF × CSV

Ferramenta web para comparar relatórios de vendas (PDF do ERP) com transações detalhadas (CSV da adquirente), identificando vendas ausentes e relatório de negadas/canceladas por caixa.

## Usar sem instalar nada

1. Vá até a aba **[Releases](../../releases)** do repositório
2. Baixe o arquivo `ComparadorPDF_CSV.exe`
3. Dê dois cliques — o navegador abre automaticamente em `http://127.0.0.1:5000`
4. Feche a janela preta para encerrar

> Funciona no Windows 10/11 sem instalar Python, Node ou qualquer dependência.

## Funcionalidades

- Upload de PDF (ERP) e CSV (adquirente) — PDF é opcional
- Detecção automática de todos os caixas disponíveis
- Seleção de um ou vários caixas para comparar
- Visualização **Geral** (consolidado) ou **Por Caixa**
- Aba **Faltando no PDF**: transações efetuadas no CSV que não aparecem no PDF
- Aba **Negadas / Canceladas**: pills clicáveis por tipo de rejeição, tabela filtrável
- Filtros por coluna (texto, dropdown, faixa de valor) e ordenação em todas as tabelas
- Exportar resultado em TXT
- Modo somente CSV: relatório de negadas/canceladas sem necessidade de PDF

## Desenvolvimento local

```bash
pip install -r requirements.txt
python app.py
```

Acesse `http://127.0.0.1:5000`.

## Compilar o executável localmente

```bat
build.bat
```

O `.exe` gerado fica em `dist/ComparadorPDF_CSV.exe`.
