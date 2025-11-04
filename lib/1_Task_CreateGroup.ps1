# Task 1: Create Group
$GroupName = $State.Settings.GroupName
$GroupDesc = $State.Settings.GroupDesc
Write-Host ("  Ensuring group '{0}' exists..." -f $GroupName)

$rows = Get-GroupRows
$exist = $rows | Where-Object { $_.name -eq $GroupName } | Select-Object -First 1
$groupObj = $null

if ($exist) {
  $State.GroupId = Get-GidOrUuid $exist
  $groupObj = $exist
  Write-Host ("  Group '{0}' already exists (id={1})." -f $GroupName, $State.GroupId)
} else {
  $payload = @{ group = @{ name = $GroupName; description = $GroupDesc } }
  $tmp = Join-Path $State.TempDir "group_add.json"; Save-Json $tmp $payload
  $addJson = (Call-Api "POST" "/api/auth/group/add/" $tmp).text
  $addResult = $addJson | ConvertFrom-Json
  Write-Host ("  Created new group '{0}'." -f $GroupName) -ForegroundColor Green
  
  $rows2 = Get-GroupRows
  $grp = $rows2 | Where-Object { $_.name -eq $GroupName } | Select-Object -First 1
  $State.GroupId = Get-GidOrUuid $grp
  $groupObj = $grp
}
if (-not $State.GroupId) { throw "Failed to get GID/UUID for group '$GroupName'" }

# [NEW] Save group data to output folder
Save-Json (Join-Path $State.OutputDataPath "group.json") $groupObj
Write-Host "[Task 1/9] Complete" -ForegroundColor Green