# Task 9: Set Firewall Rules
$VpnPort = $State.Settings.Firewall.VpnListenPort
$VpnProto = $State.Settings.Firewall.VpnProto.ToUpper() -replace '4|6','' # udp4 -> UDP

# --- Rule 1: WAN Allow UDP Port ---
$Desc1 = "WAN allow $VpnProto $VpnPort to this firewall (auto-vpn)"
Write-Host ("  Ensuring firewall rule '{0}' exists..." -f $Desc1)

try {
    $search = Call-Api-Firewall -Path "/api/firewall/filter/search_rule" -Method POST -Body @{ searchPhrase = $Desc1 }
    $existing = $search.rows | Where-Object { $_.description -eq $Desc1 }
    if ($existing) {
        Write-Host "  WAN rule already exists (UUID: $($existing[0].uuid))."
    } else {
        $payload = @{
            rule = @{
                enabled          = "1"; action = "pass"; interface = "wan"
                ipprotocol       = "inet" # IPv4
                protocol         = $VpnProto
                direction        = "in"; source_net = "any"
                destination_net  = "(self)"
                destination_port = $VpnPort
                log              = "1"; quick = "1"
                description      = $Desc1
            }
        }
        $result = Call-Api-Firewall -Path "/api/firewall/filter/add_rule" -Method POST -Body $payload
        Write-Host ("  WAN rule added (UUID: {0})." -f $result.uuid) -ForegroundColor Green
    }
} catch {
    Write-Warning "  Failed to add WAN rule: $($_.Exception.Message)"
}

# --- Rule 2: OpenVPN Group Allow All ---
$Desc2 = "Default allow OpenVPN group to any (auto-vpn)"
Write-Host ("  Ensuring firewall rule '{0}' exists..." -f $Desc2)

try {
    $search2 = Call-Api-Firewall -Path "/api/firewall/filter/search_rule" -Method POST -Body @{ searchPhrase = $Desc2 }
    $existing2 = $search2.rows | Where-Object { $_.description -eq $Desc2 }
    if ($existing2) {
        Write-Host "  OpenVPN rule already exists (UUID: $($existing2[0].uuid))."
    } else {
        $payload = @{
            rule = @{
                enabled          = "1"; action = "pass"; interface = "openvpn"
                ipprotocol       = "inet"
                protocol         = "any"; direction = "in"
                source_net       = "any"; destination_net = "any"
                log              = "1"; quick = "1"
                description      = $Desc2
            }
        }
        $result = Call-Api-Firewall -Path "/api/firewall/filter/add_rule" -Method POST -Body $payload
        Write-Host ("  OpenVPN rule added (UUID: {0})." -f $result.uuid) -ForegroundColor Green
    }
} catch {
    Write-Warning "  Failed to add OpenVPN rule: $($_.Exception.Message)"
}

# --- Apply Firewall Changes ---
Write-Host "  Applying firewall changes..."
$applied = $false
try {
    # [FIXED] ถ้าบรรทัดนี้ไม่ Error (ไม่ Throw) ให้ถือว่าสำเร็จ (HTTP 200 OK)
    $apply = Call-Api-Firewall -Path "/api/firewall/filter/apply" -Method POST -Body @{}
    $applied = $true
    Write-Host "  Apply (filter) status: OK"
} catch {
    Write-Host "  /api/firewall/filter/apply failed ($($_.Exception.Message)), trying fallback..." -ForegroundColor DarkGray
}

if (-not $applied) {
    try {
        # ลอง Endpoint สำรอง (ซึ่งเรารู้ว่า 404 แต่ใส่ไว้เผื่อ OPNsense รุ่นอื่น)
        $apply2 = Call-Api-Firewall -Path "/api/firewall/filter_base/apply" -Method POST -Body @{}
        $applied = $true
        Write-Host "  Apply (filter_base) status: OK"
    } catch {
        Write-Host "  Fallback /api/firewall/filter_base/apply failed ($($_.Exception.Message))." -ForegroundColor DarkGray
    }
}

# [FIXED] ปรับปรุงข้อความสรุป
if ($applied) {
    Write-Host "  Firewall changes applied successfully."
} else {
    Write-Warning "Could not apply firewall changes. Please apply manually via GUI."
}

Write-Host "[Task 9/9] Complete" -ForegroundColor Green