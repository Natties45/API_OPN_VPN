param(
    [int]$ProfileIndex,
    [string]$ProfileName
)

# ====================================================================
# Run-Full-Setup.ps1 (9-Task Version)
# ====================================================================

$ErrorActionPreference = 'Stop'
$PSScriptRoot = (Split-Path -Parent $MyInvocation.MyCommand.Definition)

# --- 0. Load Common Helpers ---
Write-Host "Loading helper functions..."
. (Join-Path $PSScriptRoot "lib\_common_helpers.ps1")

# --- 1. Select Profile ---
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
Write-Host "--- Please Select OPNsense Profile ---" -ForegroundColor Cyan
for ($i = 0; $i -lt $profileCount; $i++) {
    Write-Host (" [{0}] {1} ({2})" -f ($i+1), $ProfileConfig.profiles[$i].ProfileName, $ProfileConfig.profiles[$i].ApiBaseUrl)
}

if (-not $choice) {
    while ($choice -lt 1 -or $choice -gt $profileCount) {
        try { $choice = [int](Read-Host "Enter number (1-$profileCount)") } catch {}
    }
} else {
    $autoProfile = $ProfileConfig.profiles[$choice - 1]
    Write-Host ("Auto-selecting profile [{0}] {1} ({2})" -f $choice, $autoProfile.ProfileName, $autoProfile.ApiBaseUrl) -ForegroundColor Green
}
# --- 2. Load Configs ---
$UsersConfigPath = (Join-Path $PSScriptRoot "config.users.json")
$SettingsConfigPath = (Join-Path $PSScriptRoot "config.settings.json")
if (-not (Test-Path $UsersConfigPath)) { throw "File not found: config.users.json" }
if (-not (Test-Path $SettingsConfigPath)) { throw "File not found: config.settings.json" }

# --- 3. Create State Object ---
$SelectedProfile = $ProfileConfig.profiles[$choice - 1]

# [NEW] สร้าง Subfolder อัตโนมัติ (ตามที่คุณขอ)
$SafeProfileName = $SelectedProfile.ProfileName -replace '[\\/:*?"<>|]', '_' # กันอักขระพิเศษ
$OutputDataPath = Join-Path $PSScriptRoot "output_data\$SafeProfileName"
New-Item -ItemType Directory -Path $OutputDataPath -Force | Out-Null
Write-Host ("Saving build data to: {0}" -f $OutputDataPath)

$State = @{
    Profile = $SelectedProfile
    Users = (Get-Content -Raw -Path $UsersConfigPath | ConvertFrom-Json).users
    Settings = (Get-Content -Raw -Path $SettingsConfigPath | ConvertFrom-Json)
    PSScriptRoot = $PSScriptRoot
    TempDir = (Join-Path $PSScriptRoot "temp_json")
    OutputDataPath = $OutputDataPath # <-- [NEW] ส่ง Path ไปให้ Tasks
    
    # Placeholders for generated assets
    GroupId = $null
    CaRefId = $null
    ServerCertRefId = $null
    ClientCertRefIds = @{} # Map[username] -> refid
    StaticKeyUuid = $null
    VpnInstanceUuid = $null
}
New-Item -ItemType Directory -Path $State.TempDir -Force | Out-Null
Write-Host ("Selected: {0}" -f $State.Profile.ProfileName) -ForegroundColor Green
Write-Host ("Using Temp Directory: {0}" -f $State.TempDir)

# --- 4. Execute 9-Task Pipeline ---
try {
    Write-Host "`n[Task 1/9] Creating Group..." -ForegroundColor Yellow
    . (Join-Path $PSScriptRoot "lib\1_Task_CreateGroup.ps1")

    Write-Host "`n[Task 2/9] Creating Users..." -ForegroundColor Yellow
    . (Join-Path $PSScriptRoot "lib\2_Task_CreateUsers.ps1")
    
    Write-Host "`n[Task 3/9] Creating CA..." -ForegroundColor Yellow
    . (Join-Path $PSScriptRoot "lib\3_Task_CreateCA.ps1")
    
    Write-Host "`n[Task 4/9] Creating Client Certs..." -ForegroundColor Yellow
    . (Join-Path $PSScriptRoot "lib\4_Task_CreateCertClient.ps1")
    
    Write-Host "`n[Task 5/9] Creating Server Cert..." -ForegroundColor Yellow
    . (Join-Path $PSScriptRoot "lib\5_Task_CreateCertServer.ps1")

    Write-Host "`n[Task 6/9] Creating Static Key..." -ForegroundColor Yellow
    . (Join-Path $PSScriptRoot "lib\6_Task_CreateStaticKey.ps1")

    Write-Host "`n[Task 7/9] Creating OpenVPN Instance..." -ForegroundColor Yellow
    . (Join-Path $PSScriptRoot "lib\7_Task_CreateInstance.ps1")

    Write-Host "`n[Task 8/9] Assigning Interface (via SSH)..." -ForegroundColor Yellow
    . (Join-Path $PSScriptRoot "lib\8_Task_AssignInterface.ps1")
    
    Write-Host "`n[Task 9/9] Setting Firewall Rules..." -ForegroundColor Yellow
    . (Join-Path $PSScriptRoot "lib\9_Task_SetFirewall.ps1")

    Write-Host "`n========================================================" -ForegroundColor Cyan
    Write-Host "✅ ALL 9 TASKS COMPLETED SUCCESSFULLY for profile: $($State.Profile.ProfileName)" -ForegroundColor Green
    Write-Host "  Build data saved in: $($State.OutputDataPath)"
    Write-Host "========================================================" -ForegroundColor Cyan
} catch {
    Write-Error "SCRIPT FAILED: $($_.Exception.Message)"
    Write-Error "At Line: $($_.InvocationInfo.ScriptLineNumber), Script: $($_.InvocationInfo.ScriptName)"
    Write-Error "Target: $($_.TargetObject)"
} finally {
    Write-Host "Cleaning up temp directory..."
    Remove-Item -Path $State.TempDir -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "Script finished."


