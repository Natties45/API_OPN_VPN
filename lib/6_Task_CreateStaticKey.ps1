# Task 6: Create Static Key
$emptyJsonPath = Join-Path $State.TempDir "empty.json"
Save-Json $emptyJsonPath @{}

$ModeShort = if ($State.Settings.StaticKeyMode -match '^tls-?auth$') { "auth" } else { "crypt" }
$Desc      = "{0}-{1}-{2}" -f $State.Settings.NamePatterns.StaticKeyPrefix, $ModeShort, (Get-Date -Format "yyyyMMdd-HHmmss")
Write-Host ("  Ensuring Static Key '{0}' exists..." -f $Desc)

$r_search = Call-Api "POST" "/api/openvpn/instances/search_static_key" $emptyJsonPath
$rowsSK = @( (TryJson $r_search.text).rows )
$exist = $rowsSK | Where-Object { $_.description -like "$($State.Settings.NamePatterns.StaticKeyPrefix)-*" -and $_.mode -eq $ModeShort } | Sort-Object description -Descending | Select-Object -First 1

if ($exist) {
    $State.StaticKeyUuid = $exist.uuid
    Write-Host ("  Found existing static key '{0}' (uuid={1}). Using this one." -f $exist.description, $exist.uuid)
    # [NEW] Save existing key data
    $sk_content = (Call-Api "GET" "/api/openvpn/instances/get_static_key/$($State.StaticKeyUuid)").text
    Save-Json (Join-Path $State.OutputDataPath "static_key.json") ($sk_content | ConvertFrom-Json)
} else {
    $genJson = (Call-Api "GET" "/api/openvpn/instances/gen_key/secret").text
    $keyText = ($genJson | ConvertFrom-Json).key
    
    # [FIXED] เปลี่ยนข้อความ Error เป็นภาษาอังกฤษ
    if ($keyText -notmatch 'BEGIN OpenVPN Static key V1') {
      throw "Key from gen_key/secret is not a valid Static key V1. API returned: $genJson"
    }
    
    # [NEW] Save generated key data
    Save-Json (Join-Path $State.OutputDataPath "static_key.json") ($genJson | ConvertFrom-Json)

    $payload = @{ statickey = @{ description=$Desc; mode=$ModeShort; key=$keyText } }
    $tmp = Join-Path $State.TempDir "static_key_add.json"; Save-Json $tmp $payload
    $add = Call-Api "POST" "/api/openvpn/instances/add_static_key" $tmp
    
    $r_search2 = Call-Api "POST" "/api/openvpn/instances/search_static_key" $emptyJsonPath
    $row = @( (TryJson $r_search2.text).rows ) | Where-Object { $_.description -eq $Desc } | Select-Object -First 1
    
    if (-not $row -or -not $row.uuid) { throw "Failed to find static key '$Desc' after creation."}
    $State.StaticKeyUuid = $row.uuid
    Write-Host ("  Created static key '{0}' (uuid={1})." -f $Desc, $State.StaticKeyUuid) -ForegroundColor Green
}

$null = Call-Api "POST" "/api/openvpn/service/reconfigure" $emptyJsonPath
Write-Host "[Task 6/9] Complete" -ForegroundColor Green