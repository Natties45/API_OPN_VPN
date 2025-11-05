param(
    [int]$ProfileIndex,
    [string]$ProfileName
)

# ====================================================================
# Build-Ovpn-Files.ps1
#
# อ่านไฟล์ JSON จาก output_data/PROFILE_NAME
# และประกอบร่างเป็นไฟล์ .ovpn ที่พร้อมใช้งาน
# ====================================================================
$ErrorActionPreference = 'Stop'
$PSScriptRoot = (Split-Path -Parent $MyInvocation.MyCommand.Definition)
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

# --- 1. Select Profile (ต้องรู้ว่ากำลัง Build ให้ Profile ไหน) ---
$ProfileConfigPath = (Join-Path $PSScriptRoot "config.profiles.json")
if (-not (Test-Path $ProfileConfigPath)) { throw "File not found: config.profiles.json" }
$ProfileConfig = Get-Content -Raw -Path $ProfileConfigPath | ConvertFrom-Json

$profileCount = $ProfileConfig.profiles.Count
if ($profileCount -lt 1) { throw "No profiles defined in config.profiles.json." }

$choice = $null
if ($PSBoundParameters.ContainsKey('ProfileName') -and $ProfileName) {
    for ($i = 0; $i -lt $profileCount; $i++) {
        if ($ProfileConfig.profiles[$i].ProfileName -ieq $ProfileName) {
            $choice = $i + 1
            break
        }
    }
    if (-not $choice) {
        throw "Profile '$ProfileName' was not found in config.profiles.json."
    }
}
if (-not $choice -and $PSBoundParameters.ContainsKey('ProfileIndex')) {
    if ($ProfileIndex -lt 1 -or $ProfileIndex -gt $profileCount) {
        throw "ProfileIndex must be between 1 and $profileCount."
    }
    $choice = [int]$ProfileIndex
}
Write-Host "--- Please Select Profile to Build OVPNs for ---" -ForegroundColor Cyan
for ($i = 0; $i -lt $profileCount; $i++) {
    Write-Host (" [{0}] {1}" -f ($i+1), $ProfileConfig.profiles[$i].ProfileName)
}

if (-not $choice) {
    while ($choice -lt 1 -or $choice -gt $profileCount) {
        try { $choice = [int](Read-Host "Enter number (1-$profileCount)") } catch {}
    }
} else {
    $autoProfile = $ProfileConfig.profiles[$choice - 1]
    Write-Host ("Auto-selecting profile [{0}] {1}" -f $choice, $autoProfile.ProfileName) -ForegroundColor Green
}
# --- 2. Set Paths ---
$SelectedProfile = $ProfileConfig.profiles[$choice - 1]
$SettingsConfigPath = (Join-Path $PSScriptRoot "config.settings.json")

# สร้าง Path ไปยังโฟลเดอร์ build data (ที่ Run-Full-Setup สร้างไว้)
$SafeProfileName = $SelectedProfile.ProfileName -replace '[\\/:*?"<>|]', '_'
$BuildDataPath = Join-Path $PSScriptRoot "output_data\$SafeProfileName"

# สร้าง Path สำหรับเก็บไฟล์ .ovpn (โฟลเดอร์ย่อยใหม่)
$OvpnOutputPath = Join-Path $BuildDataPath "_ovpn_files"
New-Item -ItemType Directory -Path $OvpnOutputPath -Force | Out-Null

Write-Host ("Loading build data from: {0}" -f $BuildDataPath) -ForegroundColor Green

# --- 3. Load Shared Data (ไฟล์ที่ใช้ร่วมกันทุกคน) ---
if (-not (Test-Path $SettingsConfigPath)) { throw "File not found: config.settings.json" }
$Settings = Get-Content -Raw -Path $SettingsConfigPath | ConvertFrom-Json

$CaJson = Get-Content (Join-Path $BuildDataPath "ca.json") | ConvertFrom-Json
$StaticKeyJson = Get-Content (Join-Path $BuildDataPath "static_key.json") | ConvertFrom-Json
$ServerCertJson = Get-Content (Join-Path $BuildDataPath "server_cert.json") | ConvertFrom-Json

# --- 4. Extract Shared Variables ---
$CaPayload        = $CaJson.crt_payload.Trim()
$StaticKeyPayload = $StaticKeyJson.key.Trim()
$ServerHost       = $SelectedProfile.SshHost
$ServerPort       = $Settings.Firewall.VpnListenPort
$ServerProto      = $Settings.Firewall.VpnProto
$VpnDevType       = $Settings.VpnDevType

# แปลง Subject Name จาก /C=TH/ST=TH... เป็น C=TH, ST=TH... ให้ตรงเป๊ะกับ OPNsense export
$ServerCnSubject = $ServerCertJson.name.TrimStart('/') -replace '/', ', '

Write-Host ("Server: {0}:{1} ({2})" -f $ServerHost, $ServerPort, $ServerProto)
Write-Host ("Verify CN: {0}" -f $ServerCnSubject)

# --- 5. Find Client JSON files ---
$ClientJsonFiles = Get-ChildItem -Path $BuildDataPath -Filter "client_*.json"
if ($ClientJsonFiles.Count -eq 0) {
    throw "No 'client_*.json' files found in '$BuildDataPath'. Did Task 4 run correctly?"
}

Write-Host ("Found {0} client file(s). Building..." -f $ClientJsonFiles.Count) -ForegroundColor Yellow

# --- 6. Core Loop: Iterate and Build ---
foreach ($File in $ClientJsonFiles) {
    $ClientName = $File.BaseName -replace 'client_'
    Write-Host "  Building for '$ClientName'..."

    $ClientJson = Get-Content $File.FullName | ConvertFrom-Json
    
    # ดึง Cert และ Key ส่วนตัวของ Client คนนี้
    $ClientCertPayload = $ClientJson.crt_payload.Trim()
    $ClientKeyPayload  = $ClientJson.prv_payload.Trim()

    # ประกอบร่าง OVPN Template (Here-String)
    # โครงสร้างนี้อ้างอิงจากไฟล์ตัวอย่างที่คุณส่งมา
    $OvpnTemplate = @"
dev $VpnDevType
persist-tun
persist-key
client
resolv-retry infinite
remote $ServerHost $ServerPort $ServerProto
lport 0
verify-x509-name "$ServerCnSubject" subject
remote-cert-tls server
auth-user-pass

<ca>
$CaPayload
</ca>

<cert>
$ClientCertPayload
</cert>

<key>
$ClientKeyPayload
</key>

<tls-crypt>
$StaticKeyPayload
</tls-crypt>
"@

    # บันทึกไฟล์ (ใช้ ASCII encoding มาตรฐานสำหรับ .ovpn)
    $FinalPath = Join-Path $OvpnOutputPath "$ClientName.ovpn"
    $OvpnTemplate | Set-Content -Path $FinalPath -Encoding Ascii -Force
    Write-Host "  -> Created: $FinalPath" -ForegroundColor Green
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "✅ OVPN Build Complete."
Write-Host "  Files saved in: $OvpnOutputPath"
Write-Host "========================================================" -ForegroundColor Cyan

