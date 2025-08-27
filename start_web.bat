@echo off
echo Iniciando Sistema de Monitoramento de Placas - Guarita
echo =====================================================
echo.
echo Ativando ambiente virtual...
call env-lt\Scripts\activate.bat

echo.
echo Iniciando servidor Flask...
echo Acesse: http://localhost:5000
echo.
echo Para parar o servidor, pressione Ctrl+C
echo.

python app.py

pause
