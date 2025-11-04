# Task 2: Create Users
Write-Host "  Checking/Creating Users..."
$uRows = Get-UserRows
foreach ($u in $State.Users) {
  $exist = $uRows | Where-Object { $_.name -eq $u.Name } | Select-Object -First 1
  if ($exist) {
    Write-Host ("  User '{0}' already exists. Skipping." -f $u.Name)
    continue
  }

  $payload = @{
    user = @{
      disabled = "0"
      name = $u.Name
      password = $u.Password
      scrambled_password = "0"
      descr = $u.Full
      # [FIXED] Wrapped the 'if' statement in a subexpression operator $()
      email = $(if ($u.PSObject.Properties.Name -contains 'Email') { $u.Email } else { "" })
      comment = "VPN user (auto)"
      group_memberships = "$($State.GroupId)" # Add to group
    }
  }
  $tmp = Join-Path $State.TempDir "user_add_$($u.Name).json"; Save-Json $tmp $payload
  $res = Call-Api "POST" "/api/auth/user/add/" $tmp
  Write-Host ("  Created user '{0}'." -f $u.Name) -ForegroundColor Green
}
Write-Host "[Task 2/9] Complete" -ForegroundColor Green