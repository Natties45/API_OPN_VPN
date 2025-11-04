# Task 5: Create Server Cert
$ServerCN  = $State.Settings.NamePatterns.ServerCn
$Days      = $State.Settings.Lifetimes.ServerCertLifetimeDays
$ServerIPs = @() 

Write-Host ("  Ensuring Server Cert '{0}' exists (signed by {1})..." -f $ServerCN, $State.CaRefId)
$IssuedRef = ""
$existing = @(Find-CertsByCN $ServerCN)
$certObj = $null

if ($existing.Count -gt 0) {
  $keep = $existing | Sort-Object -Property @{E={ if($_.valid_from){[int]$_.valid_from}else{0} }} -Descending | Select-Object -First 1
  $IssuedRef = if ($keep.PSObject.Properties['refid']) { [string]$keep.refid } else { "" }
  Write-Host ("  Found existing cert for CN '{0}' (refid={1}). Using this one." -f $ServerCN,$IssuedRef)
  $certObj = $keep
} else {
  $now = Get-Date; $exp = $now.AddDays($Days)
  $descr = ('{0}_{1:yyyyMMdd-HHmmss}_exp{2:yyyyMMdd}' -f $ServerCN, $now, $exp)
  $fields = @{
    action               = "internal"; cert_type = "server_cert"; type = "server"
    caref                = $State.CaRefId
    descr                = $descr
    key_type             = "2048"; digest = "sha256"
    lifetime             = "$Days"
    country              = "TH"; state = "TH"; city = "TH"
    organization         = "AutoOrg"; organizationalunit = "AutoOU"
    commonname           = $ServerCN
    private_key_location = "firewall"
    crt_payload          = ""; prv_payload = ""; csr_payload = ""
  }
  if ($ServerIPs -and $ServerIPs.Count -gt 0) { $fields['altnames_ip'] = ($ServerIPs -join ",") }
  
  $payload = @{ cert = $fields }
  $tmp = Join-Path $State.TempDir "servercert_add.json"; Save-Json $tmp $payload
  
  # [FIXED] API 'add' ส่ง JSON กลับมา
  $addJson = (Call-Api "POST" "/api/trust/cert/add" $tmp).text
  $addResult = $addJson | ConvertFrom-Json
  
  $row = Wait-ForCert -Descr $descr -CN $ServerCN
  if (-not $row) { throw "Failed to find server cert '$ServerCN' after creation." }
  $IssuedRef = if ($row.PSObject.Properties['refid']) { [string]$row.refid } else { "" }
  if (-not $IssuedRef) { throw "Server cert '$ServerCN' was created but has no refid." }
  Write-Host ("  Created server cert '{0}' (refid={1})." -f $ServerCN, $IssuedRef) -ForegroundColor Green
  $certObj = $row
}
$State.ServerCertRefId = $IssuedRef

# [NEW] Save server cert data
Save-Json (Join-Path $State.OutputDataPath "server_cert.json") $certObj

# Prune old ones
foreach ($c in $existing) {
  $rid = if ($c.PSObject.Properties['refid']) { [string]$c.refid } else { "" }
  if ($rid -and $rid -ne $IssuedRef) {
    if (Try-DelCert $rid) {
      Write-Host ("  Pruned old server cert CN='{0}' (refid={1})." -f $ServerCN,$rid) -ForegroundColor DarkGray
    }
  }
}
Write-Host "[Task 5/9] Complete" -ForegroundColor Green