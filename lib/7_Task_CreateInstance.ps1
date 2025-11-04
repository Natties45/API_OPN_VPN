# Task 7: Create OpenVPN Instance
$CARef    = $State.CaRefId
$CertRef  = $State.ServerCertRefId
$TLSUUID  = $State.StaticKeyUuid
$LocalCIDR= $State.Settings.VpnLocalNetwork
$TunnelCIDR= $State.Settings.VpnTunnelNetwork
$Settings = $State.Settings.Firewall

$Description = ("{0}_{1:yyyyMMdd-HHmmss}" -f $State.Settings.NamePatterns.InstancePrefix, (Get-Date))

if (-not $CARef) { throw "State.CaRefId is missing." }
if (-not $CertRef) { throw "State.ServerCertRefId is missing." }
if (-not $TLSUUID) { throw "State.StaticKeyUuid is missing." }
if (-not $LocalCIDR) { throw "State.Settings.VpnLocalNetwork is missing." }

Write-Host ("  Creating instance '{0}'..." -f $Description)
Write-Host ("  ... CA: {0}" -f $CARef)
Write-Host ("  ... Cert: {0}" -f $CertRef)
Write-Host ("  ... TLS: {0}" -f $TLSUUID)
Write-Host ("  ... LAN: {0}" -f $LocalCIDR)
Write-Host ("  ... Tunnel: {0}" -f $TunnelCIDR)

# --- 1) Pick free vpnid ---
$r_search = Call-Api "GET" "/api/openvpn/instances/search?current=1&rowCount=-1"
$rows = if($r_search.text){ (TryJson $r_search.text).rows } else { @() }
$used = @{}; if($rows){ $rows | ForEach-Object { $used[$_.vpnid] = $true } }
$VPNID = "1"; for($i=1;$i -le 99;$i++){ if(-not $used.ContainsKey("$i")){ $VPNID="$i"; break } }
Write-Host ("  Using free vpnid: {0}" -f $VPNID)

# --- 2) ADD with 25.7 schema ---
$addBody = @{
  instance = @{
    vpnid               = $VPNID
    role                = "server"
    enabled             = "1"
    description         = $Description
    proto               = $State.Settings.Firewall.VpnProto
    port                = $State.Settings.Firewall.VpnListenPort
    dev_type            = $State.Settings.VpnDevType
    topology            = $State.Settings.VpnTopology
    server              = $TunnelCIDR
    verify_client_cert  = "require"
    cert_depth          = "1"
    authmode            = "Local Database"
    ca                  = $CARef
    cert                = $CertRef
    tls_key             = $TLSUUID
  }
}
$AddJson = Join-Path $State.TempDir "ovpn_add.json"; Save-Json $AddJson $addBody
$r_add = Call-Api "POST" "/api/openvpn/instances/add" $AddJson
$uuid = $null; try{ $uuid = (TryJson $r_add.text).uuid }catch{$uuid=$null}
if(-not $uuid){ throw "No uuid returned from add instance: $($r_add.text)" }
$State.VpnInstanceUuid = $uuid
Write-Host ("  Instance created (uuid={0})" -f $uuid) -ForegroundColor Green

# --- 3) SET: Local Network + float ---
$setBody = @{ instance = @{
  push_route    = $LocalCIDR
  local_network = $LocalCIDR
  various_flags = "float"
  cert_depth    = "1"
} }
$SetJson = Join-Path $State.TempDir "ovpn_set_flat.json"; Save-Json $SetJson $setBody
$r_set = Call-Api "POST" "/api/openvpn/instances/set/$uuid" $SetJson
Write-Host ("  Set local_network, push_route, and float flag.")

# --- 4) Apply ---
$tmpEmpty = Join-Path $State.TempDir "empty.json"; Save-Json $tmpEmpty @{}
$apply = Call-Api "POST" "/api/openvpn/service/reconfigure" $tmpEmpty
Write-Host ("  Reconfigure command sent (status: {0})" -f (TryJson $apply.text).status)

# [FIXED] ลบส่วนที่พยายาม Get/Save instance.json ที่พังทิ้ง (เราไม่จำเป็นต้องใช้)

Write-Host "[Task 7/9] Complete" -ForegroundColor Green

