# Script para configurar el Firewall de Windows para Ron Backend
# EJECUTAR COMO ADMINISTRADOR

Write-Host "Configurando Firewall de Windows para Ron Backend..." -ForegroundColor Cyan

# Agregar regla de firewall para el puerto 8000
try {
    netsh advfirewall firewall add rule name="Ron Backend Port 8000" dir=in action=allow protocol=TCP localport=8000
    Write-Host "✓ Regla de firewall agregada exitosamente" -ForegroundColor Green
} catch {
    Write-Host "✗ Error al agregar regla de firewall: $_" -ForegroundColor Red
    exit 1
}

# Verificar que la regla se haya creado
Write-Host "`nVerificando regla de firewall..." -ForegroundColor Cyan
netsh advfirewall firewall show rule name="Ron Backend Port 8000"

Write-Host "`n✓ Configuración completada!" -ForegroundColor Green
Write-Host "Ahora puedes probar la conexión desde tu teléfono:" -ForegroundColor Yellow
Write-Host "  http://192.168.0.110:8000/health" -ForegroundColor White

pause
