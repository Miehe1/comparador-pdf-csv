@echo off
echo Instalando dependencias...
pip install flask pdfplumber pyinstaller

echo.
echo Compilando executavel...
pyinstaller ^
  --onefile ^
  --name "ComparadorPDF_CSV" ^
  --add-data "templates;templates" ^
  --hidden-import pdfminer ^
  --hidden-import pdfminer.high_level ^
  --hidden-import pdfminer.layout ^
  --hidden-import pdfminer.pdfpage ^
  --hidden-import pdfminer.converter ^
  --hidden-import charset_normalizer ^
  --collect-all pdfplumber ^
  app.py

echo.
if exist dist\ComparadorPDF_CSV.exe (
  echo Executavel gerado com sucesso!
  echo Caminho: %cd%\dist\ComparadorPDF_CSV.exe
) else (
  echo ERRO: executavel nao foi gerado.
)
pause
