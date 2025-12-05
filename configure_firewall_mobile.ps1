# Configure Windows Firewall for Ron Mobile App
# Run this script as Administrator

Write-Host "Configuring Windows Firewall for Ron Mobile App..." -ForegroundColor Cyan

# Remove existing rule if it exists
try {
    Remove-NetFirewallRule -DisplayName "Ron API Server" -ErrorAction SilentlyContinue
    Write-Host "Removed existing firewall rule" -ForegroundColor Yellow
}
catch {
    # Rule doesn't exist, continue
}

# Add new firewall rule for port 8000
try {
    New-NetFirewallRule -DisplayName "Ron API Server" `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 8000 `
        -Action Allow `
        -Profile Any `
        -Description "Allow incoming connections to Ron API Server on port 8000 for mobile app"
    
    Write-Host "✓ Firewall rule created successfully!" -ForegroundColor Green
    Write-Host "  - Port 8000 is now accessible from your mobile device" -ForegroundColor Green
}
catch {
    Write-Host "✗ Failed to create firewall rule: $_" -ForegroundColor Red
    exit 1
}

# Verify the rule was created
$rule = Get-NetFirewallRule -DisplayName "Ron API Server" -ErrorAction SilentlyContinue
if ($rule) {
    Write-Host "`nFirewall rule details:" -ForegroundColor Cyan
    Write-Host "  Name: $($rule.DisplayName)" -ForegroundColor White
    Write-Host "  Direction: $($rule.Direction)" -ForegroundColor White
    Write-Host "  Action: $($rule.Action)" -ForegroundColor White
    Write-Host "  Enabled: $($rule.Enabled)" -ForegroundColor White
}
else {
    Write-Host "`n✗ Warning: Could not verify firewall rule" -ForegroundColor Yellow
}

Write-Host "`nDone! You can now connect to the Ron API from your mobile device." -ForegroundColor Green
Write-Host "Make sure the Ron API server is running on port 8000." -ForegroundColor Yellow
