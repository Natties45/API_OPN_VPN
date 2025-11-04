# Task 4: Create Client Certs
Write-Host "  Checking/Creating Client Certs..."
$ClientCertDays = $State.Settings.Lifetimes.ClientCertLifetimeDays
$allCerts = Get-CertRows

foreach ($name in $State.Users.Name) {
  $certObj = $null
  $exist = $allCerts | Where-Object { ($_.PSObject.Properties['commonname'] -and $_.commonname -eq $name) } | Select-Object -First 1
  
  if ($exist) {
    $refExist = if ($exist.PSObject.Properties['refid']) { [string]$exist.refid } else { "" }
    Write-Host ("  Client cert for '{0}' already exists (refid={1}). Skipping." -f $name, $refExist)
    $State.ClientCertRefIds[$name] = $refExist
    $certObj = $exist # <-- นี่คือ Cert object ที่มี .crt, .prv
  } else {
    $now = Get-Date; $exp = $now.AddDays($ClientCertDays)
    $descr = ('Client_{0}_{1:yyyyMMdd-HHmmss}_exp{2:yyyyMMdd}' -f $name, $now, $exp)
    $payload = @{
      cert = @{
        action               = "internal"; cert_type = "usr_cert"; type = "client"
        caref                = $State.CaRefId
        descr                = $descr
        key_type             = "2048"; digest = "sha256"
        lifetime             = "$ClientCertDays"
        country              = "TH"; state="TH"; city="TH"
        organization         = "AutoOrg"; organizationalunit="AutoOU"
        commonname           = $name
        private_key_location = "firewall" # <-- สำคัญ: บอกให้ API ส่ง Key กลับมา
        crt_payload          = ""; prv_payload = ""; csr_payload = ""
      }
    }

    $tmp = Join-Path $State.TempDir "clientcert_add_$($name).json"; Save-Json $tmp $payload
    
    # [FIXED] API 'add' ส่ง JSON ที่มี crt และ prv กลับมา (เพราะ private_key_location = "firewall")
    $addJson = (Call-Api "POST" "/api/trust/cert/add" $tmp).text
    $addResult = $addJson | ConvertFrom-Json
    
    $row = Wait-ForCert -Descr $descr -CN $name
    if (-not $row) { Write-Warning "  Could not find cert for '$name' after creation. It may fail to export." ; continue }
    $ref = if ($row.PSObject.Properties['refid']) { [string]$row.refid } else { "" }
    if (-not $ref) { Write-Warning "  Cert for '$name' created but has no refid." ; continue }

    Write-Host ("  Created client cert for '{0}' (refid={1})." -f $name, $ref) -ForegroundColor Green
    $State.ClientCertRefIds[$name] = $ref
    $certObj = $row # <-- นี่คือ Cert object ที่มี .crt, .prv
  }

  # [NEW] Save client cert data (ที่มี .crt, .prv) to output folder
  if ($null -eq $certObj.crt -or $null -eq $certObj.prv) {
      Write-Warning "  Warning: Client Cert object for $name does not contain 'crt' or 'prv' field. Build-Clients script might fail."
  }
  Save-Json (Join-Path $State.OutputDataPath "client_$($name).json") $certObj
}
Write-Host "[Task 4/9] Complete" -ForegroundColor Green