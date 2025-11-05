# ====================================================================
# _common_helpers.ps1 (Uses a single API key)
# [VERSION 3 - PS 2.0 Compatibility Fix]
# ====================================================================
$ErrorActionPreference = 'Stop'

# --- TLS / HTTP Settings ---
# Prefer the OS defaults when available (adds TLS 1.3, SChannel policy etc.)
$availableProtocols = [Enum]::GetNames([Net.SecurityProtocolType])
if ($availableProtocols -contains "SystemDefault") {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::SystemDefault
} else {
    $protocols = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls11 -bor [Net.SecurityProtocolType]::Tls
    if ($availableProtocols -contains "Tls13") {
        $protocols = $protocols -bor ([Enum]::Parse([Net.SecurityProtocolType], "Tls13"))
    }
    [Net.ServicePointManager]::SecurityProtocol = $protocols
}
# Accept all certificates via CLR delegate (works on pwsh background threads)
if (-not ('OPNsense.PS.AcceptAllCertsPolicy' -as [type])) {
    Add-Type @"
using System;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;

namespace OPNsense.PS {
    public static class AcceptAllCertsPolicy {
        public static bool Validate(object sender, X509Certificate certificate, X509Chain chain, SslPolicyErrors errors) {
            return true;
        }
    }
}
"@
}
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = [System.Net.Security.RemoteCertificateValidationCallback]([OPNsense.PS.AcceptAllCertsPolicy]::Validate)
$Global:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# --- JSON Helpers ---
function Save-Json($Path, $Obj){
  $jsonText = ConvertTo-Json -InputObject $Obj -Depth 80
  [IO.File]::WriteAllText($Path, $jsonText, $Global:Utf8NoBom)
}

function TryJson($text){
    try { $text | ConvertFrom-Json } catch { $null }
}

# --- API Error Helper (Internal) ---
function Handle-WebException($ErrorRecord, $Method, $Path, $Component="API") {
    $code = "000"
    $text = ""
    if ($_.Exception -is [System.Net.WebException] -and $_.Exception.Response) {
        $code = [string]([int]$_.Exception.Response.StatusCode)
        try {
            $rStream = $_.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($rStream)
            $text = $reader.ReadToEnd()
            $reader.Close()
            $rStream.Close()
        } catch {
            $text = "Failed to read error response stream."
        }
    } else {
        $text = $_.Exception.Message
    }
    throw "API Error ($Component) ($Method $Path): HTTP $code. Response: $text"
}

# --- API Call Helper (Main) ---
# [FIXED] Replaced Invoke-WebRequest (PS 3.0+) with System.Net.WebClient (PS 2.0+)
function Call-Api($Method, $Path, $BodyPath="", $Accept="application/json"){
  $url  = ($State.Profile.ApiBaseUrl.TrimEnd('/')) + $Path
  $pair = "$($State.Profile.ApiKey):$($State.Profile.ApiSecret)"
  $basicAuth = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))

  $wc = New-Object System.Net.WebClient
  $wc.Headers.Add("Authorization", $basicAuth)
  $wc.Headers.Add("Accept", $Accept)
  
  $text = ""
  $code = "000"
  
  try {
    if ($BodyPath) {
      # POST or method with body
      $wc.Headers.Add("Content-Type", "application/json")
      $bodyBytes = [System.IO.File]::ReadAllBytes($BodyPath)
      $responseBytes = $wc.UploadData($url, $Method, $bodyBytes)
      $text = $Global:Utf8NoBom.GetString($responseBytes)
      $code = "200" # UploadData returns bytes, not status. Assume 200 on success.
    } else {
      # GET or method without body
      $text = $wc.DownloadString($url)
      $code = "200" # DownloadString throws on error, so success is 200.
    }
    return [pscustomobject]@{ code = $code; text = $text }
  } catch {
    Handle-WebException $_ $Method $Path "API"
  } finally {
    $wc.Dispose()
  }
}

# --- API Call Helper (Firewall) ---
# [FIXED] Replaced Invoke-RestMethod (PS 3.0+) with System.Net.WebClient (PS 2.0+)
function Call-Api-Firewall($Method, $Path, $BodyObj=$null){
  $uri = ($State.Profile.ApiBaseUrl.TrimEnd('/')) + $Path
  $pair = "$($State.Profile.ApiKey):$($State.Profile.ApiSecret)"
  $basicAuth = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))

  $wc = New-Object System.Net.WebClient
  $wc.Headers.Add("Authorization", $basicAuth)
  $wc.Headers.Add("Accept", "application/json")
  
  $responseText = ""
  
  try {
    if ($Method -eq "POST") {
        $json = ""
        if ($BodyObj -ne $null) { 
            $json = ($BodyObj | ConvertTo-Json -Depth 10)
        }
        $wc.Headers.Add("Content-Type", "application/json")
        $responseText = $wc.UploadString($uri, $Method, $json)
    } else {
        # GET
        $responseText = $wc.DownloadString($uri)
    }
    
    if ([string]::IsNullOrEmpty($responseText)) {
        return $null
    }
    return $responseText | ConvertFrom-Json
  } catch {
    Handle-WebException $_ $Method $Path "Firewall"
  } finally {
    $wc.Dispose()
  }
}


# --- OPNsense API Search Helpers ---
function Get-CaRows {
  $r = Call-Api "GET" "/api/trust/ca/search"
  $o = TryJson $r.text; if ($o) { return $o.rows } else { return @() }
}
function Get-CertRows {
  $r = Call-Api "GET" "/api/trust/cert/search";
  $o = TryJson $r.text; if ($o) { return $o.rows } else { return @() }
}
function Get-UserRows {
  $r = Call-Api "GET" "/api/auth/user/search";
  $o = TryJson $r.text; if ($o) { return $o.rows } else { return @() }
}
function Get-GroupRows {
  $r = Call-Api "GET" "/api/auth/group/search";
  $o = TryJson $r.text; if ($o) { return $o.rows } else { return @() }
}

# --- OPNsense API Object Helpers ---
function Get-GidOrUuid($obj){
  if ($null -ne $obj -and $obj.PSObject.Properties['gid'] -and $obj.gid) { return $obj.gid }
  if ($null -ne $obj -and $obj.PSObject.Properties['uuid'] -and $obj.uuid) { return $obj.uuid }
  return ""
}
function Pick-Id($obj){
  if ($null -eq $obj) { return "" }
  if ($obj.PSObject.Properties['refid'] -and $obj.refid) { return [string]$obj.refid }
  if ($obj.PSObject.Properties['uuid']  -and $obj.uuid ) { return [string]$obj.uuid  }
  if ($obj.PSObject.Properties['id']    -and $obj.id   ) { return [string]$obj.id    }
  return ""
}
function Get-Label($row){
  if ($row.PSObject.Properties['descr'] -and $row.descr) { return [string]$row.descr }
  elseif ($row.PSObject.Properties['name'] -and $row.name) { return [string]$row.name }
  elseif ($row.PSObject.Properties['commonname'] -and $row.commonname) { return [string]$row.commonname }
  return ""
}

# [NEW] Added Wait-ForCa (for Task 3)
function Wait-ForCa([string]$Descr,[string]$CN,[int]$Tries=10,[int]$DelayMs=500){
  for ($i=0; $i -lt $Tries; $i++){
    $rows = Get-CaRows
    $row  = $rows | Where-Object {
      ($_.PSObject.Properties['descr'] -and $_.descr -eq $Descr) -or
      ($_.PSObject.Properties['commonname'] -and $_.commonname -eq $CN)
    } | Select-Object -First 1
    if ($row) { return $row }
    Write-Host "  ...waiting for CA '$CN' (try $($i+1)/$Tries)..." -ForegroundColor DarkGray
    Start-Sleep -Milliseconds $DelayMs
  }
  return $null
}

function Wait-ForCert([string]$Descr,[string]$CN,[int]$Tries=10,[int]$DelayMs=500){
  for ($i=0; $i -lt $Tries; $i++){
    $rows = Get-CertRows
    $row  = $rows | Where-Object {
      ($_.PSObject.Properties['descr'] -and $_.descr -eq $Descr) -or
      ($_.PSObject.Properties['commonname'] -and $_.commonname -eq $CN) -or
      ($_.PSObject.Properties['name'] -and ($_.name -like "*CN=$CN*"))
    } | Select-Object -First 1
    if ($row) { return $row }
    Write-Host "  ...waiting for Cert '$CN' (try $($i+1)/$Tries)..." -ForegroundColor DarkGray
    Start-Sleep -Milliseconds $DelayMs
  }
  return $null
}

function Find-CertsByCN([string]$CN){
  $rows = Get-CertRows
  $rows | Where-Object {
    ($_.PSObject.Properties['commonname'] -and $_.commonname -eq $CN) -or
    ($_.PSObject.Properties['name']       -and ($_.name -like "*CN=$CN*")) -or
    ($_.PSObject.Properties['descr']      -and $_.descr -like "$CN*")
  }
}

function Try-DelCert([string]$RefId){
  try {
    $res = Call-Api "POST" ("/api/trust/cert/del/{0}" -f $RefId)
    if ($res.code -match '^2' -and $res.text -notmatch '"failed"') { return $true }
  } catch {}
  Write-Host ("  ...del cert {0} (method 1) failed, trying next..." -f $RefId) -ForegroundColor DarkGray
  
  try {
    $tmp = Join-Path $State.TempDir "tmp_del_cert.json"; Save-Json $tmp @{ refid = $RefId }
    $res2 = Call-Api "POST" "/api/trust/cert/del" $tmp
    if ($res2.code -match '^2' -and $res2.text -notmatch '"failed"') { return $true }
  } catch {}
  
  Write-Warning ("Could not delete cert refid={0} (skipping)" -f $RefId)
  return $false
}

# --- SSH Helpers ---
# [FIXED] Changed from auto-install to check-and-throw
function Ensure-PoshSSH {
  if (-not (Get-Module -ListAvailable -Name Posh-SSH)) {
    throw "Module 'Posh-SSH' is not installed. Please run: `Install-Module -Name Posh-SSH -Scope CurrentUser` and try again."
  }
  Import-Module Posh-SSH -ErrorAction Stop
}






