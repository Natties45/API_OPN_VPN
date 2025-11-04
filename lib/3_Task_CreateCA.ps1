# Task 3: Create CA
$now = Get-Date
$CALifetimeDays = $State.Settings.Lifetimes.CALifetimeDays
$exp = $now.AddDays($CALifetimeDays)
$CAName = ('{0}_{1:yyyyMMdd-HHmmss}' -f $State.Settings.NamePatterns.CaPrefix, $now)
$CANameDesc = ('{0}_{1:yyyyMMdd-HHmmss}_exp{2:yyyyMMdd}' -f $State.Settings.NamePatterns.CaPrefix, $now, $exp)

Write-Host ("  Ensuring CA '{0}' exists..." -f $CAName)
$rows = Get-CaRows
$exist = $rows | Where-Object { $_.descr -eq $CANameDesc -or $_.commonname -eq $CAName } | Select-Object -First 1
$caObj = $null

if ($exist) {
  $State.CaRefId = Pick-Id $exist
  $caObj = $exist # <-- นี่คือ CA object ที่มี .crt
  Write-Host ("  CA '{0}' already exists (refid={1})." -f $CAName, $State.CaRefId)
} else {
  $payload = @{
    ca = @{
      action             = "internal"; caref = ""
      descr              = $CANameDesc
      commonname         = $CAName
      key_type           = "2048"; digest = "sha256"
      lifetime           = "$CALifetimeDays"
      country            = "TH"; state = "TH"; city = "TH"
      organization       = "AutoOrg"; organizationalunit = "AutoOU"
      email              = ""; ocsp_uri = ""; crt_payload = ""; prv_payload = ""; serial = ""
    }
  }
  $tmp = Join-Path $State.TempDir "ca_add.json"; Save-Json $tmp $payload
  
  $addJson = (Call-Api "POST" "/api/trust/ca/add" $tmp).text
  $addResult = $addJson | ConvertFrom-Json
  
  # [FIXED] Replaced unreliable Sleep with robust polling function Wait-ForCa
  $row = Wait-ForCa -Descr $CANameDesc -CN $CAName
  if (-not $row) { throw "Failed to create CA or find it after creation." }
  
  $State.CaRefId = Pick-Id $row
  $caObj = $row # <-- นี่คือ CA object ที่มี .crt
  Write-Host ("  Created CA '{0}' (refid={1})." -f $CAName, $State.CaRefId) -ForegroundColor Green
}

# [NEW] Save CA data (ที่มี .crt) to output folder
if ($null -eq $caObj.crt) {
    Write-Warning "  Warning: CA object does not contain 'crt' field. Build-Clients script might fail."
}
Save-Json (Join-Path $State.OutputDataPath "ca.json") $caObj
Write-Host "[Task 3/9] Complete" -ForegroundColor Green